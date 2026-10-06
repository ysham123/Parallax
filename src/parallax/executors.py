"""Outbound, credential-scoped worker relay for the private hosted workspace.

The relay carries typed Studio operations, never shell commands, file mounts,
provider credentials, or arbitrary URLs. Execution and integration stay local.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from urllib.parse import parse_qs
from fastapi import HTTPException

MAX_MESSAGE = 8 * 1024 * 1024
ONLINE_SECONDS = 30


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

    def pair(self):
        code = secrets.token_urlsafe(24)
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_pairs WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO worker_pairs VALUES(?,?)", (digest(code), time.time() + 300))
        return {"code": code, "expires_in": 300}

    def connect(self, code, name, metadata):
        identifier, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self.store.connect() as db:
            row = db.execute("DELETE FROM worker_pairs WHERE hash=? AND expires>=? RETURNING hash", (digest(code), time.time())).fetchone()
            if not row:
                raise HTTPException(401, "Pairing code is invalid, expired, or already used")
            db.execute("INSERT INTO workers VALUES(?,?,?,?,0,?)", (identifier, name, digest(token), time.time(), encode(metadata)))
        return {"id": identifier, "token": token}

    def authenticate(self, token):
        with self.store.connect() as db:
            row = db.execute("SELECT id FROM workers WHERE token_hash=? AND revoked=0", (digest(token),)).fetchone()
        if not row:
            raise HTTPException(401, "Worker connection revoked or invalid")
        return row[0]

    def workers(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM workers WHERE revoked=0 ORDER BY name,id").fetchall()
        return [{"id": r["id"], "name": r["name"], "online": time.time() - r["seen"] < ONLINE_SECONDS,
                 "last_seen": r["seen"], **json.loads(r["metadata"])} for r in rows]

    def worker(self, identifier):
        row = next((r for r in self.workers() if r["id"] == identifier), None)
        if row is None:
            raise HTTPException(404, "Execution machine not found")
        return row

    def revoke(self, identifier):
        self.worker(identifier)
        with self.store.connect() as db:
            db.execute("UPDATE workers SET revoked=1 WHERE id=?", (identifier,))
        return {"ok": True}

    def pending(self, worker):
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_commands WHERE response IS NOT NULL AND created<? AND request LIKE ?", (time.time()-300, '{"method":"GET",%'))
            db.execute("UPDATE workers SET seen=? WHERE id=?", (time.time(), worker))
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
        return {"ok": True}

    @staticmethod
    def _cache(db, worker, path, response):
        db.execute("INSERT INTO worker_cache VALUES(?,?,?) ON CONFLICT(worker,path) DO UPDATE SET response=excluded.response", (worker, path, encode(response)))

    def sync(self, worker, runs, events):
        encode({"runs": runs, "events": events})
        with self.store.connect() as db:
            for result in runs:
                uuid.UUID(result["run_id"])
                self._cache(db, worker, "/api/runs/" + result["run_id"], {"status": 200, "body": result, "content_type": "application/json"})
            if runs:
                cached = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path LIKE '/api/runs/%'", (worker,)).fetchall()
                history = [json.loads(r[0])["body"] for r in cached if isinstance(json.loads(r[0]).get("body"), dict) and "run_id" in json.loads(r[0])["body"]]
                history.sort(key=lambda r: r.get("artifacts", {}).get("started_at", 0), reverse=True)
                self._cache(db, worker, "/api/runs", {"status": 200, "body": history[:100], "content_type": "application/json"})
            for event in events:
                uuid.UUID(event["run_id"])
                db.execute("INSERT OR IGNORE INTO worker_events VALUES(?,?,?,?)", (worker, event["run_id"], event["sequence"], encode(event)))
            db.execute("UPDATE workers SET seen=? WHERE id=?", (time.time(), worker))
        return {"ok": True}

    def events(self, worker, run_id, cursor):
        with self.store.connect() as db:
            rows = db.execute("SELECT event FROM worker_events WHERE worker=? AND run_id=? AND sequence>? ORDER BY sequence LIMIT 500", (worker, run_id, cursor)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def cached(self, worker, path):
        with self.store.connect() as db:
            row = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, path)).fetchone()
        return json.loads(row[0]) if row else None

    async def request(self, worker, method, path, query, body, *, timeout=60):
        if not permitted(method, path, query):
            raise HTTPException(403, "This operation is not available through a paired worker. Manage credentials locally.")
        descriptor = self.worker(worker)
        cache_path = path + ("?" + query if query else "")
        if not descriptor["online"]:
            cached = self.cached(worker, cache_path) if method == "GET" else None
            if cached:
                return {**cached, "offline": True}
            raise HTTPException(503, "Execution machine is offline. Wake it and start its Parallax worker; no work was dispatched.")
        identifier = str(uuid.uuid4())
        payload = encode({"method": method, "path": path, "query": query, "body": body, "expires_at": time.time() + timeout})
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (identifier, worker, payload, time.time()))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.store.connect() as db:
                row = db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()
            if row and row[0] is not None:
                return json.loads(row[0])
            await asyncio.sleep(.1)
        raise HTTPException(504, f"Worker response timed out (request {identifier}). It may still finish. Inspect run history before retrying; the runtime will not redispatch this request.")
