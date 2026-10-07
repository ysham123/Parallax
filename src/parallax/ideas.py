"""Persistent per-project idea graph: what was tried, what the evidence said, and distilled lessons.

Memory is local to the executing machine and scoped to one project: a key over
the project's real path and its Git root commits, so a different repository
cloned at the same path starts fresh. Nodes are projected from run facts at the
end of a run through a whitelist (titles, requirements, outcomes, verdicts,
check names); patches, tool output and provider answers are never stored.

Only coordinators read memory, and only as data: a small primer computed once
per run plus results of searches the coordinator chooses to make. Retrieval is
deterministic (BM25 over tokens plus file overlap, weighted by evidence and by
recency counted in project runs), so the same history gives the same context.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

KEEP_RUNS = 200
MAX_ACTIVE_LESSONS = 200
STALE_AFTER = 12
LESSON_STATUSES = ("active", "contested", "disabled", "stale", "superseded")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, run_seq INTEGER NOT NULL UNIQUE, status TEXT NOT NULL,
    distilled_sha256 TEXT);
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL, local_key TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
    files TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL, outcome TEXT, category TEXT, meta TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS node_runs ON nodes(run_id, kind);
CREATE TABLE IF NOT EXISTS edges(src TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, rel TEXT NOT NULL,
    dst TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, PRIMARY KEY(src, rel, dst));
CREATE TABLE IF NOT EXISTS lessons(node_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE, kind TEXT NOT NULL,
    status TEXT NOT NULL, support REAL NOT NULL DEFAULT 0, refute REAL NOT NULL DEFAULT 0,
    last_support_seq INTEGER NOT NULL DEFAULT 0, exposures_since_support INTEGER NOT NULL DEFAULT 0, distiller TEXT);
CREATE TABLE IF NOT EXISTS lesson_runs(lesson_id TEXT NOT NULL REFERENCES lessons(node_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL, effect TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY(lesson_id, run_id));
CREATE TABLE IF NOT EXISTS exposures(run_id TEXT NOT NULL, node_id TEXT NOT NULL, via TEXT NOT NULL,
    PRIMARY KEY(run_id, node_id));
"""


def project_key(workspace: str) -> str:
    real = os.path.realpath(workspace)
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    try:
        found = subprocess.run(["git", "-C", real, "-c", "core.fsmonitor=false", "rev-list", "--max-parents=0", "HEAD"],
                               capture_output=True, text=True, timeout=10, env=env, check=False)
        roots = sorted(found.stdout.split()) if found.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        roots = []
    return hashlib.sha256((real + "\0" + (",".join(roots) or "unborn")).encode()).hexdigest()


# Text helpers ----------------------------------------------------------------

def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    return [_stem(word) for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1]


def jaccard(left, right) -> float:
    left, right = set(left), set(right)
    return len(left & right) / len(left | right) if left and right else 0.0


def _file_parts(files) -> set:
    parts = set()
    for name in files or []:
        path = PurePosixPath(str(name).rstrip("/"))
        parts.add(str(path))
        parts.update(str(parent) for parent in path.parents if str(parent) not in ("", "."))
    return parts


def bm25(query: list[str], documents: list[list[str]], k1: float = 1.4, b: float = 0.75) -> list[float]:
    if not documents:
        return []
    average = sum(len(d) for d in documents) / len(documents) or 1.0
    frequency = {}
    for document in documents:
        for term in set(document):
            frequency[term] = frequency.get(term, 0) + 1
    scores = []
    for document in documents:
        counts = {}
        for term in document:
            counts[term] = counts.get(term, 0) + 1
        score = 0.0
        for term in set(query):
            if term not in counts:
                continue
            idf = math.log(1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            tf = counts[term]
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(document) / average))
        scores.append(score)
    return scores


