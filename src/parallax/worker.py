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
from .executors import encode, permitted, digest
from .server import create_app
from .store import Store, state_directory


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
        fingerprint = digest(encode({k: command.get(k) for k in ("method", "path", "query", "body")}))
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
            response = await self.client.request(command["method"], path, json=command.get("body"))
            content_type = response.headers.get("content-type", "application/json").split(";")[0]
            body = response.json() if content_type == "application/json" else response.text
            reply = {"status": response.status_code, "body": body, "content_type": content_type}
            encode(reply)
        except Exception:
            reply = {"status": 500, "body": {"detail": "Worker operation failed. Inspect its local log and saved run history before retrying."}, "content_type": "application/json"}
        with self.store.connect() as db:
            db.execute("UPDATE worker_dispatch SET response=? WHERE id=?", (encode(reply), identifier))
        return reply

    def snapshot(self, hashes, cursor):
        changed = []
        for result in self.store.runs():
            serialized = encode(result)
            if hashes.get(result["run_id"]) != digest(serialized):
                changed.append(result)
        with self.store.connect() as db:
            events = db.execute("SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT 100", (cursor,)).fetchall()
        return changed, [{"schema_version": "1.1", "run_id": e["run_id"], "sequence": e["sequence"], "timestamp": e["timestamp"], "kind": e["kind"], "task_id": e["task_id"], "data": json.loads(e["data"])} for e in events]


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
            response = await remote.post("/api/worker/connect", json={"code": pair_code, "name": name, "platform": sys.platform, "workspaces": [str(p) for p in runtime.workspaces]})
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
        tasks, replies, hashes, cursor = {}, {}, {}, 0
        last_notice = None
        try:
            while True:
                try:
                    for identifier, task in list(tasks.items()):
                        if task.done():
                            replies[identifier] = task.result()
                            del tasks[identifier]
                    for identifier, reply in list(replies.items()):
                        response = await remote.post("/api/worker/reply", json={"id": identifier, **reply})
                        if response.status_code == 401:
                            raise PermissionError("Worker connection revoked. Active local runs will be interrupted and preserved.")
                        if response.status_code == 404:
                            # Completed read replies may have aged out while
                            # disconnected. Their journal still prevents repeats.
                            del replies[identifier]
                            continue
                        response.raise_for_status()
                        del replies[identifier]
                    runs, events = runtime.snapshot(hashes, cursor)
                    response = await remote.post("/api/worker/sync", json={"runs": runs, "events": events})
                    if response.status_code == 401:
                        raise PermissionError("Worker connection revoked. Active local runs will be interrupted and preserved.")
                    response.raise_for_status()
                    # A relay low on storage keeps the machine reachable but declines evidence; resend it later.
                    try:
                        stored = response.json().get("stored", True) is not False
                    except (ValueError, AttributeError):
                        stored = True
                    if stored:
                        for result in runs:
                            hashes[result["run_id"]] = digest(encode(result))
                        if events:
                            cursor = events[-1]["sequence"]
                    response = await remote.get("/api/worker/next")
                    if response.status_code == 401:
                        raise PermissionError("Worker connection revoked. Active local runs will be interrupted and preserved.")
                    response.raise_for_status()
                    for command in response.json():
                        identifier = command["id"]
                        if identifier not in tasks and identifier not in replies and len(tasks) < 4:
                            tasks[identifier] = asyncio.create_task(runtime.dispatch(command))
                    if last_notice == "offline":
                        print("Relay reconnected; replaying saved run evidence.", flush=True)
                    last_notice = "online"
                except PermissionError:
                    raise
                except (httpx.HTTPError, OSError):
                    if last_notice != "offline":
                        print("Relay unavailable. Authorized local runs continue; Studio controls will reconnect when the network returns.", flush=True)
                    last_notice = "offline"
                await asyncio.sleep(1)
        finally:
            for task in tasks.values(): task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)


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
