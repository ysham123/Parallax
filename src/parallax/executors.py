"""Outbound, credential-scoped worker relay for hosted workspaces.

The relay carries typed Studio operations, never shell commands, file mounts,
provider credentials, or arbitrary URLs. Execution and integration stay on the
paired machine. Every Studio-facing operation names the caller's workspace and
only reaches machines paired into that workspace; worker credentials reach only
their own queue and evidence.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import secrets
import shutil
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs
from fastapi import HTTPException
from .store import allow_rate

MAX_MESSAGE = 8 * 1024 * 1024
ONLINE_SECONDS = 30
PAIR_SECONDS = 300
COMMAND_RETENTION = 86400
OWNER_WORKSPACE = "owner"
MIN_FREE_BYTES = 512 * 1024 * 1024
RUN_PATH = re.compile(r"/api/runs/[a-f0-9-]{36}")


@dataclass(frozen=True)
class WorkspaceLimits:
    workers: int
    pending_pairs: int
    pairs_per_hour: int
    pending_commands: int
    pending_bytes: int  # request payloads waiting for one machine
    relayed_per_window: int  # relayed Studio requests per RELAY_WINDOW seconds
    evidence_bytes: int  # mirrored events and cached responses retained per machine
    event_bytes: int  # larger events are mirrored as a truncation marker
    relay_requests: int  # concurrent Studio requests waiting on machines
    event_streams: int  # concurrent replay streams


RELAY_WINDOW = 300
OPERATOR_LIMITS = WorkspaceLimits(workers=50, pending_pairs=10, pairs_per_hour=120, pending_commands=128, pending_bytes=256 * 1024 ** 2,
                                  relayed_per_window=6000, evidence_bytes=2 * 1024 ** 3, event_bytes=MAX_MESSAGE,
                                  relay_requests=64, event_streams=64)
PERSONAL_LIMITS = WorkspaceLimits(workers=3, pending_pairs=3, pairs_per_hour=20, pending_commands=32, pending_bytes=32 * 1024 ** 2,
                                  relayed_per_window=600, evidence_bytes=96 * 1024 ** 2, event_bytes=256 * 1024,
                                  relay_requests=16, event_streams=8)
LOW_DISK_BODY = 64 * 1024


def limits_for(workspace: str) -> WorkspaceLimits:
    return OPERATOR_LIMITS if workspace == OWNER_WORKSPACE else PERSONAL_LIMITS


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encode(value):
    value = json.dumps(value, separators=(",", ":"))
    if len(value.encode()) > MAX_MESSAGE:
        raise ValueError("Worker message exceeds the 8 MiB limit")
    return value


def permitted(method: str, path: str, query: str = "") -> bool:
    """A second copy of this allowlist runs on the worker before any dispatch."""
    if any(value in path for value in ("%", "\\", "..", "\x00")):
        return False
    parameters = parse_qs(query, keep_blank_values=True)
    if set(parameters) - {"refresh", "transport", "connection_id", "cursor"}:
        return False
    if any(len(values) != 1 or len(values[0]) > 128 for values in parameters.values()):
        return False
    if method == "GET":
        return bool(re.fullmatch(r"/api/(context|deployment|providers|connections|profiles|project-profiles|runs|feedback/export|models/[a-z][a-z0-9_-]{0,47}|runs/[a-f0-9-]{36}(?:/(?:receipt|patch|recovery|event-log))?)", path))
    if method == "POST":
        return bool(re.fullmatch(r"/api/(runs|project/assess|feedback/baseline|connections/[a-z][a-z0-9_-]{0,63}/test|runs/[a-f0-9-]{36}/(?:steer|pause|stop|cancel|resume|recover|feedback))", path))
    if method in {"PUT", "DELETE"}:
        return bool(re.fullmatch(r"/api/(?:profiles|project-profiles)/[^/]{1,100}", path))
    return False


SCOPE = "COALESCE((SELECT workspace FROM worker_scope WHERE worker=workers.id),'owner')"


class ExecutorHub:
    """Workspace data lives in side tables, so the original worker tables keep the
    previous release's shape and a rollback onto the same database still works.
    Machines and pairing codes without a scope row belong to the operator workspace."""

    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS worker_pairs(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                token_hash TEXT NOT NULL, seen REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_commands(id TEXT PRIMARY KEY, worker TEXT NOT NULL,
                request TEXT NOT NULL, response TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_cache(worker TEXT NOT NULL, path TEXT NOT NULL,
                response TEXT NOT NULL, PRIMARY KEY(worker,path));
            CREATE TABLE IF NOT EXISTS worker_events(worker TEXT NOT NULL, run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY(worker,run_id,sequence));
            CREATE TABLE IF NOT EXISTS worker_scope(worker TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                evidence_bytes INTEGER NOT NULL DEFAULT 0, pruned_through INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS worker_pair_scope(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS worker_scope_workspace ON worker_scope(workspace);
            CREATE INDEX IF NOT EXISTS worker_event_order ON worker_events(worker, sequence);
            CREATE INDEX IF NOT EXISTS worker_queue ON worker_commands(worker, response, created);
            """)
            db.execute(f"INSERT OR IGNORE INTO worker_scope(worker,workspace) SELECT id,'{OWNER_WORKSPACE}' FROM workers")
            # Recount retained evidence so budgets also hold for rows written before accounting existed.
            db.execute("""UPDATE worker_scope SET evidence_bytes=
                COALESCE((SELECT SUM(length(CAST(event AS BLOB))) FROM worker_events WHERE worker=worker_scope.worker),0)+
                COALESCE((SELECT SUM(length(CAST(response AS BLOB))) FROM worker_cache WHERE worker=worker_scope.worker),0)""")

    # Studio-facing operations: every call names the caller's workspace --------
    def pair(self, workspace):
        limits, now = limits_for(workspace), time.time()
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_pairs WHERE expires<?", (now,))
            db.execute("DELETE FROM worker_pair_scope WHERE hash NOT IN (SELECT hash FROM worker_pairs)")
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace can connect up to {limits.workers} machines. Disconnect one before pairing another.")
            pending = db.execute("SELECT COUNT(*) FROM worker_pairs p WHERE COALESCE((SELECT workspace FROM worker_pair_scope WHERE hash=p.hash),'owner')=?",
                                 (workspace,)).fetchone()[0]
            if pending >= limits.pending_pairs:
                raise HTTPException(429, "Several unused pairing codes are still active. Use one, or wait five minutes for them to expire.")
            if not allow_rate(db, "pair:" + workspace, limits.pairs_per_hour, 3600):
                raise HTTPException(429, "Too many pairing codes were generated this hour. Try again later.")
            code = secrets.token_urlsafe(24)
            db.execute("INSERT INTO worker_pairs(hash,expires) VALUES(?,?)", (digest(code), now + PAIR_SECONDS))
            db.execute("INSERT INTO worker_pair_scope(hash,workspace) VALUES(?,?)", (digest(code), workspace))
        return {"code": code, "expires_in": PAIR_SECONDS}

    def workers(self, workspace):
        with self.store.connect() as db:
            rows = db.execute(f"SELECT id,name,seen,metadata FROM workers WHERE revoked=0 AND {SCOPE}=? ORDER BY name,id", (workspace,)).fetchall()
        now = time.time()
        return [{"id": r["id"], "name": r["name"], "online": now - r["seen"] < ONLINE_SECONDS,
                 "last_seen": r["seen"], **json.loads(r["metadata"])} for r in rows]

    def worker(self, identifier, workspace):
        """Return the caller's machine. Other workspaces' machines are indistinguishable from missing ones."""
        row = next((r for r in self.workers(workspace) if r["id"] == identifier), None)
        if row is None:
            raise HTTPException(404, "Execution machine not found")
        return row

    def revoke(self, identifier, workspace):
        self.worker(identifier, workspace)
        with self.store.connect() as db:
            db.execute("UPDATE workers SET revoked=1 WHERE id=?", (identifier,))
            db.execute("UPDATE worker_scope SET evidence_bytes=0 WHERE worker=?", (identifier,))
            # A revoked machine's mirror is unreachable; remove it instead of retaining it indefinitely.
            for table in ("worker_commands", "worker_cache", "worker_events"):
                db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
        return {"ok": True}

    def purge_workspace(self, workspace):
        if workspace == OWNER_WORKSPACE:
            raise ValueError("The operator workspace cannot be purged")
        with self.store.connect() as db:
            identifiers = [row[0] for row in db.execute("SELECT worker FROM worker_scope WHERE workspace=?", (workspace,))]
            for identifier in identifiers:
                for table in ("worker_commands", "worker_cache", "worker_events"):
                    db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
                db.execute("DELETE FROM workers WHERE id=?", (identifier,))
            db.execute("DELETE FROM worker_scope WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM worker_pairs WHERE hash IN (SELECT hash FROM worker_pair_scope WHERE workspace=?)", (workspace,))
            db.execute("DELETE FROM worker_pair_scope WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM rate_events WHERE bucket IN (?,?)", ("pair:" + workspace, "relay:" + workspace))

    def events(self, worker, run_id, cursor, workspace):
        self.worker(worker, workspace)
        with self.store.connect() as db:
            rows = db.execute("SELECT event FROM worker_events WHERE worker=? AND run_id=? AND sequence>? ORDER BY sequence LIMIT 500", (worker, run_id, cursor)).fetchall()
        return [json.loads(row[0]) for row in rows]

    async def request(self, worker, method, path, query, body, *, workspace, timeout=60):
        if not permitted(method, path, query):
            raise HTTPException(403, "This operation is not available through a paired worker. Manage credentials locally.")
        descriptor = self.worker(worker, workspace)
        cache_path = path + ("?" + query if query else "")
        if not descriptor["online"]:
            cached = self.cached(worker, cache_path) if method == "GET" else None
            if cached:
                return {**cached, "offline": True}
            raise HTTPException(503, "Execution machine is offline. Wake it and start its Parallax worker; no work was dispatched.")
        limits = limits_for(workspace)
        identifier = str(uuid.uuid4())
        payload = encode({"method": method, "path": path, "query": query, "body": body, "expires_at": time.time() + timeout})
        if len(payload) > LOW_DISK_BODY and self._low_disk(workspace):
            raise HTTPException(507, "Hosted storage is low, so large requests are paused. Run controls such as stop and steer still work.")
        with self.store.connect() as db:
            if not allow_rate(db, "relay:" + workspace, limits.relayed_per_window, RELAY_WINDOW):
                raise HTTPException(429, "Too many requests reached this workspace's machines in the last five minutes. Retry shortly.")
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_commands WHERE worker=? AND created<?", (worker, time.time() - COMMAND_RETENTION))
            waiting, queued = db.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(request AS BLOB))),0) FROM worker_commands WHERE worker=? AND response IS NULL",
                                         (worker,)).fetchone()
            if waiting >= limits.pending_commands or queued + len(payload) > limits.pending_bytes:
                raise HTTPException(429, "This machine has too many unanswered requests. Wait for it to catch up, then retry.")
            db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,NULL,?)", (identifier, worker, payload, time.time()))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.store.connect() as db:
                row = db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()
                if row and row[0] is not None:
                    # Delivered: nothing about this command needs to stay on the hosted volume.
                    db.execute("DELETE FROM worker_commands WHERE id=?", (identifier,))
                    return json.loads(row[0])
            await asyncio.sleep(.1)
        raise HTTPException(504, f"Worker response timed out (request {identifier}). It may still finish. Inspect run history before retrying; the runtime will not redispatch this request.")

    def cached(self, worker, path):
        with self.store.connect() as db:
            row = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, path)).fetchone()
        return json.loads(row[0]) if row else None

    # Worker-facing operations: authorized by the worker's own scoped token -----
    def connect(self, code, name, metadata):
        # Pairing codes carry 192 random bits, so no shared guess limit is needed (one would let
        # anonymous traffic block every pairing).
        identifier, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self.store.connect() as db:
            row = db.execute("DELETE FROM worker_pairs WHERE hash=? AND expires>=? RETURNING hash", (digest(code), time.time())).fetchone()
            if not row:
                raise HTTPException(401, "Pairing code is invalid, expired, or already used")
            scope = db.execute("DELETE FROM worker_pair_scope WHERE hash=? RETURNING workspace", (row[0],)).fetchone()
            workspace = scope[0] if scope else OWNER_WORKSPACE
            limits = limits_for(workspace)
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace already has {limits.workers} machines. Disconnect one in Studio, then retry with the same code.")
            db.execute("INSERT INTO workers(id,name,token_hash,seen,revoked,metadata) VALUES(?,?,?,?,0,?)",
                       (identifier, name, digest(token), time.time(), encode(metadata)))
            db.execute("INSERT INTO worker_scope(worker,workspace) VALUES(?,?)", (identifier, workspace))
        return {"id": identifier, "token": token}

    def authenticate(self, token):
        with self.store.connect() as db:
            row = db.execute("SELECT id FROM workers WHERE token_hash=? AND revoked=0", (digest(token),)).fetchone()
        if not row:
            raise HTTPException(401, "Worker connection revoked or invalid")
        return row[0]

    def pending(self, worker):
        now = time.time()
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_commands WHERE worker=? AND created<?", (worker, now - COMMAND_RETENTION))
            # Answers nobody collected (the Studio request timed out) are kept only briefly.
            db.execute("DELETE FROM worker_commands WHERE worker=? AND response IS NOT NULL AND created<?", (worker, now - 300))
            db.execute("UPDATE workers SET seen=? WHERE id=?", (now, worker))
            rows = db.execute("SELECT id,request FROM worker_commands WHERE worker=? AND response IS NULL ORDER BY created LIMIT 8", (worker,)).fetchall()
        return [{"id": row["id"], **json.loads(row["request"])} for row in rows]

    def complete(self, worker, identifier, response):
        serialized = encode(response)
        with self.store.connect() as db:
            row = db.execute("SELECT request,response FROM worker_commands WHERE id=? AND worker=?", (identifier, worker)).fetchone()
            if not row:
                raise HTTPException(404, "Worker request not found")
            if row["response"] is not None:
                if row["response"] != serialized:
                    raise HTTPException(409, "Worker response cannot be replaced")
                return {"ok": True}
            db.execute("UPDATE worker_commands SET response=? WHERE id=?", (serialized, identifier))
            request = json.loads(row["request"])
            workspace = self._workspace(db, worker)
            if request["method"] == "GET" and 200 <= response["status"] < 300 and not self._low_disk(workspace):
                self._cache(db, worker, request["path"] + ("?" + request["query"] if request["query"] else ""), response)
                self._prune(db, worker)
        return {"ok": True}

    def sync(self, worker, runs, events):
        encode({"runs": runs, "events": events})
        with self.store.connect() as db:
            workspace = self._workspace(db, worker)
            limits = limits_for(workspace)
            if (runs or events) and self._low_disk(workspace):
                # Keep the machine reachable so stop and steer still work; evidence stays on the machine.
                db.execute("UPDATE workers SET seen=? WHERE id=?", (time.time(), worker))
                return {"ok": True, "stored": False}
            for result in runs:
                uuid.UUID(result["run_id"])
                self._cache(db, worker, "/api/runs/" + result["run_id"], {"status": 200, "body": result, "content_type": "application/json"})
            if runs:
                cached = db.execute("SELECT path,response FROM worker_cache WHERE worker=? AND path LIKE '/api/runs/%'", (worker,)).fetchall()
                bodies = [json.loads(r["response"]).get("body") for r in cached if RUN_PATH.fullmatch(r["path"])]
                history = [body for body in bodies if isinstance(body, dict) and "run_id" in body]
                history.sort(key=lambda r: r.get("artifacts", {}).get("started_at", 0), reverse=True)
                self._cache(db, worker, "/api/runs", {"status": 200, "body": history[:100], "content_type": "application/json"})
            pruned_through = db.execute("SELECT pruned_through FROM worker_scope WHERE worker=?", (worker,)).fetchone()[0]
            added = 0
            for event in events:
                uuid.UUID(event["run_id"])
                if event["sequence"] <= pruned_through:
                    continue  # Already aged out; a restarted worker replaying history must not displace newer evidence.
                serialized = encode(event)
                if len(serialized) > limits.event_bytes:
                    serialized = encode({**{key: event.get(key) for key in ("schema_version", "run_id", "sequence", "timestamp", "kind", "task_id")},
                                         "data": {"truncated": True, "bytes": len(serialized)}})
                cursor = db.execute("INSERT OR IGNORE INTO worker_events(worker,run_id,sequence,event) VALUES(?,?,?,?)",
                                    (worker, event["run_id"], event["sequence"], serialized))
                added += len(serialized) if cursor.rowcount else 0
            db.execute("UPDATE workers SET seen=? WHERE id=?", (time.time(), worker))
            db.execute("UPDATE worker_scope SET evidence_bytes=evidence_bytes+? WHERE worker=?", (added, worker))
            self._prune(db, worker)
        return {"ok": True}

    # Internal helpers ----------------------------------------------------------
    @staticmethod
    def _active(db, workspace):
        return db.execute(f"SELECT COUNT(*) FROM workers WHERE revoked=0 AND {SCOPE}=?", (workspace,)).fetchone()[0]

    @staticmethod
    def _workspace(db, worker):
        db.execute("INSERT OR IGNORE INTO worker_scope(worker,workspace) VALUES(?,?)", (worker, OWNER_WORKSPACE))
        return db.execute("SELECT workspace FROM worker_scope WHERE worker=?", (worker,)).fetchone()[0]

    def _low_disk(self, workspace):
        return workspace != OWNER_WORKSPACE and shutil.disk_usage(self.store.home).free < MIN_FREE_BYTES

    def _cache(self, db, worker, path, response):
        serialized = encode(response)
        previous = db.execute("DELETE FROM worker_cache WHERE worker=? AND path=? RETURNING length(CAST(response AS BLOB))", (worker, path)).fetchone()
        # Re-inserting gives the entry a new rowid, so rowid order is least recently written first.
        db.execute("INSERT INTO worker_cache(worker,path,response) VALUES(?,?,?)", (worker, path, serialized))
        db.execute("UPDATE worker_scope SET evidence_bytes=evidence_bytes+? WHERE worker=?", (len(serialized) - (previous[0] if previous else 0), worker))

    def _prune(self, db, worker):
        """Keep a machine's mirror within its workspace budget, oldest evidence first."""
        row = db.execute("SELECT workspace,evidence_bytes,pruned_through FROM worker_scope WHERE worker=?", (worker,)).fetchone()
        budget = limits_for(row["workspace"]).evidence_bytes
        total = row["evidence_bytes"]
        if total <= budget:
            return
        target = int(budget * 0.9)
        cutoff = None
        # One ordered pass over the (worker, sequence) index finds the newest sequence to drop.
        oldest = db.execute("SELECT sequence,length(CAST(event AS BLOB)) FROM worker_events WHERE worker=? ORDER BY sequence", (worker,))
        try:
            for sequence, size in oldest:
                total -= size
                cutoff = sequence
                if total <= target:
                    break
        finally:
            oldest.close()
        if cutoff is not None:
            db.execute("DELETE FROM worker_events WHERE worker=? AND sequence<=?", (worker, cutoff))
            db.execute("UPDATE worker_scope SET pruned_through=MAX(pruned_through,?) WHERE worker=?", (cutoff, worker))
        if total > target:
            for rowid, size in db.execute("SELECT rowid,length(CAST(response AS BLOB)) FROM worker_cache WHERE worker=? AND path!='/api/runs' ORDER BY rowid", (worker,)).fetchall():
                db.execute("DELETE FROM worker_cache WHERE rowid=?", (rowid,))
                total -= size
                if total <= target:
                    break
        db.execute("UPDATE worker_scope SET evidence_bytes=? WHERE worker=?", (max(total, 0), worker))
