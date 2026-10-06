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
    evidence_bytes: int  # mirrored events and cached responses retained per machine
    event_bytes: int  # larger events are mirrored as a truncation marker
    relay_requests: int  # concurrent Studio requests waiting on machines
    event_streams: int  # concurrent replay streams


OPERATOR_LIMITS = WorkspaceLimits(workers=50, pending_pairs=10, pairs_per_hour=120, pending_commands=128,
                                  evidence_bytes=2 * 1024 ** 3, event_bytes=MAX_MESSAGE, relay_requests=64, event_streams=64)
PERSONAL_LIMITS = WorkspaceLimits(workers=3, pending_pairs=3, pairs_per_hour=20, pending_commands=32,
                                  evidence_bytes=96 * 1024 ** 2, event_bytes=256 * 1024, relay_requests=16, event_streams=8)


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


def _ensure_column(db, table, column, definition):
    if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


class ExecutorHub:
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
            """)
            # Additive migration: rows that predate workspaces belong to the operator workspace.
            _ensure_column(db, "worker_pairs", "workspace", f"workspace TEXT NOT NULL DEFAULT '{OWNER_WORKSPACE}'")
            _ensure_column(db, "workers", "workspace", f"workspace TEXT NOT NULL DEFAULT '{OWNER_WORKSPACE}'")
            _ensure_column(db, "workers", "evidence_bytes", "evidence_bytes INTEGER NOT NULL DEFAULT 0")
            _ensure_column(db, "worker_cache", "updated", "updated REAL NOT NULL DEFAULT 0")
            db.execute("CREATE INDEX IF NOT EXISTS worker_scope ON workers(workspace, revoked)")
            db.execute("CREATE INDEX IF NOT EXISTS worker_queue ON worker_commands(worker, response, created)")
            db.execute("CREATE INDEX IF NOT EXISTS worker_pair_scope ON worker_pairs(workspace, expires)")
            # Recount retained evidence so budgets also hold for rows written before accounting existed.
            db.execute("""UPDATE workers SET evidence_bytes=
                COALESCE((SELECT SUM(length(CAST(event AS BLOB))) FROM worker_events WHERE worker=workers.id),0)+
                COALESCE((SELECT SUM(length(CAST(response AS BLOB))) FROM worker_cache WHERE worker=workers.id),0)""")

    # Studio-facing operations: every call names the caller's workspace --------
    def pair(self, workspace):
        limits, now = limits_for(workspace), time.time()
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_pairs WHERE expires<?", (now,))
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace can connect up to {limits.workers} machines. Disconnect one before pairing another.")
            if db.execute("SELECT COUNT(*) FROM worker_pairs WHERE workspace=?", (workspace,)).fetchone()[0] >= limits.pending_pairs:
                raise HTTPException(429, "Several unused pairing codes are still active. Use one, or wait five minutes for them to expire.")
            if not allow_rate(db, "pair:" + workspace, limits.pairs_per_hour, 3600):
                raise HTTPException(429, "Too many pairing codes were generated this hour. Try again later.")
            code = secrets.token_urlsafe(24)
            db.execute("INSERT INTO worker_pairs(hash,expires,workspace) VALUES(?,?,?)", (digest(code), now + PAIR_SECONDS, workspace))
        return {"code": code, "expires_in": PAIR_SECONDS}

    def workers(self, workspace):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,name,seen,metadata FROM workers WHERE workspace=? AND revoked=0 ORDER BY name,id", (workspace,)).fetchall()
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
            db.execute("UPDATE workers SET revoked=1,evidence_bytes=0 WHERE id=? AND workspace=?", (identifier, workspace))
            # A revoked machine's mirror is unreachable; remove it instead of retaining it indefinitely.
            for table in ("worker_commands", "worker_cache", "worker_events"):
                db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
        return {"ok": True}

    def purge_workspace(self, workspace):
        if workspace == OWNER_WORKSPACE:
            raise ValueError("The operator workspace cannot be purged")
        with self.store.connect() as db:
            identifiers = [row[0] for row in db.execute("SELECT id FROM workers WHERE workspace=?", (workspace,))]
            for identifier in identifiers:
                for table in ("worker_commands", "worker_cache", "worker_events"):
                    db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
            db.execute("DELETE FROM workers WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM worker_pairs WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM rate_events WHERE bucket=?", ("pair:" + workspace,))

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
        identifier = str(uuid.uuid4())
        payload = encode({"method": method, "path": path, "query": query, "body": body, "expires_at": time.time() + timeout})
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_commands WHERE worker=? AND created<?", (worker, time.time() - COMMAND_RETENTION))
            waiting = db.execute("SELECT COUNT(*) FROM worker_commands WHERE worker=? AND response IS NULL", (worker,)).fetchone()[0]
            if waiting >= limits_for(workspace).pending_commands:
                raise HTTPException(429, "This machine has too many unanswered requests. Wait for it to catch up, then retry.")
            db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,NULL,?)", (identifier, worker, payload, time.time()))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.store.connect() as db:
                row = db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()
            if row and row[0] is not None:
                return json.loads(row[0])
            await asyncio.sleep(.1)
        raise HTTPException(504, f"Worker response timed out (request {identifier}). It may still finish. Inspect run history before retrying; the runtime will not redispatch this request.")

    def cached(self, worker, path):
        with self.store.connect() as db:
            row = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, path)).fetchone()
        return json.loads(row[0]) if row else None

    # Worker-facing operations: authorized by the worker's own scoped token -----
    def connect(self, code, name, metadata):
        with self.store.connect() as db:
            # Counted in its own transaction so failed guesses are not rolled back.
            if not allow_rate(db, "worker-connect", 120, 60):
                raise HTTPException(429, "Too many pairing attempts. Wait a minute and retry.")
        identifier, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self.store.connect() as db:
            row = db.execute("DELETE FROM worker_pairs WHERE hash=? AND expires>=? RETURNING workspace", (digest(code), time.time())).fetchone()
            if not row:
                raise HTTPException(401, "Pairing code is invalid, expired, or already used")
            workspace = row[0]
            limits = limits_for(workspace)
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace already has {limits.workers} machines. Disconnect one in Studio, then retry with the same code.")
            db.execute("INSERT INTO workers(id,name,token_hash,seen,revoked,metadata,workspace,evidence_bytes) VALUES(?,?,?,?,0,?,?,0)",
                       (identifier, name, digest(token), time.time(), encode(metadata), workspace))
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
            db.execute("DELETE FROM worker_commands WHERE worker=? AND response IS NOT NULL AND created<? AND request LIKE ?", (worker, now - 300, '{"method":"GET",%'))
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
            if request["method"] == "GET" and 200 <= response["status"] < 300:
                self._cache(db, worker, request["path"] + ("?" + request["query"] if request["query"] else ""), response)
                self._prune(db, worker)
        return {"ok": True}

    def sync(self, worker, runs, events):
        encode({"runs": runs, "events": events})
        with self.store.connect() as db:
            workspace = db.execute("SELECT workspace FROM workers WHERE id=?", (worker,)).fetchone()[0]
            limits = limits_for(workspace)
            if (runs or events) and workspace != OWNER_WORKSPACE and shutil.disk_usage(self.store.home).free < MIN_FREE_BYTES:
                # Refuse before marking the machine seen: Studio shows it offline instead of losing evidence silently.
                raise HTTPException(507, "Hosted evidence storage is temporarily full. Local runs continue and will mirror once space is available.")
            for result in runs:
                uuid.UUID(result["run_id"])
                self._cache(db, worker, "/api/runs/" + result["run_id"], {"status": 200, "body": result, "content_type": "application/json"})
            if runs:
                cached = db.execute("SELECT path,response FROM worker_cache WHERE worker=? AND path LIKE '/api/runs/%'", (worker,)).fetchall()
                bodies = [json.loads(r["response"]).get("body") for r in cached if RUN_PATH.fullmatch(r["path"])]
                history = [body for body in bodies if isinstance(body, dict) and "run_id" in body]
                history.sort(key=lambda r: r.get("artifacts", {}).get("started_at", 0), reverse=True)
                self._cache(db, worker, "/api/runs", {"status": 200, "body": history[:100], "content_type": "application/json"})
            added = 0
            for event in events:
                uuid.UUID(event["run_id"])
                serialized = encode(event)
                if len(serialized) > limits.event_bytes:
                    serialized = encode({**{key: event.get(key) for key in ("schema_version", "run_id", "sequence", "timestamp", "kind", "task_id")},
                                         "data": {"truncated": True, "bytes": len(serialized)}})
                cursor = db.execute("INSERT OR IGNORE INTO worker_events(worker,run_id,sequence,event) VALUES(?,?,?,?)",
                                    (worker, event["run_id"], event["sequence"], serialized))
                added += len(serialized) if cursor.rowcount else 0
            db.execute("UPDATE workers SET seen=?,evidence_bytes=evidence_bytes+? WHERE id=?", (time.time(), added, worker))
            self._prune(db, worker)
        return {"ok": True}

    # Internal helpers ----------------------------------------------------------
    @staticmethod
    def _active(db, workspace):
        return db.execute("SELECT COUNT(*) FROM workers WHERE workspace=? AND revoked=0", (workspace,)).fetchone()[0]

    def _cache(self, db, worker, path, response):
        serialized = encode(response)
        previous = db.execute("SELECT length(CAST(response AS BLOB)) FROM worker_cache WHERE worker=? AND path=?", (worker, path)).fetchone()
        db.execute("INSERT INTO worker_cache(worker,path,response,updated) VALUES(?,?,?,?) ON CONFLICT(worker,path) DO UPDATE SET response=excluded.response,updated=excluded.updated",
                   (worker, path, serialized, time.time()))
        db.execute("UPDATE workers SET evidence_bytes=evidence_bytes+? WHERE id=?", (len(serialized) - (previous[0] if previous else 0), worker))

    def _prune(self, db, worker):
        """Keep a machine's mirror within its workspace budget, oldest evidence first."""
        row = db.execute("SELECT workspace,evidence_bytes FROM workers WHERE id=?", (worker,)).fetchone()
        budget = limits_for(row["workspace"]).evidence_bytes
        total = row["evidence_bytes"]
        if total <= budget:
            return
        target = int(budget * 0.9)
        while total > target:
            rows = db.execute("SELECT rowid,length(CAST(event AS BLOB)) FROM worker_events WHERE worker=? ORDER BY rowid LIMIT 500", (worker,)).fetchall()
            if not rows:
                break
            chosen = []
            for rowid, size in rows:
                chosen.append(rowid)
                total -= size
                if total <= target:
                    break
            db.execute(f"DELETE FROM worker_events WHERE rowid IN ({','.join('?' * len(chosen))})", chosen)
        if total > target:
            for path, size in db.execute("SELECT path,length(CAST(response AS BLOB)) FROM worker_cache WHERE worker=? AND path!='/api/runs' ORDER BY updated", (worker,)).fetchall():
                db.execute("DELETE FROM worker_cache WHERE worker=? AND path=?", (worker, path))
                total -= size
                if total <= target:
                    break
        db.execute("UPDATE workers SET evidence_bytes=? WHERE id=?", (max(total, 0), worker))
