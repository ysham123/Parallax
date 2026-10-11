"""Paired local executor. Only outbound HTTPS; no listener or credential upload."""
from __future__ import annotations
import argparse
import asyncio
import fcntl
import getpass
import json
from pathlib import Path
import secrets
import socket
import sys
import time
from urllib.parse import urlsplit
import httpx
from .executors import encode, permitted, digest, MAX_MESSAGE, is_control
from .server import create_app
from .store import Store, state_directory

WORKER_FEATURES = ["workflow-v2", "workflow-task-settings-v1", "worker-control-v1", "worker-byte-batches-v1", "pilot-evaluation-v1", "pilot-observations-v1"]
TRANSPORT_DETAIL = "Some evidence exceeds the relay's 8 MiB message limit. Inspect the complete candidate in local Studio; team approval is unavailable for an oversized candidate."


def serialized(value):
    return json.dumps(value, separators=(",", ":"))


def evidence_batches(runs, events, *, maximum=MAX_MESSAGE):
    """Budget the exact transmitted JSON, including escaping and protocol fields.

    Oversized records stay local. An oversized event stops replay at that gap;
    accepting a later sequence must never pretend the missing event was stored.
    Runs have independent identities and can still be mirrored around that gap.
    """
    batches, problems = [], []
    current = {"runs": [], "events": [], "features": WORKER_FEATURES}
    size = len(serialized(current).encode())
    for field, values in (("runs", runs), ("events", events)):
        for value in values:
            data = serialized(value)
            amount = len(data.encode())
            empty = {"runs": [], "events": [], "features": WORKER_FEATURES}
            if amount + len(serialized(empty).encode()) > maximum:
                key = value["run_id"] if field == "runs" else str(value["sequence"])
                problems.append({"kind": field, "key": key, "run_id": value["run_id"],
                                 "bytes": amount, "fingerprint": digest(data), "limit_bytes": maximum})
                if field == "events":
                    break
                continue
            extra = amount + int(bool(current[field]))
            if size + extra > maximum:
                batches.append(current)
                current = empty
                size = len(serialized(current).encode())
                extra = amount
            current[field].append(value)
            size += extra
    if current["runs"] or current["events"]:
        batches.append(current)
    return batches, problems


