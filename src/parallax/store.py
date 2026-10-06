"""Durable local run state; no provider credentials are stored here."""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def state_directory() -> Path:
    if os.environ.get("PARALLAX_HOME"):
        return Path(os.environ["PARALLAX_HOME"]).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Parallax"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "parallax"

class Store:
    def __init__(self, home: Path | None = None):
        self._project_handles = {}
        self.home = (home or state_directory()).resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.home / "state.sqlite3"
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL, task_id TEXT, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS run_events ON events(run_id, sequence);
            CREATE TABLE IF NOT EXISTS actions(run_id TEXT NOT NULL, id TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(run_id,id));
            CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY, spec TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS project_locks(workspace TEXT PRIMARY KEY, run_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS project_profiles(name TEXT PRIMARY KEY, profile TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback(run_id TEXT PRIMARY KEY, metrics TEXT NOT NULL);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, result: dict):
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,result=excluded.result,updated=excluded.updated",
                       (result["run_id"], result["spec"]["workspace"], result["status"], json.dumps(result), now()))

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT result FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def runs(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT result FROM runs ORDER BY updated DESC LIMIT 100")]

    def event(self, run_id: str, kind: str, data: dict | None = None, task_id: str | None = None) -> dict:
        stamp = now()
        with self.connect() as db:
            cur = db.execute("INSERT INTO events(run_id,timestamp,kind,task_id,data) VALUES(?,?,?,?,?)", (run_id,stamp,kind,task_id,json.dumps(data or {})))
            sequence = cur.lastrowid
        return {"schema_version":"1.0", "sequence":sequence, "run_id":run_id,"timestamp":stamp,"kind":kind,"task_id":task_id,"data":data or {}}

    def events(self, run_id: str, cursor: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 250", (run_id,cursor)).fetchall()
        return [{"schema_version":"1.0", **dict(row), "data":json.loads(row["data"])} for row in rows]

    def claim(self, workspace: str, run_id: str):
        # SQLite protects one state directory; a process lock also protects the
        # same project when two runtimes use different PARALLAX_HOME values.
        import fcntl
        key = str(Path(workspace).resolve())
        acquired = None
        if key in self._project_handles:
            if self._project_handles[key][0] != run_id:
                raise ValueError("Project already has an implementation run")
        else:
            locks = Path("/tmp") / f"parallax-project-locks-{os.getuid()}"
            locks.mkdir(mode=0o700, exist_ok=True)
            if locks.is_symlink() or locks.stat().st_uid != os.getuid() or locks.stat().st_mode & 0o077:
                raise ValueError("Project lock directory must be private and owned by this user")
            path = locks / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            acquired = os.fdopen(descriptor, "a")
            try:
                if os.fstat(descriptor).st_uid != os.getuid(): raise ValueError("Project lock has a different owner")
                fcntl.flock(acquired, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, ValueError):
                acquired.close()
                raise ValueError("Project already has an implementation run in another runtime")
        try:
            self._claim_database(workspace, run_id)
        except BaseException:
            if acquired: acquired.close()
            raise
        if acquired: self._project_handles[key] = (run_id, acquired)

    def _claim_database(self, workspace: str, run_id: str):
        with self.connect() as db:
            try:
                db.execute("INSERT INTO project_locks VALUES(?,?)", (workspace,run_id))
            except sqlite3.IntegrityError:
                owner = db.execute("SELECT run_id FROM project_locks WHERE workspace=?", (workspace,)).fetchone()[0]
                if owner != run_id:
                    raise ValueError(f"Project already has an implementation run: {owner}")

    def close(self):
        for _, handle in getattr(self, "_project_handles", {}).values():
            handle.close()
        self._project_handles = {}

    def __del__(self):
        self.close()

    def release(self, run_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM project_locks WHERE run_id=?", (run_id,))
        for key, (owner, handle) in list(self._project_handles.items()):
            if owner == run_id:
                handle.close()
                del self._project_handles[key]

    def action(self, run_id: str, action_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT result FROM actions WHERE run_id=? AND id=?", (run_id, action_id)).fetchone()
        return json.loads(row[0]) if row else None

    def save_action(self, run_id: str, action_id: str, result: dict):
        with self.connect() as db:
            db.execute("INSERT INTO actions VALUES(?,?,?)", (run_id,action_id,json.dumps(result)))

    def profiles(self) -> list[dict]:
        with self.connect() as db:
            return [{"name":row[0],"spec":json.loads(row[1])} for row in db.execute("SELECT name,spec FROM profiles ORDER BY name")]

    def put_profile(self, name: str, spec: dict):
        if not name.strip() or len(name)>100:
            raise ValueError("Profile name must contain 1–100 characters")
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES(?,?) ON CONFLICT(name) DO UPDATE SET spec=excluded.spec", (name,json.dumps(spec)))

    def delete_profile(self, name: str):
        with self.connect() as db:
            db.execute("DELETE FROM profiles WHERE name=?",(name,))

    def project_profiles(self) -> list[dict]:
        with self.connect() as db:
            return [{"name": row[0], "profile": json.loads(row[1])} for row in db.execute("SELECT name,profile FROM project_profiles ORDER BY name")]

    def put_project_profile(self, name: str, profile: dict):
        from .models import ProjectProfile
        if not name.strip() or len(name) > 100: raise ValueError("Profile name must contain 1–100 characters")
        value = ProjectProfile.model_validate(profile).model_dump()
        with self.connect() as db:
            db.execute("INSERT INTO project_profiles VALUES(?,?) ON CONFLICT(name) DO UPDATE SET profile=excluded.profile", (name, json.dumps(value)))

    def delete_project_profile(self, name: str):
        with self.connect() as db:
            db.execute("DELETE FROM project_profiles WHERE name=?", (name,))
