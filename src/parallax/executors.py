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
from datetime import datetime
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
CONTROL_SLOTS = 4
CONTROL_BYTES = 64 * 1024


def is_control(method, path):
    return method == "POST" and bool(re.fullmatch(r"/api/(?:runs|workflows)/[a-f0-9-]{36}/(?:cancel|stop)", path))


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
        if re.fullmatch(r"/api/(?:workflow-templates|workflows(?:/[a-f0-9-]{36})?)", path):
            return not parameters
        return bool(re.fullmatch(r"/api/(pilot/report|context|deployment|providers|connections|profiles|project-profiles|runs|feedback/export|models/[a-z][a-z0-9_-]{0,47}|runs/[a-f0-9-]{36}(?:/(?:receipt|patch|recovery|event-log))?)", path))
    if method == "POST":
        if path in {"/api/pilot/benchmark", "/api/pilot/observations"}:
            return not parameters
        if re.fullmatch(r"/api/(?:workflow-templates|workflows(?:/[a-f0-9-]{36}/(?:decision|resume|cancel|revise|approve|apply|reviewer|comment|publish|publication-preview|begin-publication|record-publication|github-refresh))?)", path):
            return not parameters
        return bool(re.fullmatch(r"/api/(pilot/benchmark|runs|project/assess|feedback/baseline|connections/[a-z][a-z0-9_-]{0,63}/test|runs/[a-f0-9-]{36}/(?:steer|pause|stop|cancel|resume|recover|feedback))", path))
    if method in {"PUT", "DELETE"}:
        if method == "PUT" and re.fullmatch(r"/api/workflow-templates/[a-f0-9-]{36}", path):
            return not parameters
        return bool(re.fullmatch(r"/api/(?:profiles|project-profiles)/[^/]{1,100}", path))
    return False


# Machines are read through their scope row. A personal machine's real token and revocation live only in
# worker_scope; its workers row says revoked with an unusable token, so the previous release (which reads
# only workers) can neither list it nor accept its token after a rollback.
MACHINES = "workers w LEFT JOIN worker_scope s ON s.worker=w.id"
ACTIVE = "(CASE WHEN s.token_hash IS NULL THEN w.revoked=0 ELSE s.revoked=0 END)"
SCOPE = "COALESCE(s.workspace,'owner')"


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