class WorkerRuntime:
    def __init__(self, store, workspaces, *, registry=None):
        self.store = store
        self.workspaces = tuple(Path(p).expanduser().resolve() for p in workspaces)
        if not self.workspaces or any(not p.is_dir() for p in self.workspaces):
            raise ValueError("Approve at least one existing project directory with --workspace")
        if any(store.home.is_relative_to(p) for p in self.workspaces):
            raise ValueError("Worker state must be outside every approved project")
        self.token = secrets.token_urlsafe(32)
        self.app = create_app(store, registry, token=self.token, workspace=str(self.workspaces[0]), allowed_workspaces=self.workspaces)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer " + self.token})
        self.inflight = {}
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS worker_dispatch(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                response TEXT, started REAL NOT NULL, read_only INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS worker_evidence_problems(kind TEXT NOT NULL, record_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,record_key));
            """)

    async def __aenter__(self):
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()
        await self.lifespan.__aexit__(*args)

    async def dispatch(self, command):
        identifier = command["id"]
        fingerprint = digest(encode({k: command.get(k) for k in ("method", "path", "query", "body", "authority")}))
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_dispatch WHERE read_only=1 AND response IS NOT NULL AND started<?", (time.time()-300,))
            row = db.execute("SELECT fingerprint,response FROM worker_dispatch WHERE id=?", (identifier,)).fetchone()
        if row:
            if row[0] != fingerprint:
                return {"status": 409, "body": {"detail": "Request identity was reused with different content"}, "content_type": "application/json"}
            if row[1]:
                return json.loads(row[1])
            # A process may have died after the engine persisted its run, but
            # before recording a reply. Never infer that dispatch did not happen.
            return {"status": 409, "body": {"detail": "Interrupted request requires reconciliation. Inspect saved runs before retrying; no duplicate work was dispatched."}, "content_type": "application/json"}
        if not permitted(command["method"], command["path"], command.get("query", "")):
            return {"status": 403, "body": {"detail": "Worker operation denied"}, "content_type": "application/json"}
        if command.get("expires_at", 0) < time.time():
            return {"status": 408, "body": {"detail": "Request expired before dispatch; no work was started"}, "content_type": "application/json"}
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_dispatch VALUES(?,?,NULL,?,?)", (identifier, fingerprint, time.time(), int(command["method"]=="GET")))
        try:
            path = command["path"] + ("?" + command["query"] if command.get("query") else "")
            headers = {"X-Parallax-Authority":encode(command["authority"])} if command.get("authority") else {}
            response = await self.client.request(command["method"], path, json=command.get("body"), headers=headers)
            content_type = response.headers.get("content-type", "application/json").split(";")[0]
            body = response.json() if content_type == "application/json" else response.text
            reply = {"status": response.status_code, "body": body, "content_type": content_type}
            data = serialized(reply)
            if len(data.encode()) > MAX_MESSAGE:
                run_id = body.get("run_id") if isinstance(body, dict) else None
                self.record_reply_problem(command["path"], data, run_id)
                reply = {"status": 413, "body": {"code": "evidence_exceeds_transport_limit", "detail": TRANSPORT_DETAIL,
                         "limit_bytes": MAX_MESSAGE, "full_evidence_available_locally": True}, "content_type": "application/json"}
            elif response.status_code < 400:
                with self.store.connect() as db:
                    db.execute("DELETE FROM worker_evidence_problems WHERE kind='reply' AND record_key=?", (command["path"],))
        except Exception:
            reply = {"status": 500, "body": {"detail": "Worker operation failed. Inspect its local log and saved run history before retrying."}, "content_type": "application/json"}
        with self.store.connect() as db:
            db.execute("UPDATE worker_dispatch SET response=? WHERE id=?", (encode(reply), identifier))
        return reply

    def snapshot(self, hashes, cursor):
        changed = []
        for result in self.store.runs():
            data = serialized(result)
            if hashes.get(result["run_id"]) != digest(data):
                changed.append(result)
        with self.store.connect() as db:
            events = db.execute("SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT 100", (cursor,)).fetchall()
        return changed, [{"schema_version": "1.1", "run_id": e["run_id"], "sequence": e["sequence"], "timestamp": e["timestamp"], "kind": e["kind"], "task_id": e["task_id"], "data": json.loads(e["data"])} for e in events]

    def record_problems(self, problems):
        with self.store.connect() as db:
            previous = {(r[0], r[1]): r[2] for r in db.execute("SELECT kind,record_key,fingerprint FROM worker_evidence_problems")}
            db.execute("DELETE FROM worker_evidence_problems WHERE kind IN ('runs','events')")
            for problem in problems:
                db.execute("INSERT INTO worker_evidence_problems VALUES(?,?,?,?)",
                           (problem["kind"], problem["key"], problem["fingerprint"], serialized(problem)))
        for problem in problems:
            if previous.get((problem["kind"], problem["key"])) != problem["fingerprint"]:
                self.store.event(problem["run_id"], "evidence_transport", {"code": "evidence_exceeds_transport_limit",
                    "kind": problem["kind"], "bytes": problem["bytes"], "limit_bytes": problem["limit_bytes"],
                    "full_evidence_available_locally": True, "detail": TRANSPORT_DETAIL})

    def record_reply_problem(self, path, data, run_id):
        problem = {"kind": "reply", "key": path, "bytes": len(data.encode()), "fingerprint": digest(data),
                   "limit_bytes": MAX_MESSAGE, "run_id": run_id}
        with self.store.connect() as db:
            previous = db.execute("SELECT fingerprint FROM worker_evidence_problems WHERE kind='reply' AND record_key=?", (path,)).fetchone()
            db.execute("INSERT INTO worker_evidence_problems VALUES('reply',?,?,?) ON CONFLICT(kind,record_key) DO UPDATE SET fingerprint=excluded.fingerprint,body=excluded.body",
                       (path, problem["fingerprint"], serialized(problem)))
        if run_id and (not previous or previous[0] != problem["fingerprint"]):
            self.store.event(run_id, "evidence_transport", {"code": "evidence_exceeds_transport_limit", "kind": "reply",
                "bytes": problem["bytes"], "limit_bytes": MAX_MESSAGE, "full_evidence_available_locally": True, "detail": TRANSPORT_DETAIL})

    def transport_status(self):
        with self.store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM worker_evidence_problems").fetchone()[0]
        return {"status": "local_evidence_only" if count else "ok", "problem_count": min(count, 1000),
                "limit_bytes": MAX_MESSAGE, "detail": TRANSPORT_DETAIL if count else ""}


async def run_worker(url, state, workspaces, *, name, pair_code=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Worker relay must be an exact HTTPS origin")
    url = url.rstrip("/")
    store = Store(state)
    config_path = store.home / "worker-connection.json"
    try:
        config = json.loads(config_path.read_text())
    except FileNotFoundError:
        config = None
    # Engine recovery and locking are performed even if the relay is offline.
    async with WorkerRuntime(store, workspaces) as runtime, httpx.AsyncClient(base_url=url, timeout=20, trust_env=False, follow_redirects=False) as remote:
        if config and (config.get("url") != url or config.get("workspaces") != [str(p) for p in runtime.workspaces]):
            raise ValueError("Relay or approved projects changed. Use a new worker state directory and pair again.")
        if not config:
            if not pair_code:
                pair_code = getpass.getpass("One-time Studio pairing code: ").strip()
            response = await remote.post("/api/worker/connect", json={"code": pair_code, "name": name, "platform": sys.platform, "workspaces": [str(p) for p in runtime.workspaces], "features":WORKER_FEATURES})
            if response.status_code != 200:
                raise ValueError("Pairing failed. Generate a fresh code in Studio and retry.")
            config = {**response.json(), "url": url, "workspaces": [str(p) for p in runtime.workspaces]}
            temporary = config_path.with_suffix(".tmp")
            temporary.touch(mode=0o600)
            temporary.chmod(0o600)
            temporary.write_text(encode(config))
            temporary.replace(config_path)
        remote.headers["Authorization"] = "Bearer " + config["token"]
        print(json.dumps({"ok": True, "worker": config["id"], "name": name, "relay": url, "approved_projects": config["workspaces"]}), flush=True)
        tasks, replies, hashes = {}, {}, {}
        async def checked(response):
            if response.status_code == 401:
                raise PermissionError("Worker connection revoked. Active local runs will be interrupted and preserved.")
            response.raise_for_status()
            return response

        async def control():
            modern = True
            while True:
                try:
                    status = await asyncio.to_thread(runtime.transport_status)
                    if modern:
                        response = await remote.post("/api/worker/heartbeat", json={"features": WORKER_FEATURES, "transport_status": status})
                        if response.status_code in {404, 405}:
                            modern = False  # Older relay: its empty sync also refreshes liveness.
                        else:
                            await checked(response)
                    if not modern:
                        await checked(await remote.post("/api/worker/sync", json={"runs": [], "events": [], "features": WORKER_FEATURES}))
                    for identifier, task in list(tasks.items()):
                        if task.done():
                            replies[identifier] = task.result()
                            del tasks[identifier]
                    response = await checked(await remote.get("/api/worker/next"))
                    for command in response.json():
                        identifier = command["id"]
                        if identifier in tasks or identifier in replies:
                            continue
                        priority = is_control(command["method"], command["path"])
                        count = sum(getattr(t, "parallax_control", False) == priority for t in tasks.values())
                        if count < (2 if priority else 4):
                            task = asyncio.create_task(runtime.dispatch(command))
                            task.parallax_control = priority
                            tasks[identifier] = task
                except PermissionError:
                    raise
                except (httpx.HTTPError, OSError):
                    pass  # Connectivity errors never imply revocation.
                await asyncio.sleep(1)

        async def deliver_replies():
            while True:
                for identifier, reply in list(replies.items()):
                    try:
                        response = await remote.post("/api/worker/reply", json={"id": identifier, **reply})
                        if response.status_code == 404:
                            replies.pop(identifier, None)
                            continue
                        await checked(response)
                        replies.pop(identifier, None)
                    except PermissionError:
                        raise
                    except (httpx.HTTPError, OSError):
                        continue
                await asyncio.sleep(1)

        async def evidence():
            cursor, last_notice = 0, None
            while True:
                try:
                    runs, events = await asyncio.to_thread(runtime.snapshot, hashes, cursor)
                    batches, problems = await asyncio.to_thread(evidence_batches, runs, events)
                    await asyncio.to_thread(runtime.record_problems, problems)
                    for batch in batches:
                        response = await checked(await remote.post("/api/worker/sync", content=serialized(batch).encode(),
                                                                  headers={"Content-Type": "application/json"}))
                        if response.json().get("stored", True) is False:
                            break
                        # Hashes/cursors are committed only after this exact batch
                        # was accepted; a later refusal cannot acknowledge it.
                        for result in batch["runs"]:
                            hashes[result["run_id"]] = digest(serialized(result))
                        if batch["events"]:
                            cursor = batch["events"][-1]["sequence"]
                    last_notice = "online"
                except PermissionError:
                    raise
                except (httpx.HTTPError, OSError, ValueError):
                    if last_notice != "offline":
                        print("Relay evidence transfer paused. Local evidence is preserved; control polling continues independently.", flush=True)
                    last_notice = "offline"
                await asyncio.sleep(1)

        loops = [asyncio.create_task(control()), asyncio.create_task(evidence()), asyncio.create_task(deliver_replies())]
        try:
            await asyncio.gather(*loops)
        finally:
            for loop in loops: loop.cancel()
            for task in tasks.values(): task.cancel()
            await asyncio.gather(*loops, *tasks.values(), return_exceptions=True)


def add_arguments(parser):
    parser.add_argument("--url", required=True)
    parser.add_argument("--workspace", action="append", required=True)
    parser.add_argument("--name", default=socket.gethostname())
    parser.add_argument("--state", type=Path)
    parser.add_argument("--pair-file", type=Path, help="Private file containing a one-time code; otherwise prompt without echo")
    return parser

def launch(args):
    home = args.state or state_directory() / "workers" / digest(args.url.rstrip('/'))[:12]
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (home / "worker.lock").open("a") as lock, (home / "runtime.lock").open("a") as runtime_lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("This worker state already has an active owner")
        try:
            asyncio.run(run_worker(args.url, home, args.workspace, name=args.name, pair_code=args.pair_file.read_text().strip() if args.pair_file else None))
        except KeyboardInterrupt:
            pass
        except (OSError, ValueError, PermissionError) as exc:
            raise SystemExit(str(exc))

def main():
    parser = add_arguments(argparse.ArgumentParser(description="Connect an approved local project to hosted Studio without opening a port"))
    launch(parser.parse_args())


if __name__ == "__main__": main()