def _clip(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class GraphStore:
    """Storage, projection and retrieval. IdeaStore adds distillation."""

    def __init__(self, home: Path, workspace: str, *, key: str | None = None):
        self.workspace = os.path.realpath(workspace)
        self.key = key or project_key(workspace)
        directory = Path(home) / "memory"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / f"{self.key[:32]}.sqlite3"
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('project',?)", (self.key,))
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def node_id(self, kind: str, run_id: str | None, local_key: str) -> str:
        prefix = {"goal": "G", "approach": "A", "evidence": "E", "lesson": "L"}[kind]
        return prefix + "-" + hashlib.sha256(f"{self.key}|{run_id or ''}|{kind}|{local_key}".encode()).hexdigest()[:12]

    # Projection --------------------------------------------------------------
    def project(self, result: dict, check_events: list[dict]) -> int:
        """Idempotently record one finished run's facts. Returns the run's sequence number."""
        from .context import memory_scrubber
        run_id, now = result["run_id"], time.time()
        spec = result["spec"]
        scrub = memory_scrubber(result["artifacts"].get("directory"), spec.get("workspace"))
        with self.connect() as db:
            row = db.execute("SELECT run_seq FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                sequence = (db.execute("SELECT COALESCE(MAX(run_seq),0) FROM runs").fetchone()[0] or 0) + 1
                db.execute("INSERT INTO runs(run_id,run_seq,status) VALUES(?,?,?)", (run_id, sequence, result["status"]))
            else:
                sequence = row[0]
                db.execute("UPDATE runs SET status=? WHERE run_id=?", (result["status"], run_id))
            db.execute("DELETE FROM nodes WHERE run_id=?", (run_id,))
            goal = self.node_id("goal", run_id, "goal")
            self._node(db, goal, run_id, "goal", "goal", _clip(scrub(spec["prompt"]), 200), _clip(scrub(spec["prompt"]), 2000), [], "runtime",
                       {"completed": "pass", "failed": "fail", "needs_attention": "fail"}.get(result["status"]), None,
                       {"mode": spec["mode"]}, now)
            sessions = {}
            for session in result.get("sessions", []):
                if session.get("task_id") and (session.get("effective_settings") or {}).get("model"):
                    sessions[session["task_id"]] = session["effective_settings"]["model"]
            selected = result["artifacts"].get("selected_task")
            approaches = {}
            for task in result["tasks"]:
                outcome = self._outcome(task, spec["mode"], selected)
                approach = self.node_id("approach", run_id, task["id"])
                approaches[task["id"]] = approach
                outcome_result = task.get("result") or {}
                self._node(db, approach, run_id, "approach", task["id"], _clip(scrub(task.get("title")), 200),
                           _clip(scrub(task.get("prompt")), 1000), task.get("files", []), "runtime", outcome, task.get("failure_category"),
                           {"provider": task.get("provider"), "model": sessions.get(task["id"]), "attempts": task.get("attempts", 0),
                            "acceptance": [_clip(scrub(a), 200) for a in task.get("acceptance", [])][:8],
                            "changed_files": (outcome_result.get("changed_files") or [])[:30],
                            "variant_of": task.get("variant_of"), "directive": _clip(scrub(task.get("directive")), 300) or None}, now)
                db.execute("INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)", (approach, "pursues", goal))
                review = outcome_result.get("review")
                if review:
                    evidence = self.node_id("evidence", run_id, f"review:{task['id']}")
                    findings = [_clip(scrub(f if isinstance(f, str) else json.dumps(f, sort_keys=True)), 200) for f in (review.get("findings") or [])[:3]]
                    self._node(db, evidence, run_id, "evidence", f"review:{task['id']}", "Independent review " + ("approved" if review.get("ok") else "rejected"),
                               "\n".join(findings), task.get("files", []), "runtime", "pass" if review.get("ok") else "fail", None, {"type": "review"}, now)
                    db.execute("INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)", (evidence, "supports" if review.get("ok") else "refutes", approach))
            for task in result["tasks"]:
                if task.get("variant_of") in approaches:
                    db.execute("INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)", (approaches[task["id"]], "variant_of", approaches[task["variant_of"]]))
            for event in check_events:
                data = event.get("data") or event
                target = approaches.get(event.get("task_id") or data.get("task_id") or "")
                local = f"check:{event.get('sequence', '')}:{data.get('name')}"
                evidence = self.node_id("evidence", run_id, local)
                self._node(db, evidence, run_id, "evidence", local, _clip(f"Check {data.get('name')} {'passed' if data.get('ok') else 'failed'}", 200),
                           "", [], "runtime", "pass" if data.get("ok") else "fail", _clip(scrub(data.get("error")), 200) or None,
                           {"type": "check", "phase": data.get("phase"), "exit_code": data.get("exit_code")}, now)
                if target:
                    db.execute("INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)", (evidence, "supports" if data.get("ok") else "refutes", target))
            stale = db.execute("SELECT run_id FROM runs ORDER BY run_seq DESC LIMIT -1 OFFSET ?", (KEEP_RUNS,)).fetchall()
            for (old,) in stale:
                db.execute("DELETE FROM runs WHERE run_id=?", (old,))
        return sequence

    @staticmethod
    def _outcome(task, mode, selected):
        status = task.get("status")
        if status in {"completed", "resolved", "candidate"}:
            return "discarded" if mode == "compare" and selected and task["id"] != selected else "pass"
        if status == "discarded":
            return "discarded"
        if status == "failed":
            return "fail"
        return None

    @staticmethod
    def _node(db, identifier, run_id, kind, local_key, title, body, files, source, outcome, category, meta, created):
        db.execute("""INSERT INTO nodes(id,run_id,kind,local_key,title,body,files,source,outcome,category,meta,created)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,
            files=excluded.files,outcome=excluded.outcome,category=excluded.category,meta=excluded.meta""",
                   (identifier, run_id, kind, local_key, title, body, json.dumps(list(files or [])), source, outcome, category,
                    json.dumps({k: v for k, v in (meta or {}).items() if v not in (None, [], "")}, sort_keys=True), created))

    # Retrieval ---------------------------------------------------------------
    def _current_seq(self, db) -> int:
        return db.execute("SELECT COALESCE(MAX(run_seq),0) FROM runs").fetchone()[0] or 0

    def search(self, text: str, files=(), k: int = 6, exclude_run: str | None = None) -> list[dict]:
        """Deterministic retrieval of at most 3 lessons and 3 episodic nodes relevant to `text` and `files`."""
        query = tokenize(text)
        wanted = _file_parts(files)
        with self.connect() as db:
            current = self._current_seq(db)
            rows = db.execute("""SELECT n.*, r.run_seq, l.kind AS lesson_kind, l.status AS lesson_status, l.support, l.refute,
                l.last_support_seq, l.exposures_since_support FROM nodes n LEFT JOIN runs r ON r.run_id=n.run_id
                LEFT JOIN lessons l ON l.node_id=n.id WHERE n.kind IN ('goal','approach','lesson')""").fetchall()
        candidates = [r for r in rows if not (exclude_run and r["run_id"] == exclude_run)
                      and not (r["kind"] == "lesson" and r["lesson_status"] not in ("active", "contested"))]
        documents = [tokenize(f"{r['title']} {r['body']} {' '.join(json.loads(r['files']))} {json.loads(r['meta']).get('directive') or ''}")
                     for r in candidates]
        lexical = bm25(query, documents)
        best = max(lexical, default=0) or 1.0
        scored = []
        for row, document, value in zip(candidates, documents, lexical):
            parts = _file_parts(json.loads(row["files"]))
            overlap = len(parts & wanted) / len(wanted | parts) if wanted and parts else 0.0
            relevance = 0.7 * value / best + 0.3 * overlap
            if relevance < 0.05:
                continue
            if row["kind"] == "lesson":
                support = min(row["support"] or 0, 5)
                strength = (support + 1) / (support + (row["refute"] or 0) + 2) * 0.85 ** (row["exposures_since_support"] or 0)
                strength *= 0.5 if row["lesson_status"] == "contested" else 1.0
                runs_ago = max(0, current - (row["last_support_seq"] or 0))
            else:
                strength = {"pass": 1.0, "fail": 0.9, "discarded": 0.6}.get(row["outcome"], 0.5)
                runs_ago = max(0, current - (row["run_seq"] or current))
            fresh = max(0.1, 0.5 ** (runs_ago / 10))
            scored.append((round(relevance * strength * fresh, 6), row["id"], row, document))
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen, lessons, episodic = [], 0, 0
        for score, identifier, row, document in scored:
            if row["kind"] == "lesson" and lessons >= 3 or row["kind"] != "lesson" and episodic >= 3:
                continue
            if any(jaccard(document, other) >= 0.8 for _, _, _, other in chosen):
                continue
            chosen.append((score, identifier, row, document))
            lessons += row["kind"] == "lesson"
            episodic += row["kind"] != "lesson"
            if len(chosen) >= k:
                break
        return [{"id": identifier, "score": score} for score, identifier, _, _ in chosen]

    def render(self, ids, workspace: str | None = None) -> list[dict]:
        """Compact, dated records for a coordinator packet. Lessons whose scope no longer exists are dropped."""
        if not ids:
            return []
        root = Path(workspace) if workspace else None
        with self.connect() as db:
            current = self._current_seq(db)
            out = []
            for identifier in ids:
                row = db.execute("""SELECT n.*, r.run_seq, l.kind AS lesson_kind, l.status AS lesson_status, l.support, l.refute,
                    l.last_support_seq FROM nodes n LEFT JOIN runs r ON r.run_id=n.run_id LEFT JOIN lessons l ON l.node_id=n.id
                    WHERE n.id=?""", (identifier,)).fetchone()
                if row is None:
                    continue
                files, meta = json.loads(row["files"]), json.loads(row["meta"])
                if row["kind"] == "lesson":
                    if row["lesson_status"] not in ("active", "contested"):
                        continue
                    if root is not None and files and not any((root / PurePosixPath(f).parts[0]).exists() for f in files if PurePosixPath(f).parts):
                        continue
                    out.append({"id": identifier, "type": "lesson", "kind": row["lesson_kind"], "when": row["title"], "observed": row["body"],
                                "scope": files, "support": row["support"], "refute": row["refute"], "status": row["lesson_status"],
                                "runs_since_support": max(0, current - (row["last_support_seq"] or 0))})
                    continue
                record = {"id": identifier, "type": row["kind"], "title": row["title"], "outcome": row["outcome"],
                          "runs_ago": max(0, current - (row["run_seq"] or current))}
                if row["kind"] == "approach":
                    record.update({"files": files[:12], "failure_category": row["category"], "attempts": meta.get("attempts"),
                                   "provider": meta.get("provider"), "model": meta.get("model"), "directive": meta.get("directive"),
                                   "evidence": [dict(e) for e in db.execute("""SELECT n.title, n.body FROM edges e JOIN nodes n ON n.id=e.src
                                       WHERE e.dst=? AND e.rel IN ('supports','refutes') ORDER BY n.id LIMIT 4""", (identifier,))]})
                out.append({k: v for k, v in record.items() if v not in (None, [], "")})
        return out

    def expose(self, run_id: str, ids, via: str) -> None:
        with self.connect() as db:
            for identifier in ids:
                cursor = db.execute("INSERT OR IGNORE INTO exposures(run_id,node_id,via) VALUES(?,?,?)", (run_id, identifier, via))
                if cursor.rowcount and identifier.startswith("L-"):
                    db.execute("UPDATE lessons SET exposures_since_support=exposures_since_support+1 WHERE node_id=?", (identifier,))
                    db.execute("UPDATE lessons SET status='stale' WHERE node_id=? AND status='active' AND exposures_since_support>=?",
                               (identifier, STALE_AFTER))

    # Local correction surface -------------------------------------------------
    def lessons(self, query: str = "", status: str | None = None, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT n.id, n.title, n.body, n.files, l.kind, l.status, l.support, l.refute, l.distiller
                FROM lessons l JOIN nodes n ON n.id=l.node_id ORDER BY n.created DESC""").fetchall()
        words = set(tokenize(query))
        out = []
        for row in rows:
            if status and row["status"] != status:
                continue
            if words and not words & set(tokenize(f"{row['title']} {row['body']}")):
                continue
            out.append({"id": row["id"], "kind": row["kind"], "when": row["title"], "observed": row["body"], "scope": json.loads(row["files"]),
                        "status": row["status"], "support": row["support"], "refute": row["refute"], "distiller": row["distiller"]})
            if len(out) >= limit:
                break
        return out

    def counts(self) -> dict:
        with self.connect() as db:
            return {"runs": db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                    "nodes": db.execute("SELECT COUNT(*) FROM nodes WHERE kind!='lesson'").fetchone()[0],
                    "lessons": db.execute("SELECT COUNT(*) FROM lessons WHERE status IN ('active','contested')").fetchone()[0]}

    def set_status(self, identifier: str, status: str) -> None:
        if status not in ("active", "disabled"):
            raise ValueError("A lesson can be set to active or disabled")
        with self.connect() as db:
            if db.execute("UPDATE lessons SET status=? WHERE node_id=?", (status, identifier)).rowcount == 0:
                raise KeyError(identifier)

    def forget(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)


# Distillation ----------------------------------------------------------------

DISTILL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lessons"],
    "properties": {"lessons": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "when", "observed", "scope", "evidence", "confirms", "contradicts"],
        "properties": {
            "kind": {"type": "string", "enum": ["prefer", "avoid", "caution", "fact"]},
            "when": {"type": "string"}, "observed": {"type": "string"},
            "scope": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "confirms": {"type": "array", "items": {"type": "string"}},
            "contradicts": {"type": "array", "items": {"type": "string"}},
        }}}},
}
LESSON_KEYS = set(DISTILL_SCHEMA["properties"]["lessons"]["items"]["required"])
MAX_LESSONS_PER_RUN = 3
OPPOSITE = {"prefer": "avoid", "avoid": "prefer"}
HYGIENE = re.compile(
    r"https?://|`|\$\(|\bcurl\b|\bwget\b|\beval\b|[A-Za-z0-9+]{40,}={0,2}"
    r"|\b(?:ignore|skip|disable|bypass|turn off|don't run|do not run)\b.{0,40}\b(?:checks?|reviews?|instructions?|tests?|sandbox(?:es)?)\b",
    re.IGNORECASE)


SCOPE_SHAPE = re.compile(r"[A-Za-z0-9._@+/-]{1,200}")


def _safe_scope(path) -> bool:
    # A scope is a project path, never prose: no spaces or punctuation that could carry an instruction.
    if not isinstance(path, str) or not SCOPE_SHAPE.fullmatch(path):
        return False
    parts = PurePosixPath(path).parts
    return not PurePosixPath(path).is_absolute() and ".." not in parts and not any(p.startswith(".git") for p in parts)


def _overlaps(path, files) -> bool:
    path = path.rstrip("/")
    return any(f == path or f.startswith(path + "/") or path.startswith(f.rstrip("/") + "/") for f in files)


def _digest_hash(digest: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in digest.items() if k != "sha256"}, sort_keys=True).encode()).hexdigest()


class IdeaStore(GraphStore):
    """Project memory with post-run distillation of grounded lessons."""

    def digest(self, run_id: str) -> dict | None:
        """The distiller's whole input: this run's whitelisted facts plus related lessons it may confirm or contradict."""
        with self.connect() as db:
            run = db.execute("SELECT run_seq,status,distilled_sha256 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                return None
            nodes = db.execute("SELECT * FROM nodes WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            edges = db.execute("""SELECT e.src,e.rel,e.dst FROM edges e JOIN nodes n ON n.id=e.src WHERE n.run_id=?
                AND e.rel IN ('supports','refutes')""", (run_id,)).fetchall()
        goal = next((n for n in nodes if n["kind"] == "goal"), None)
        links = {}
        for src, rel, dst in edges:
            links.setdefault(src, []).append({"relation": rel, "approach": dst})
        approaches = [{"id": n["id"], "title": n["title"], "requirements": _clip(n["body"], 600), "outcome": n["outcome"],
                       "failure_category": n["category"], "files": json.loads(n["files"])[:20],
                       **{k: v for k, v in json.loads(n["meta"]).items() if k in ("attempts", "directive", "variant_of", "provider", "model")}}
                      for n in nodes if n["kind"] == "approach"]
        evidence = [{"id": n["id"], "title": n["title"], "detail": _clip(n["body"], 600), "outcome": n["outcome"],
                     "type": json.loads(n["meta"]).get("type"), "links": links.get(n["id"], [])}
                    for n in nodes if n["kind"] == "evidence"]
        files = sorted({f for a in approaches for f in a["files"]})
        text = " ".join([goal["title"] if goal else "", *(a["title"] for a in approaches)])
        related = [h["id"] for h in self.search(text, files, k=8) if h["id"].startswith("L-")]
        lessons = [r for r in self.render(related) if r.get("type") == "lesson"][:8]
        digest = {"goal": goal["body"] if goal else "", "outcome": run["status"], "approaches": approaches,
                  "evidence": evidence, "related_lessons": lessons}
        digest["sha256"] = _digest_hash(digest)
        return digest

    def distilled(self, run_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT distilled_sha256 FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return row[0] if row else None

    def apply_distillation(self, run_id: str, payload, digest: dict, distiller: str) -> dict:
        """Validate proposed lessons against the digest and fold them into memory. Never trusts the model's claims."""
        accepted, rejected = [], []
        lessons = payload.get("lessons") if isinstance(payload, dict) else None
        if not isinstance(lessons, list) or set(payload) - {"lessons"}:
            return {"accepted": [], "rejected": [{"index": None, "reason": "malformed"}]}
        approaches = {a["id"]: a for a in digest.get("approaches", [])}
        evidence = {e["id"]: e for e in digest.get("evidence", [])}
        shown = {l["id"] for l in digest.get("related_lessons", [])}
        with self.connect() as db:
            sequence = db.execute("SELECT run_seq FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if sequence is None:
                return {"accepted": [], "rejected": [{"index": None, "reason": "unknown_run"}]}
            sequence = sequence[0]
            exposed = {row[0] for row in db.execute("SELECT node_id FROM exposures WHERE run_id=?", (run_id,))}
            for index, lesson in enumerate(lessons):
                reason = self._invalid(index, lesson, approaches, evidence, shown)
                if reason:
                    rejected.append({"index": index, "reason": reason})
                    continue
                for identifier in lesson["confirms"]:
                    self._support(db, identifier, run_id, sequence, 0.5 if identifier in exposed else 1.0)
                for identifier in lesson["contradicts"]:
                    self._refute(db, identifier, run_id)
                existing = self._similar(db, lesson)
                if existing and existing["kind"] == lesson["kind"]:
                    self._support(db, existing["node_id"], run_id, sequence, 0.5 if existing["node_id"] in exposed else 1.0)
                    accepted.append(existing["node_id"])
                    continue
                identifier = self.node_id("lesson", None, lesson["kind"] + "|" + lesson["when"] + "|" + lesson["observed"])
                status = "active"
                if existing and OPPOSITE.get(lesson["kind"]) == existing["kind"]:
                    status = "contested"
                    db.execute("UPDATE lessons SET status='contested' WHERE node_id=? AND status='active'", (existing["node_id"],))
                self._node(db, identifier, None, "lesson", identifier, lesson["when"], lesson["observed"], lesson["scope"],
                                "model", None, None, {"evidence": lesson["evidence"], "run": run_id}, time.time())
                db.execute("""INSERT OR IGNORE INTO lessons(node_id,kind,status,support,refute,last_support_seq,exposures_since_support,distiller)
                    VALUES(?,?,?,1.0,0,?,0,?)""", (identifier, lesson["kind"], status, sequence, distiller))
                db.execute("INSERT OR IGNORE INTO lesson_runs(lesson_id,run_id,effect,weight) VALUES(?,?,?,1.0)", (identifier, run_id, "created"))
                for cited in lesson["evidence"]:
                    if cited in approaches or cited in evidence:
                        db.execute("INSERT OR IGNORE INTO edges(src,rel,dst) VALUES(?,?,?)", (identifier, "derived_from", cited))
                accepted.append(identifier)
            self._cap(db)
            db.execute("UPDATE runs SET distilled_sha256=? WHERE run_id=?", (digest.get("sha256"), run_id))
        return {"accepted": accepted, "rejected": rejected}

    @staticmethod
    def _invalid(index, lesson, approaches, evidence, shown) -> str | None:
        if index >= MAX_LESSONS_PER_RUN:
            return "too_many"
        if not isinstance(lesson, dict) or set(lesson) != LESSON_KEYS:
            return "unknown_keys"
        if lesson["kind"] not in ("prefer", "avoid", "caution", "fact"):
            return "kind"
        if not all(isinstance(lesson[k], str) for k in ("when", "observed")) or not all(
                isinstance(lesson[k], list) and all(isinstance(v, str) for v in lesson[k]) for k in ("scope", "evidence", "confirms", "contradicts")):
            return "types"
        if not lesson["when"].strip() or not lesson["observed"].strip() or len(lesson["when"]) > 160 or len(lesson["observed"]) > 300:
            return "length"
        if not lesson["evidence"] or any(e not in approaches and e not in evidence for e in lesson["evidence"]):
            return "evidence"
        if any(i not in shown for i in lesson["confirms"] + lesson["contradicts"]):
            return "unshown_lesson"
        cited_outcomes = [(approaches.get(e) or evidence.get(e) or {}).get("outcome") for e in lesson["evidence"]]
        if lesson["kind"] in ("avoid", "caution") and "fail" not in cited_outcomes:
            return "polarity"
        if lesson["kind"] == "prefer" and not any(evidence.get(e, {}).get("type") == "check" and evidence[e].get("outcome") == "pass"
                                                  for e in lesson["evidence"]):
            return "polarity"
        files = set()
        for cited in lesson["evidence"]:
            if cited in approaches:
                files.update(approaches[cited]["files"])
            for link in evidence.get(cited, {}).get("links", []):
                files.update(approaches.get(link["approach"], {}).get("files", []))
        if not lesson["scope"] or len(lesson["scope"]) > 8 or not all(_safe_scope(s) and _overlaps(s, files) for s in lesson["scope"]):
            return "scope"
        if HYGIENE.search(lesson["when"] + "\n" + lesson["observed"]) or any(HYGIENE.search(s) for s in lesson["scope"]):
            return "hygiene"
        return None

    def _similar(self, db, lesson):
        words = tokenize(lesson["when"] + " " + lesson["observed"])
        best = None
        for row in db.execute("""SELECT l.node_id,l.kind,n.title,n.body,n.files FROM lessons l JOIN nodes n ON n.id=l.node_id
                WHERE l.status IN ('active','contested','stale')"""):
            if not any(_overlaps(s, json.loads(row["files"])) or _overlaps(f, lesson["scope"]) for s in lesson["scope"] for f in json.loads(row["files"])):
                continue
            similarity = jaccard(words, tokenize(row["title"] + " " + row["body"]))
            if similarity >= 0.6 and (best is None or similarity > best[0]):
                best = (similarity, dict(row))
        return best[1] if best else None

    @staticmethod
    def _support(db, identifier, run_id, sequence, weight):
        if db.execute("INSERT OR IGNORE INTO lesson_runs(lesson_id,run_id,effect,weight) VALUES(?,?,?,?)",
                      (identifier, run_id, "confirm", weight)).rowcount:
            db.execute("""UPDATE lessons SET support=support+?, last_support_seq=?, exposures_since_support=0,
                status=CASE WHEN status='stale' THEN 'active' ELSE status END WHERE node_id=?""", (weight, sequence, identifier))

    @staticmethod
    def _refute(db, identifier, run_id):
        if db.execute("INSERT OR IGNORE INTO lesson_runs(lesson_id,run_id,effect,weight) VALUES(?,?,?,1.0)",
                      (identifier, run_id, "contradict")).rowcount:
            db.execute("UPDATE lessons SET refute=refute+1 WHERE node_id=?", (identifier,))
            db.execute("""UPDATE lessons SET status=CASE WHEN refute>=support+2 THEN 'superseded'
                WHEN refute>support THEN 'contested' ELSE status END WHERE node_id=? AND status IN ('active','contested','stale')""", (identifier,))

    @staticmethod
    def _cap(db):
        rows = db.execute("""SELECT node_id FROM lessons WHERE status IN ('active','contested')
            ORDER BY (support+1)/(support+refute+2) DESC, last_support_seq DESC, node_id LIMIT -1 OFFSET ?""", (MAX_ACTIVE_LESSONS,)).fetchall()
        for (identifier,) in rows:
            db.execute("UPDATE lessons SET status='superseded' WHERE node_id=?", (identifier,))