class ExecutorHub:
    """Workspace data lives in side tables, so the original worker tables keep the
    previous release's shape and a rollback onto the same database still works,
    without exposing personal machines or pairing codes to the operator.
    Machines and pairing codes without a scope row belong to the operator workspace."""

    def __init__(self, store, *, accounts=None):
        self.store = store
        self.accounts = accounts
        with store.connect() as db:
            # A pre-release build named indexes after the side tables; free those names for the tables.
            for name in ("worker_scope", "worker_pair_scope"):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone():
                    db.execute(f"DROP INDEX {name}")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS worker_pairs(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                token_hash TEXT NOT NULL, seen REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_commands(id TEXT PRIMARY KEY, worker TEXT NOT NULL,
                request TEXT NOT NULL, response TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_command_dispatch(id TEXT PRIMARY KEY, dispatched REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_command_priority(id TEXT PRIMARY KEY, priority INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_operation_receipts(id TEXT PRIMARY KEY, worker TEXT NOT NULL,
                workspace TEXT NOT NULL, project TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_archives(worker TEXT NOT NULL, workspace TEXT NOT NULL,
                project TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL, body TEXT NOT NULL,
                archived REAL NOT NULL, PRIMARY KEY(worker,kind,record_id));
            CREATE INDEX IF NOT EXISTS worker_archive_workspace ON worker_archives(workspace,archived);
            CREATE TABLE IF NOT EXISTS worker_cache(worker TEXT NOT NULL, path TEXT NOT NULL,
                response TEXT NOT NULL, PRIMARY KEY(worker,path));
            CREATE TABLE IF NOT EXISTS worker_events(worker TEXT NOT NULL, run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY(worker,run_id,sequence));
            CREATE TABLE IF NOT EXISTS worker_workflow_features(worker TEXT NOT NULL, workflow TEXT NOT NULL,
                features TEXT NOT NULL, PRIMARY KEY(worker,workflow));
            CREATE TABLE IF NOT EXISTS worker_workflow_feature_requests(worker TEXT NOT NULL, command TEXT NOT NULL,
                workflow TEXT NOT NULL, features TEXT NOT NULL, PRIMARY KEY(worker,command));
            CREATE TABLE IF NOT EXISTS worker_scope(worker TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                evidence_bytes INTEGER NOT NULL DEFAULT 0, pruned_through INTEGER NOT NULL DEFAULT 0,
                token_hash TEXT, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS worker_pair_scope(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                expires REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS worker_pair_authority(hash TEXT PRIMARY KEY, actor TEXT NOT NULL,
                session TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS worker_event_order ON worker_events(worker, sequence);
            CREATE INDEX IF NOT EXISTS worker_queue ON worker_commands(worker, response, created);
            CREATE INDEX IF NOT EXISTS worker_command_age ON worker_commands(created);
            CREATE INDEX IF NOT EXISTS worker_workflow_request_lookup ON worker_workflow_feature_requests(worker,workflow);
            """)
            # Side tables from an earlier build of this release lack the columns that hide personal state.
            for table, column, definition in (("worker_scope", "token_hash", "token_hash TEXT"),
                                              ("worker_scope", "revoked", "revoked INTEGER NOT NULL DEFAULT 0"),
                                              ("worker_pair_scope", "expires", "expires REAL NOT NULL DEFAULT 0")):
                if column not in _columns(db, table):
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            db.execute("CREATE INDEX IF NOT EXISTS worker_scope_workspace ON worker_scope(workspace)")
            db.execute("CREATE INDEX IF NOT EXISTS worker_scope_token ON worker_scope(token_hash)")
            # A pre-release build kept the workspace on the original rows; carry it over before defaulting.
            if "workspace" in _columns(db, "workers"):
                db.execute("INSERT OR IGNORE INTO worker_scope(worker,workspace) SELECT id,workspace FROM workers")
            if "workspace" in _columns(db, "worker_pairs"):
                db.execute("INSERT OR IGNORE INTO worker_pair_scope(hash,workspace,expires) SELECT hash,workspace,expires FROM worker_pairs WHERE workspace!=?",
                           (OWNER_WORKSPACE,))
            db.execute("INSERT OR IGNORE INTO worker_scope(worker,workspace) SELECT id,? FROM workers", (OWNER_WORKSPACE,))
            db.execute("""UPDATE worker_scope SET token_hash=(SELECT token_hash FROM workers WHERE id=worker_scope.worker),
                revoked=(SELECT revoked FROM workers WHERE id=worker_scope.worker) WHERE workspace!=? AND token_hash IS NULL""", (OWNER_WORKSPACE,))
            db.execute("UPDATE workers SET revoked=1,token_hash='scoped:'||id WHERE id IN (SELECT worker FROM worker_scope WHERE workspace!=?)",
                       (OWNER_WORKSPACE,))
            # Personal pairing codes live only in the side table; operator codes only in worker_pairs.
            db.execute("UPDATE worker_pair_scope SET expires=COALESCE((SELECT expires FROM worker_pairs WHERE hash=worker_pair_scope.hash),0) WHERE expires=0")
            db.execute("DELETE FROM worker_pairs WHERE hash IN (SELECT hash FROM worker_pair_scope WHERE workspace!=?)", (OWNER_WORKSPACE,))
            db.execute("DELETE FROM worker_pair_scope WHERE workspace=?", (OWNER_WORKSPACE,))
            # Recount retained evidence so budgets also hold for rows written before accounting existed.
            db.execute("""UPDATE worker_scope SET evidence_bytes=
                COALESCE((SELECT SUM(length(CAST(event AS BLOB))) FROM worker_events WHERE worker=worker_scope.worker),0)+
                COALESCE((SELECT SUM(length(CAST(response AS BLOB))) FROM worker_cache WHERE worker=worker_scope.worker),0)""")

    # Studio-facing operations: every call names the caller's workspace --------
    @staticmethod
    def _team_workspace(db, workspace):
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspaces'").fetchone()
                    and db.execute("SELECT 1 FROM workspaces WHERE id=? AND kind='team'", (workspace,)).fetchone())

    @staticmethod
    def _pair_authorized(db, workspace, issuer, now):
        if not issuer or not issuer.get("actor") or not issuer.get("session"):
            return False
        return bool(db.execute("""SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account
            JOIN sessions s ON s.account=m.account AND s.workspace=m.workspace
            WHERE m.workspace=? AND m.account=? AND m.role='owner' AND a.disabled=0
            AND s.hash=? AND s.kind='team' AND s.expires>=?""",
            (workspace, issuer["actor"], issuer["session"], now)).fetchone())

    def pair(self, workspace, *, authority=None):
        limits, now = limits_for(workspace), time.time()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM worker_pairs WHERE expires<?", (now,))
            db.execute("DELETE FROM worker_pair_scope WHERE expires<?", (now,))
            db.execute("DELETE FROM worker_pair_authority WHERE hash NOT IN (SELECT hash FROM worker_pair_scope)")
            team = self._team_workspace(db, workspace)
            if team and not self._pair_authorized(db, workspace, authority, now):
                raise HTTPException(403, "Current owner authorization is required to pair a team worker")
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace can connect up to {limits.workers} machines. Disconnect one before pairing another.")
            if workspace == OWNER_WORKSPACE:
                pending = db.execute("SELECT COUNT(*) FROM worker_pairs").fetchone()[0]
            else:
                pending = db.execute("SELECT COUNT(*) FROM worker_pair_scope WHERE workspace=?", (workspace,)).fetchone()[0]
            if pending >= limits.pending_pairs:
                raise HTTPException(429, "Several unused pairing codes are still active. Use one, or wait five minutes for them to expire.")
            if not allow_rate(db, "pair:" + workspace, limits.pairs_per_hour, 3600):
                raise HTTPException(429, "Too many pairing codes were generated this hour. Try again later.")
            code = secrets.token_urlsafe(24)
            if workspace == OWNER_WORKSPACE:
                db.execute("INSERT INTO worker_pairs(hash,expires) VALUES(?,?)", (digest(code), now + PAIR_SECONDS))
            else:
                db.execute("INSERT INTO worker_pair_scope(hash,workspace,expires) VALUES(?,?,?)", (digest(code), workspace, now + PAIR_SECONDS))
                if team:
                    db.execute("INSERT INTO worker_pair_authority VALUES(?,?,?)", (digest(code), authority["actor"], authority["session"]))
        return {"code": code, "expires_in": PAIR_SECONDS}

    def workers(self, workspace):
        with self.store.connect() as db:
            rows = db.execute(f"SELECT w.id,w.name,w.seen,w.metadata FROM {MACHINES} WHERE {ACTIVE} AND {SCOPE}=? ORDER BY w.name,w.id",
                              (workspace,)).fetchall()
        now = time.time()
        return [{"id": r["id"], "name": r["name"], "online": now - r["seen"] < ONLINE_SECONDS,
                 "last_seen": r["seen"], **json.loads(r["metadata"])} for r in rows]

    def worker(self, identifier, workspace):
        """Return the caller's machine. Other workspaces' machines are indistinguishable from missing ones."""
        row = next((r for r in self.workers(workspace) if r["id"] == identifier), None)
        if row is None:
            raise HTTPException(404, "Execution machine not found")
        return row

    def revoke(self, identifier, workspace, *, authority=None):
        self.worker(identifier, workspace)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._team_workspace(db, workspace):
                if authority is not None and not self._pair_authorized(db, workspace, authority, time.time()):
                    raise HTTPException(403, "Current workspace owner authorization is required to revoke a team worker")
                self._archive_worker(db, identifier, workspace)
            else:
                db.execute("DELETE FROM worker_operation_receipts WHERE worker=?", (identifier,))
                db.execute("DELETE FROM worker_archives WHERE worker=?", (identifier,))
            db.execute("UPDATE workers SET revoked=1 WHERE id=?", (identifier,))
            db.execute("UPDATE worker_scope SET revoked=1,evidence_bytes=0 WHERE worker=?", (identifier,))
            # A revoked machine's mirror is unreachable; remove it instead of retaining it indefinitely.
            db.execute("DELETE FROM worker_command_dispatch WHERE id IN (SELECT id FROM worker_commands WHERE worker=?)", (identifier,))
            db.execute("DELETE FROM worker_command_priority WHERE id IN (SELECT id FROM worker_commands WHERE worker=?)", (identifier,))
            for table in ("worker_commands", "worker_cache", "worker_events", "worker_workflow_features", "worker_workflow_feature_requests"):
                db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
        return {"ok": True}

    def purge_workspace(self, workspace):
        if workspace == OWNER_WORKSPACE:
            raise ValueError("The operator workspace cannot be purged")
        with self.store.connect() as db:
            identifiers = [row[0] for row in db.execute("SELECT worker FROM worker_scope WHERE workspace=?", (workspace,))]
            for identifier in identifiers:
                db.execute("DELETE FROM worker_command_dispatch WHERE id IN (SELECT id FROM worker_commands WHERE worker=?)", (identifier,))
                db.execute("DELETE FROM worker_command_priority WHERE id IN (SELECT id FROM worker_commands WHERE worker=?)", (identifier,))
                for table in ("worker_commands", "worker_cache", "worker_events", "worker_workflow_features", "worker_workflow_feature_requests"):
                    db.execute(f"DELETE FROM {table} WHERE worker=?", (identifier,))
                db.execute("DELETE FROM workers WHERE id=?", (identifier,))
                db.execute("DELETE FROM worker_operation_receipts WHERE worker=?", (identifier,))
                db.execute("DELETE FROM worker_archives WHERE worker=?", (identifier,))
            db.execute("DELETE FROM worker_scope WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM worker_pair_authority WHERE hash IN (SELECT hash FROM worker_pair_scope WHERE workspace=?)", (workspace,))
            db.execute("DELETE FROM worker_pair_scope WHERE workspace=?", (workspace,))
            db.execute("DELETE FROM rate_events WHERE bucket IN (?,?)", ("pair:" + workspace, "relay:" + workspace))
            db.execute("DELETE FROM rate_events WHERE bucket=?", ("relay-control:" + workspace,))

    def _command_project(self, db, worker, command):
        body = command.get("body") or {}
        project = body.get("workspace") if isinstance(body, dict) else None
        match = re.fullmatch(r"/api/(workflows|runs)/([a-f0-9-]{36})(?:/[^/]+)?", command["path"])
        if match:
            cached = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, "/api/"+match[1]+"/"+match[2])).fetchone()
            if cached:
                saved = json.loads(cached[0]).get("body") or {}
                project = saved.get("workspace") if match[1] == "workflows" else saved.get("spec", {}).get("workspace")
        metadata = json.loads(db.execute("SELECT metadata FROM workers WHERE id=?", (worker,)).fetchone()[0])
        if project not in metadata.get("workspaces", []):
            return None
        ctx = command.get("authority") or {}
        return project if not ctx.get("team") or project in ctx.get("projects", []) else None

    def _record_receipt(self, db, worker, workspace, command, dispatched):
        if command["method"] == "GET":
            return
        request = command.get("body") or {}
        requester = command.get("requester") or command.get("authority") or {}
        record = {"id": command["id"], "kind": "operation", "actor": requester.get("actor", "operator"),
                  "method": command["method"], "path": command["path"], "state": "dispatched",
                  "operation_id": request.get("request_id") if isinstance(request, dict) else None,
                  "request_sha256": digest(encode({k: command.get(k) for k in ("method", "path", "query", "body", "authority")})),
                  "dispatched_at": dispatched, "status": None, "response_sha256": None}
        db.execute("INSERT OR IGNORE INTO worker_operation_receipts VALUES(?,?,?,?,?)",
                   (command["id"], worker, workspace, self._command_project(db, worker, command), json.dumps(record)))

    def _archive_worker(self, db, worker, workspace):
        stamp = time.time()
        name = db.execute("SELECT name FROM workers WHERE id=?", (worker,)).fetchone()[0]
        approved = json.loads(db.execute("SELECT metadata FROM workers WHERE id=?", (worker,)).fetchone()[0]).get("workspaces", [])
        # Upgrade boundary: older runtimes may already have dispatched commands
        # before the receipt table existed. Preserve their identity on revoke.
        for row in db.execute("SELECT c.id,c.request,c.response,d.dispatched FROM worker_commands c JOIN worker_command_dispatch d ON d.id=c.id WHERE c.worker=?", (worker,)).fetchall():
            command = {"id": row[0], **json.loads(row[1])}
            self._record_receipt(db, worker, workspace, command, row[3])
            if row[2]:
                receipt = db.execute("SELECT body FROM worker_operation_receipts WHERE id=?", (row[0],)).fetchone()
                if receipt:
                    record = json.loads(receipt[0])
                    response = json.loads(row[2])
                    record.update(state="completed", status=response["status"], response_sha256=digest(row[2]))
                    db.execute("UPDATE worker_operation_receipts SET body=? WHERE id=?", (json.dumps(record), row[0]))
        def keep(kind, identifier, project, record):
            if project not in approved:
                return
            payload = {**record, "worker": worker, "worker_name": name, "workspace": workspace,
                       "project": project, "archived_at": stamp, "read_only": True}
            db.execute("INSERT OR IGNORE INTO worker_archives VALUES(?,?,?,?,?,?,?)",
                       (worker, workspace, project, kind, identifier, json.dumps(payload), stamp))
        workflow_records = {}
        def state_rank(value, detailed):
            try:
                stamp = datetime.fromisoformat(value.get("updated_at") or "").timestamp()
            except (ValueError, TypeError, OverflowError):
                stamp = float("-inf")
            return stamp, detailed
        # Build one task record before inserting its immutable archive row.
        # Latest saved state wins; detail supplies omitted candidate metadata.
        for row in db.execute("SELECT path,response FROM worker_cache WHERE worker=? ORDER BY length(path) DESC,path", (worker,)).fetchall():
            saved = json.loads(row[1]).get("body")
            values = saved if row[0] == "/api/workflows" and isinstance(saved, list) else [saved]
            for value in values:
                if not isinstance(value, dict):
                    continue
                if row[0] == "/api/workflows" or re.fullmatch(r"/api/workflows/[a-f0-9-]{36}", row[0]):
                    identifier, project = value.get("id"), value.get("workspace")
                    if not identifier:
                        continue
                    record = {key: value.get(key) for key in ("id", "title", "status", "run_id", "requester", "reviewer", "created_at", "updated_at")}
                    record["kind"] = "task"
                    decision = value.get("approval") or value.get("decision") or {}
                    record["approval"] = {key: decision.get(key) for key in ("id", "actor", "at", "action", "candidate_digest")}
                    record["candidate_digest"] = (value.get("candidate") or {}).get("digest") or decision.get("candidate_digest")
                    record["delivery"] = {key: (value.get("delivery") or {}).get(key) for key in ("local", "github")}
                    workflow_records.setdefault(identifier, []).append((state_rank(value, row[0] != "/api/workflows"), project, record))
                elif RUN_PATH.fullmatch(row[0]):
                    identifier = value.get("run_id")
                    if not identifier:
                        continue
                    checks, reviews = value.get("checks", []), value.get("reviews", [])
                    record = {"id": identifier, "kind": "run", "status": value.get("status"),
                              "requester": value.get("artifacts", {}).get("authority", {}).get("actor"),
                              "diff_sha256": digest(value.get("diff", "")),
                              "evidence_sha256": digest(json.dumps({"checks": checks, "reviews": reviews}, sort_keys=True)),
                              "checks_passed": sum(c.get("ok") is True for c in checks), "checks_total": len(checks),
                              "reviews_total": len(reviews)}
                    keep("run", identifier, value.get("spec", {}).get("workspace"), record)
        for identifier, versions in workflow_records.items():
            _, project, latest = max(versions, key=lambda item: item[0])
            if not latest["candidate_digest"] and latest.get("run_id"):
                captured = [item for item in versions if item[1] == project
                            and item[2].get("run_id") == latest["run_id"] and item[2]["candidate_digest"]]
                if captured:
                    latest["candidate_digest"] = max(captured, key=lambda item: item[0])[2]["candidate_digest"]
            keep("task", identifier, project, latest)
        for row in db.execute("SELECT id,project,body FROM worker_operation_receipts WHERE worker=? AND workspace=?", (worker, workspace)).fetchall():
            record = json.loads(row[2])
            if record["state"] == "dispatched":
                record["state"] = "revoked_pending_reconciliation"
                db.execute("UPDATE worker_operation_receipts SET body=? WHERE id=?", (json.dumps(record), row[0]))
            keep("operation", row[0], row[1], record)

    def archives(self, workspace, *, authority=None, cursor=0, limit=50):
        """Only metadata; raw cache/evidence is never replayed after revocation.

        Team membership, session and current project grants are resolved in the
        same read transaction as the archive, rather than trusting caller roles.
        """
        limit = max(1, min(limit, 100))
        with self.store.connect() as db:
            db.execute("BEGIN")
            parameters = [workspace, max(0, cursor)]
            clause = "workspace=? AND rowid>?"
            if self._team_workspace(db, workspace):
                ctx = authority or {}
                member = db.execute("SELECT m.role FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND a.disabled=0",
                                    (workspace, ctx.get("actor"))).fetchone()
                session = db.execute("SELECT 1 FROM sessions WHERE hash=? AND account=? AND workspace=? AND expires>=?",
                                     (ctx.get("session"), ctx.get("actor"), workspace, time.time())).fetchone()
                if not member or not session:
                    raise HTTPException(403, "Current workspace membership is required for archived records")
                projects = [(r[0], r[1]) for r in db.execute("SELECT worker,path,members FROM project_bindings WHERE workspace=?", (workspace,))
                            if member[0] == "owner" or not json.loads(r[2]) or ctx["actor"] in json.loads(r[2])]
                if not projects:
                    return {"items": [], "next_cursor": None, "has_more": False}
                clause += " AND (" + " OR ".join("(worker=? AND project=?)" for _ in projects) + ")"
                parameters += [v for project in projects for v in project]
            rows = db.execute("SELECT rowid,body FROM worker_archives WHERE " + clause + " ORDER BY rowid LIMIT ?", (*parameters, limit+1)).fetchall()
        page = rows[:limit]
        return {"items": [json.loads(row[1]) for row in page], "next_cursor": page[-1][0] if len(rows) > limit else None,
                "has_more": len(rows) > limit}

    def events(self, worker, run_id, cursor, workspace, *, authority=None):
        with self.store.connect() as db:
            db.execute("BEGIN")
            if not db.execute(f"SELECT w.id FROM {MACHINES} WHERE {ACTIVE} AND {SCOPE}=? AND w.id=?", (workspace, worker)).fetchone():
                raise HTTPException(404, "Execution machine not found")
            if self._team_workspace(db, workspace):
                ctx = authority or {}
                member = db.execute("SELECT m.role FROM memberships m JOIN accounts a ON a.id=m.account WHERE m.workspace=? AND m.account=? AND a.disabled=0",
                                    (workspace, ctx.get("actor"))).fetchone()
                session = db.execute("SELECT 1 FROM sessions WHERE hash=? AND account=? AND workspace=? AND expires>=?",
                                     (ctx.get("session"), ctx.get("actor"), workspace, time.time())).fetchone()
                if not member or not session:
                    raise HTTPException(403, "Current workspace membership is required for live evidence")
                cached = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, "/api/runs/"+run_id)).fetchone()
                saved = json.loads(cached[0]).get("body", {}) if cached else {}
                project = saved.get("spec", {}).get("workspace")
                binding = db.execute("SELECT members FROM project_bindings WHERE workspace=? AND worker=? AND path=?", (workspace, worker, project)).fetchone()
                if not binding or (member[0] != "owner" and json.loads(binding[0]) and ctx.get("actor") not in json.loads(binding[0])):
                    raise HTTPException(404, "Run not found")
            rows = db.execute("SELECT event FROM worker_events WHERE worker=? AND run_id=? AND sequence>? ORDER BY sequence LIMIT 500", (worker, run_id, cursor)).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def _workflow_uuid(value):
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            return None

    def _workflow_feature_requirement(self, db, worker, method, path, body):
        """Requirements come from scoped, accepted records or our queued payloads.

        Provisional child metadata protects an interrupted start until its reply
        is accepted. Only a successful matching reply creates a permanent row,
        so a rejected request-ID collision cannot stamp an unrelated workflow.
        """
        if method != "POST" or path.endswith(("/cancel", "/comment", "/reviewer")):
            return False
        if path == "/api/workflows" and isinstance(body, dict):
            if body.get("task_settings") is not None:
                return True
            related = {self._workflow_uuid(body.get(key)) for key in ("parent_workflow_id", "request_id")}
        else:
            match = re.fullmatch(r"/api/workflows/([a-f0-9-]{36})/[^/]+", path)
            related = {match.group(1) if match else None}
            if path.endswith("/revise") and isinstance(body, dict):
                related.add(self._workflow_uuid(body.get("request_id")))
        related.discard(None)
        if not related:
            return False
        for workflow in related:
            for table in ("worker_workflow_features", "worker_workflow_feature_requests"):
                rows = db.execute(f"SELECT features FROM {table} WHERE worker=? AND workflow=?", (worker, workflow))
                if any("workflow-task-settings-v1" in json.loads(row[0]) for row in rows):
                    return True
        for row in db.execute("SELECT request FROM worker_commands WHERE worker=? AND response IS NULL", (worker,)):
            requirement = json.loads(row[0]).get("workflow_features") or {}
            if requirement.get("workflow") in related and "workflow-task-settings-v1" in requirement.get("required", []):
                return True
        return False

    def _workflow_feature_child(self, method, path, body):
        if method == "POST" and isinstance(body, dict) and (path == "/api/workflows" or path.endswith("/revise")):
            return self._workflow_uuid(body.get("request_id"))
        return None

    async def request(self, worker, method, path, query, body, *, workspace, timeout=60, authority=None, requester=None):
        identifier = str(uuid.uuid4())
        deadline = time.monotonic() + timeout
        expires = time.time() + timeout
        try:
            queued = await asyncio.wait_for(asyncio.to_thread(self._enqueue_request, identifier, worker, method, path, query, body,
                                                              workspace, deadline, expires, authority, requester), max(0, timeout))
        except asyncio.TimeoutError:
            raise HTTPException(504, f"Relay admission timed out (request {identifier}). Inspect saved history before retrying; any queued command retains this request's original expiry.")
        if queued is not None:
            return queued
        while time.monotonic() < deadline:
            try:
                response = await asyncio.wait_for(asyncio.to_thread(self._collect_response, identifier), max(0, deadline-time.monotonic()))
            except asyncio.TimeoutError:
                break
            if response is not None:
                return response
            await asyncio.sleep(min(.1, max(0, deadline-time.monotonic())))
        raise HTTPException(504, f"Worker response timed out (request {identifier}). It may still finish. Inspect run history before retrying; the runtime will not redispatch this request.")

    def _collect_response(self, identifier):
        with self.store.connect() as db:
            row = db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()
            if row and row[0] is not None:
                db.execute("DELETE FROM worker_commands WHERE id=?", (identifier,))
                db.execute("DELETE FROM worker_command_dispatch WHERE id=?", (identifier,))
                db.execute("DELETE FROM worker_command_priority WHERE id=?", (identifier,))
                return json.loads(row[0])
        return None

    def _enqueue_request(self, identifier, worker, method, path, query, body, workspace, deadline, expires, authority, requester):
        if not permitted(method, path, query):
            raise HTTPException(403, "This operation is not available through a paired worker. Manage credentials locally.")
        descriptor = self.worker(worker, workspace)
        with self.store.connect() as db:
            required = self._workflow_feature_requirement(db, worker, method, path, body)
        if required and "workflow-task-settings-v1" not in descriptor.get("features", []):
            raise HTTPException(409, "Update this worker to preserve task-specific instructions and checks")
        cache_path = path + ("?" + query if query else "")
        if not descriptor["online"]:
            cached = self.cached(worker, cache_path) if method == "GET" and not (authority or {}).get("team") else None
            if cached:
                return {**cached, "offline": True}
            raise HTTPException(503, "Execution machine is offline. Wake it and start its Parallax worker; no work was dispatched.")
        limits = limits_for(workspace)
        priority = is_control(method, path)
        payload = encode({"method": method, "path": path, "query": query, "body": body, "expires_at": expires,
                          **({"authority":authority} if authority else {}), **({"requester":requester} if requester else {})})
        if len(payload) > LOW_DISK_BODY and self._low_disk(workspace):
            raise HTTPException(507, "Hosted storage is low, so large requests are paused. Run controls such as stop and steer still work.")
        with self.store.connect() as db:
            if not allow_rate(db, ("relay-control:" if priority else "relay:") + workspace,
                              60 if priority else limits.relayed_per_window, 60 if priority else RELAY_WINDOW):
                raise HTTPException(429, "Too many requests reached this workspace's machines in the last five minutes. Retry shortly.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if time.monotonic() >= deadline:
                raise HTTPException(504, "Request expired during relay admission; no work was queued")
            self._sweep(db)
            waiting, queued = db.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(request AS BLOB))),0) FROM worker_commands WHERE worker=? AND response IS NULL",
                                         (worker,)).fetchone()
            controls = db.execute("SELECT COUNT(*) FROM worker_commands c JOIN worker_command_priority p ON p.id=c.id WHERE c.worker=? AND c.response IS NULL", (worker,)).fetchone()[0]
            if priority and (len(payload.encode()) > CONTROL_BYTES or controls >= CONTROL_SLOTS):
                raise HTTPException(429, "The machine's reserved cancellation queue is full. Retry shortly.")
            allowed_count = limits.pending_commands + (CONTROL_SLOTS if priority else 0)
            allowed_bytes = limits.pending_bytes + (CONTROL_BYTES * CONTROL_SLOTS if priority else 0)
            if waiting >= allowed_count or queued + len(payload.encode()) > allowed_bytes:
                raise HTTPException(429, "This machine has too many unanswered requests. Wait for it to catch up, then retry.")
            # Re-read parent requirements under the queue writer lock. A prior
            # child can become durable while this request is being authorized.
            required = self._workflow_feature_requirement(db, worker, method, path, body)
            if required:
                if "workflow-task-settings-v1" not in self.worker(worker, workspace).get("features", []):
                    raise HTTPException(409, "Update this worker to preserve task-specific instructions and checks")
                child = self._workflow_feature_child(method, path, body)
                if child:
                    request_value = json.loads(payload)
                    request_value["workflow_features"] = {"workflow":child, "required":["workflow-task-settings-v1"]}
                    payload = encode(request_value)
                    if queued + len(payload.encode()) > allowed_bytes:
                        raise HTTPException(429, "This machine has too many unanswered requests. Wait for it to catch up, then retry.")
            if time.monotonic() >= deadline:
                raise HTTPException(504, "Request expired during relay admission; no work was queued")
            db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,NULL,?)", (identifier, worker, payload, time.time()))
            if priority:
                db.execute("INSERT INTO worker_command_priority VALUES(?,1)", (identifier,))
            requirement = json.loads(payload).get("workflow_features")
            if requirement:
                db.execute("INSERT INTO worker_workflow_feature_requests VALUES(?,?,?,?)",
                    (worker, identifier, requirement["workflow"], json.dumps(requirement["required"])))
        return None

    def cached(self, worker, path):
        with self.store.connect() as db:
            row = db.execute("SELECT response FROM worker_cache WHERE worker=? AND path=?", (worker, path)).fetchone()
        return json.loads(row[0]) if row else None

    # Worker-facing operations: authorized by the worker's own scoped token -----
    def connect(self, code, name, metadata):
        # Pairing codes carry 192 random bits, so no shared guess limit is needed (one would let
        # anonymous traffic block every pairing).
        identifier, token, now = str(uuid.uuid4()), secrets.token_urlsafe(32), time.time()
        with self.store.connect() as db:
            # Raising inside this transaction rolls back the deletes, so a refused code stays usable.
            if db.execute("DELETE FROM worker_pairs WHERE hash=? AND expires>=? RETURNING hash", (digest(code), now)).fetchone():
                workspace = OWNER_WORKSPACE
            else:
                scope = db.execute("DELETE FROM worker_pair_scope WHERE hash=? AND expires>=? RETURNING workspace", (digest(code), now)).fetchone()
                if not scope:
                    raise HTTPException(401, "Pairing code is invalid, expired, or already used")
                workspace = scope[0]
                if self._team_workspace(db, workspace):
                    issuer = db.execute("SELECT actor,session FROM worker_pair_authority WHERE hash=?", (digest(code),)).fetchone()
                    if not self._pair_authorized(db, workspace, dict(issuer) if issuer else None, now):
                        raise HTTPException(401, "Pairing authorization ended. Ask a current owner for a new code")
                db.execute("DELETE FROM worker_pair_authority WHERE hash=?", (digest(code),))
            limits = limits_for(workspace)
            if self._active(db, workspace) >= limits.workers:
                raise HTTPException(409, f"This workspace already has {limits.workers} machines. Disconnect one in Studio, then retry with the same code.")
            personal = workspace != OWNER_WORKSPACE
            db.execute("INSERT INTO workers(id,name,token_hash,seen,revoked,metadata) VALUES(?,?,?,?,?,?)",
                       (identifier, name, "scoped:" + identifier if personal else digest(token), now, int(personal), encode(metadata)))
            db.execute("INSERT INTO worker_scope(worker,workspace,token_hash) VALUES(?,?,?)",
                       (identifier, workspace, digest(token) if personal else None))
        return {"id": identifier, "token": token}

    def features(self, worker, features):
        with self.store.connect() as db:
            self._claim(db, worker)
            row = db.execute("SELECT metadata FROM workers WHERE id=?", (worker,)).fetchone()
            metadata = json.loads(row[0]); metadata["features"] = features
            db.execute("UPDATE workers SET metadata=? WHERE id=?", (encode(metadata),worker))

    def heartbeat(self, worker, features, transport_status):
        with self.store.connect() as db:
            self._claim(db, worker)
            row = db.execute("SELECT metadata FROM workers WHERE id=?", (worker,)).fetchone()
            metadata = json.loads(row[0])
            metadata.update(features=features, transport_status=transport_status)
            db.execute("UPDATE workers SET metadata=? WHERE id=?", (encode(metadata), worker))
        return {"ok": True, "features": ["worker-control-v1", "worker-byte-batches-v1"]}

    def authenticate(self, token):
        with self.store.connect() as db:
            row = (db.execute("SELECT id FROM workers WHERE token_hash=? AND revoked=0", (digest(token),)).fetchone()
                   or db.execute("SELECT worker FROM worker_scope WHERE token_hash=? AND revoked=0", (digest(token),)).fetchone())
        if not row:
            raise HTTPException(401, "Worker connection revoked or invalid")
        return row[0]

    def pending(self, worker, *, mark_dispatched=True):
        with self.store.connect() as db:
            workspace = self._claim(db, worker)
            self._sweep(db)
            # Additive upgrade: old queues have no priority side row. Recognize
            # their typed cancellation paths before taking the eight-command page.
            rows = db.execute("SELECT id,request FROM worker_commands WHERE worker=? AND response IS NULL ORDER BY created LIMIT ?",
                              (worker, limits_for(workspace).pending_commands + CONTROL_SLOTS)).fetchall()
            for row in rows:
                command = json.loads(row["request"])
                if is_control(command["method"], command["path"]):
                    db.execute("INSERT OR IGNORE INTO worker_command_priority VALUES(?,1)", (row["id"],))
            rows = db.execute("SELECT c.id,c.request FROM worker_commands c LEFT JOIN worker_command_priority p ON p.id=c.id WHERE c.worker=? AND c.response IS NULL ORDER BY COALESCE(p.priority,0) DESC,c.created LIMIT 8", (worker,)).fetchall()
        commands = []
        for row in rows:
            command = self.dispatch(worker, row["id"], mark_dispatched=mark_dispatched)
            if command is not None:
                commands.append(command)
        return commands

    def dispatched(self, worker, identifier):
        with self.store.connect() as db:
            return bool(db.execute("SELECT 1 FROM worker_command_dispatch d JOIN worker_commands c ON c.id=d.id WHERE c.worker=? AND c.id=?",
                                   (worker, identifier)).fetchone())

    def reject_undispatched(self, worker, identifier, response):
        """A concurrent authorized delivery must retain its eventual worker receipt."""
        with self.store.connect() as db:
            self._claim(db, worker)
            rejected = db.execute("UPDATE worker_commands SET response=? WHERE worker=? AND id=? AND response IS NULL AND NOT EXISTS(SELECT 1 FROM worker_command_dispatch d WHERE d.id=worker_commands.id)",
                       (encode(response), worker, identifier))
            if rejected.rowcount:
                db.execute("DELETE FROM worker_workflow_feature_requests WHERE worker=? AND command=?", (worker, identifier))
            row = db.execute("SELECT response FROM worker_commands WHERE worker=? AND id=?", (worker, identifier)).fetchone()
            return row is None or row[0] is not None

    def dispatch(self, worker, identifier, *, mark_dispatched=True):
        # Initialize optional authorization tables before holding the writer lock.
        # Once locked, membership/session changes serialize with the first dispatch.
        with self.store.connect() as db:
            initial = db.execute("SELECT request FROM worker_commands WHERE id=? AND worker=?", (identifier,worker)).fetchone()
        if initial is None:
            return None
        teams = None
        if (json.loads(initial[0]).get("authority") or {}).get("team"):
            from .teams import Teams
            teams = self.accounts.teams if self.accounts else Teams(self.store)
        with self.store.connect() as db:
            workspace = self._claim(db, worker)
            row = db.execute("SELECT c.request,c.response,d.dispatched FROM worker_commands c LEFT JOIN worker_command_dispatch d ON d.id=c.id WHERE c.id=? AND c.worker=?",
                             (identifier,worker)).fetchone()
            if row is None or row["response"] is not None:
                return None
            command = {"id":identifier, **json.loads(row["request"])}
            # This server-owned record is separate from worker authority, so legacy
            # workers receive their original payload while personal sign-out still
            # invalidates work that has not been dispatched.
            requester = command.pop("requester", None)
            try:
                ctx = command.get("authority") or {}
                pilot_feature = "pilot-observations-v1" if command["method"] == "POST" and command["path"] == "/api/pilot/observations" else (
                    "pilot-evaluation-v1" if command["method"] == "POST" and command["path"] == "/api/pilot/benchmark" and isinstance(command.get("body"), dict) and command["body"].get("evaluation") is not None else None)
                if pilot_feature and pilot_feature not in self.worker(worker, workspace).get("features", []):
                    if row["dispatched"] is not None:
                        return None
                    raise HTTPException(409, "Update this worker for recorded pilot evidence")
                requires_v2 = ctx.get("team") or command["path"].endswith(("/revise","/approve","/apply","/publication-preview","/begin-publication","/record-publication")) or (
                    command["method"] == "POST" and command["path"] == "/api/workflows" and isinstance(command.get("body"),dict) and command["body"].get("schema_version") == "2.0")
                if requires_v2 and "workflow-v2" not in self.worker(worker,workspace).get("features",[]):
                    # Keep a dispatched receipt recoverable, but never send team or
                    # versioned operations to a worker that has since downgraded.
                    if row["dispatched"] is not None:
                        return None
                    raise HTTPException(409, "Update this worker for versioned workflows")
                uses_task_settings = self._workflow_feature_requirement(db, worker, command["method"], command["path"], command.get("body"))
                if uses_task_settings and "workflow-task-settings-v1" not in self.worker(worker,workspace).get("features",[]):
                    if row["dispatched"] is not None:
                        return None
                    raise HTTPException(409, "Update this worker to use task-specific instructions and checks")
                if uses_task_settings:
                    child = self._workflow_feature_child(command["method"], command["path"], command.get("body"))
                    if child:
                        command["workflow_features"] = {"workflow":child, "required":["workflow-task-settings-v1"]}
                if row["dispatched"] is not None:
                    return command
                if requester:
                    principal = self.accounts.principal_from_hash(requester["session"]) if self.accounts else None
                    if (not principal or principal.workspace != workspace or principal.workspace != requester["workspace"]
                            or (principal.account or {}).get("id", "operator") != requester["actor"]):
                        raise HTTPException(403, "Session ended before queued dispatch")
                if (command.get("authority") or {}).get("team"):
                    command["authority"] = teams.reauthorize(command["authority"],worker,command["method"],command["path"])
            except HTTPException as exc:
                db.execute("UPDATE worker_commands SET response=? WHERE id=? AND response IS NULL", (encode({"status":exc.status_code,"body":{"detail":exc.detail},"content_type":"application/json"}),identifier))
                db.execute("DELETE FROM worker_workflow_feature_requests WHERE worker=? AND command=?", (worker, identifier))
                return None
            if mark_dispatched:
                saved = {k:v for k,v in command.items() if k != "id"}
                if requester:
                    saved["requester"] = requester
                db.execute("UPDATE worker_commands SET request=? WHERE id=?", (encode(saved),identifier))
                requirement = saved.get("workflow_features")
                if requirement:
                    db.execute("INSERT OR IGNORE INTO worker_workflow_feature_requests VALUES(?,?,?,?)",
                        (worker, identifier, requirement["workflow"], json.dumps(requirement["required"])))
                dispatched = time.time()
                db.execute("INSERT INTO worker_command_dispatch VALUES(?,?)", (identifier,dispatched))
                self._record_receipt(db, worker, workspace, {**command, **({"requester": requester} if requester else {})}, dispatched)
            return command

    def complete(self, worker, identifier, response):
        serialized = encode(response)
        with self.store.connect() as db:
            workspace = self._claim(db, worker)
            row = db.execute("SELECT request,response FROM worker_commands WHERE id=? AND worker=?", (identifier, worker)).fetchone()
            if not row:
                raise HTTPException(404, "Worker request not found")
            if row["response"] is not None:
                if row["response"] != serialized:
                    raise HTTPException(409, "Worker response cannot be replaced")
                return {"ok": True}
            # Answers wait only until Studio collects them, so their total per machine stays within its queue budget.
            limits = limits_for(workspace)
            held = db.execute("SELECT COALESCE(SUM(length(CAST(response AS BLOB))),0) FROM worker_commands WHERE worker=? AND response IS NOT NULL",
                              (worker,)).fetchone()[0]
            if held + len(serialized) > limits.pending_bytes or (len(serialized) > LOW_DISK_BODY and self._low_disk(workspace)):
                serialized = encode({"status": 507, "content_type": "application/json",
                                     "body": {"detail": "The machine's answer was too large to hold right now. Retry shortly."}})
            db.execute("UPDATE worker_commands SET response=? WHERE id=?", (serialized, identifier))
            receipt = db.execute("SELECT body FROM worker_operation_receipts WHERE id=? AND worker=?", (identifier, worker)).fetchone()
            if receipt:
                record = json.loads(receipt[0])
                record.update(state="completed", status=response["status"], response_sha256=digest(encode(response)), completed_at=time.time())
                db.execute("UPDATE worker_operation_receipts SET body=? WHERE id=?", (json.dumps(record), identifier))
            request = json.loads(row["request"])
            requirement = request.get("workflow_features") or {}
            if (200 <= response["status"] < 300 and isinstance(response.get("body"), dict)
                    and response["body"].get("id") == requirement.get("workflow") and requirement.get("workflow")):
                db.execute("INSERT OR IGNORE INTO worker_workflow_features VALUES(?,?,?)",
                    (worker, requirement["workflow"], json.dumps(requirement["required"])))
                # A matching successful retry reconciles earlier unanswered
                # requests for the same workflow without changing its settings.
                db.execute("DELETE FROM worker_workflow_feature_requests WHERE worker=? AND workflow=?", (worker, requirement["workflow"]))
            detail = (response.get("body") or {}).get("detail") if isinstance(response.get("body"), dict) else None
            refused_before_effect = response["status"] in {403, 404, 422} or (
                response["status"] in {400, 409} and isinstance(detail, str) and detail in {
                    "This start request was already used with different inputs",
                    "This start request belongs to another actor",
                    "This revision request was already used with different inputs",
                    "This revision request belongs to another actor",
                    "Request identity was reused with different content",
                })
            if refused_before_effect:
                db.execute("DELETE FROM worker_workflow_feature_requests WHERE worker=? AND command=?", (worker, identifier))
            if request["method"] == "GET" and 200 <= response["status"] < 300 and not self._low_disk(workspace):
                self._cache(db, worker, request["path"] + ("?" + request["query"] if request["query"] else ""), response)
                self._prune(db, worker)
        return {"ok": True}

    def sync(self, worker, runs, events):
        encode({"runs": runs, "events": events})
        with self.store.connect() as db:
            workspace = self._claim(db, worker)
            limits = limits_for(workspace)
            if (runs or events) and self._low_disk(workspace):
                # Keep the machine reachable so stop and steer still work; evidence stays on the machine.
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
            db.execute("UPDATE worker_scope SET evidence_bytes=evidence_bytes+? WHERE worker=?", (added, worker))
            self._prune(db, worker)
        return {"ok": True, "stored": True}

    # Internal helpers ----------------------------------------------------------
    @staticmethod
    def _active(db, workspace):
        return db.execute(f"SELECT COUNT(*) FROM {MACHINES} WHERE {ACTIVE} AND {SCOPE}=?", (workspace,)).fetchone()[0]

    @staticmethod
    def _claim(db, worker):
        """Mark the machine seen and return its workspace, or refuse if it was revoked or deleted after
        authentication. The write comes first, so the check and the rest of the request share one transaction."""
        updated = db.execute(f"UPDATE workers SET seen=? WHERE id=? AND EXISTS(SELECT 1 FROM {MACHINES} WHERE w.id=workers.id AND {ACTIVE})",
                             (time.time(), worker)).rowcount
        if not updated:
            raise HTTPException(401, "Worker connection revoked or invalid")
        db.execute("INSERT OR IGNORE INTO worker_scope(worker,workspace) VALUES(?,?)", (worker, OWNER_WORKSPACE))
        return db.execute("SELECT workspace FROM worker_scope WHERE worker=?", (worker,)).fetchone()[0]

    @staticmethod
    def _sweep(db):
        """Expire commands for every machine, including ones that went offline and never poll again."""
        now = time.time()
        db.execute("DELETE FROM worker_commands WHERE created<?", (now - COMMAND_RETENTION,))
        # Answers nobody collected (the Studio request timed out) are kept only briefly.
        db.execute("DELETE FROM worker_commands WHERE response IS NOT NULL AND created<?", (now - 300,))
        db.execute("DELETE FROM worker_command_dispatch WHERE id NOT IN (SELECT id FROM worker_commands)")
        db.execute("DELETE FROM worker_command_priority WHERE id NOT IN (SELECT id FROM worker_commands)")

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
