"""Saved product workflows. LangGraph coordinates; Engine owns coding effects."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal, TypedDict
from uuid import UUID, uuid4

import aiosqlite
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langsmith import tracing_context
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import set_config_context
from pydantic import BaseModel, ConfigDict, Field

from .candidates import Candidates, digest
from .models import Participant, Limits, CheckSpec, RunSpec
from .store import now

FINISHED = {"applied", "rejected", "cancelled"}
BUILTINS = (
    ("verified-change", "Verified change", "A focused change with independent review and project checks.", "Meet the requested outcome. Preserve existing behavior outside the requested scope."),
    ("fix-a-bug", "Fix a bug", "Reproduce the failure, fix its cause, and add a regression check.", "Reproduce the reported bug. Add a regression test that distinguishes the broken and corrected behavior. Fix the root cause."),
    ("safe-refactor", "Safe refactor", "Improve the structure while preserving observable behavior.", "Preserve observable behavior and public interfaces. Use existing checks and add focused coverage where behavior is not protected."),
)


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    instructions: str = Field(default="", max_length=4000)
    coordinator: Participant = Field(default_factory=lambda: Participant(provider="codex"))
    team: list[Participant] = Field(default_factory=lambda: [Participant(provider="claude")], min_length=1, max_length=8)
    limits: Limits = Field(default_factory=Limits)
    checks: list[CheckSpec] = Field(default_factory=list, max_length=64)


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    template_id: str = Field(default="verified-change", pattern=r"^[a-z0-9-]{1,80}$")
    template_version: int = Field(default=1, ge=1)
    workspace: str = Field(min_length=1, max_length=4096)
    prompt: str = Field(min_length=1, max_length=12000)
    # Explicit selections become part of this execution's immutable settings.
    coordinator: Participant | None = None
    team: list[Participant] | None = Field(default=None, min_length=1, max_length=8)
    minutes: int | None = Field(default=None, ge=1, le=240)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "reject"]


class GraphState(TypedDict):
    workflow_id: str


class Workflows:
    def __init__(self, engine, check_workspace):
        self.engine, self.store, self.check_workspace = engine, engine.store, check_workspace
        self.candidates = Candidates(engine)
        self.jobs = {}
        self.lock = asyncio.Lock()
        self.graph = self.connection = None
        self.closing = False
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_templates(id TEXT NOT NULL, version INTEGER NOT NULL,
                    body TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
            """)
            for identifier, name, description, instructions in BUILTINS:
                template = TemplateInput(name=name, description=description, instructions=instructions).model_dump()
                db.execute("INSERT OR IGNORE INTO workflow_templates VALUES(?,1,?,?)", (identifier,json.dumps(template),now()))

    def templates(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,version,body FROM workflow_templates t WHERE version=(SELECT MAX(version) FROM workflow_templates WHERE id=t.id) ORDER BY created,id").fetchall()
        return [{"id":r[0], "version":r[1], **json.loads(r[2]), "builtin":r[0] in {b[0] for b in BUILTINS}} for r in rows]

    def template(self, identifier, version):
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM workflow_templates WHERE id=? AND version=?", (identifier,version)).fetchone()
        if not row:
            raise KeyError(identifier)
        return {"id":identifier,"version":version, **json.loads(row[0])}

    def save_template(self, body: TemplateInput, identifier=None):
        if identifier in {b[0] for b in BUILTINS}:
            raise ValueError("Save a personal copy of a built-in recipe")
        identifier = identifier or str(uuid4())
        UUID(identifier)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM workflow_templates").fetchone()[0] >= 1000:
                raise ValueError("Saved recipe limit reached")
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM workflow_templates WHERE id=?", (identifier,)).fetchone()[0]
            db.execute("INSERT INTO workflow_templates VALUES(?,?,?,?)", (identifier,version,json.dumps(body.model_dump()),now()))
        return self.template(identifier, version)

    def get(self, identifier):
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        return json.loads(row[0])

    def save(self, value):
        value["updated_at"] = now()
        with self.store.connect() as db:
            db.execute("UPDATE workflows SET body=?,updated=? WHERE id=?", (json.dumps(value),value["updated_at"],value["id"]))

    def listing(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT body FROM workflows ORDER BY updated DESC LIMIT 100").fetchall()
        result = []
        for row in rows:
            value = json.loads(row[0])
            try:
                self.check_workspace(value["spec"]["workspace"])
            except ValueError:
                continue
            result.append(self.public(value, brief=True))
        return result

    def public(self, value, *, brief=False):
        out = {key:value.get(key) for key in ("id", "title", "status", "stage", "created_at", "updated_at", "run_id", "error", "candidate", "decision", "timeline")}
        out["template"] = {key:value["template"][key] for key in ("id", "version", "name")}
        out["workspace"] = value["spec"]["workspace"]
        if value.get("run_id"):
            run = self.store.get(value["run_id"])
            out["run_status"] = run["status"]
            out["runtime_seconds"] = run["artifacts"].get("runtime_seconds", 0)
            out["summary"] = run["summary"]
        if brief:
            out.pop("timeline", None)
            out.pop("candidate", None)
        else:
            out["spec"] = value["spec"]
            out["prompt"] = value["prompt"]
        return out

    def _stage(self, identifier, stage, status=None, **changes):
        value = self.get(identifier)
        if value["status"] in FINISHED:
            return value
        if stage != value["stage"]:
            value["timeline"].append({"stage":stage, "at":now()})
        value.update(stage=stage, status=status or stage, **changes)
        self.save(value)
        return value

    def _check_capacity(self, db, identifier=None):
        active = {row[0] for row in db.execute("SELECT id,body FROM workflows")
            if json.loads(row[1])["status"] in {"queued", "preparing", "applying"}}
        active.update(self.jobs)
        active.discard(identifier)
        if len(active) >= 3:
            raise ValueError("Three workflows are already running. Finish or cancel one first.")

    async def _ensure_graph(self):
        if self.graph:
            return
        path = self.store.home / "workflows.sqlite3"
        self.connection = await aiosqlite.connect(path)
        path.chmod(0o600)
        saver = AsyncSqliteSaver(self.connection, serde=JsonPlusSerializer(pickle_fallback=False,
            allowed_json_modules=[], allowed_msgpack_modules=[]))
        graph = StateGraph(GraphState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("approval", self._approval)
        graph.add_node("apply", self._apply)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "approval")
        graph.add_conditional_edges("approval", lambda state: "apply" if self.get(state["workflow_id"]).get("decision", {}).get("action") == "approve" else END)
        graph.add_edge("apply", END)
        self.graph = graph.compile(checkpointer=saver)

    async def start(self, request: WorkflowStart):
        async with self.lock:
            identifier = str(request.request_id)
            request.workspace = str(Path(request.workspace).expanduser().resolve())
            self.check_workspace(request.workspace)
            request_hash = digest(request.model_dump(mode="json"))
            try:
                existing = self.get(identifier)
                if existing["request_hash"] != request_hash:
                    raise ValueError("This start request was already used with different inputs")
                return self.public(existing)
            except KeyError:
                pass
            template = self.template(request.template_id, request.template_version)
            spec = RunSpec(workspace=request.workspace, prompt=request.prompt.strip()+"\n\nWorkflow requirements:\n"+template["instructions"],
                coordinator=request.coordinator or template["coordinator"], team=request.team or template["team"],
                limits=template["limits"], checks=template["checks"], mode="build", integrate=False)
            if not request.prompt.strip():
                raise ValueError("Describe the outcome you want")
            if request.minutes:
                spec.limits.minutes = request.minutes
            await self.engine.validate_settings(spec)
            value = {"id":identifier, "request_hash":request_hash, "title":request.prompt.strip()[:160], "prompt":request.prompt,
                "template":template, "spec":spec.model_dump(), "status":"queued", "stage":"queued",
                "created_at":now(), "updated_at":now(), "timeline":[], "error":""}
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= 10000:
                    raise ValueError("Workflow history limit reached")
                self._check_capacity(db)
                db.execute("INSERT INTO workflows VALUES(?,?,?)", (identifier,json.dumps(value),now()))
            await self._launch(identifier)
            return self.public(self.get(identifier))

    async def _launch(self, identifier, *, decision=False):
        if identifier in self.jobs:
            return
        await self._ensure_graph()
        task = asyncio.create_task(self._drive(identifier, decision=decision))
        self.jobs[identifier] = task
        task.add_done_callback(lambda done: self.jobs.pop(identifier, None))

    async def _drive(self, identifier, *, decision=False):
        config = {"configurable":{"thread_id":identifier}, "recursion_limit":12}
        try:
            state = await self.graph.aget_state(config)
            if decision:
                payload = Command(resume={"decision_id":self.get(identifier)["decision"]["id"]}) if state.interrupts else None
            else:
                payload = None if state.values else {"workflow_id":identifier}
            # Global LangSmith environment settings must not opt a local coding project into telemetry.
            with tracing_context(enabled=False):
                await self.graph.ainvoke(payload, config)
        except asyncio.CancelledError:
            if self.closing:
                self._stage(identifier, "interrupted", "interrupted")
            raise
        except Exception as exc:
            self._stage(identifier, "needs_attention", "needs_attention", error=str(exc)[:2000])

    async def _prepare(self, state):
        identifier = state["workflow_id"]
        value = self._stage(identifier, "preparing", error="")
        self.check_workspace(value["spec"]["workspace"])
        if value["status"] in FINISHED:
            raise ValueError("This workflow has ended")
        run = await self.engine.start(RunSpec.model_validate(value["spec"]), request_key=identifier+":build")
        value = self.get(identifier)
        value["run_id"] = run["run_id"]
        resume_requested = value.pop("resume_requested", False)
        self.save(value)
        if resume_requested and run["status"] in {"paused", "interrupted", "needs_attention"} and run["run_id"] not in self.engine.jobs:
            self.engine.control(run["run_id"], "resume")
        job = self.engine.jobs.get(run["run_id"])
        if job:
            await asyncio.shield(job)
        run = self.store.get(run["run_id"])
        if self.get(identifier)["status"] in FINISHED:
            raise ValueError("This workflow has ended")
        if run["status"] != "completed":
            reason = next((e.get("message") for e in reversed(run["errors"]) if e.get("message")), "The run stopped before verification completed.")
            raise ValueError(reason)
        candidate = await self.candidates.capture(run["run_id"])
        self._stage(identifier, "approval", "awaiting_approval", candidate=candidate)
        return state

    def _approval(self, state, config: RunnableConfig):
        # Python 3.10 cannot propagate async task context automatically. Bind the
        # node's injected configuration explicitly for interrupt(), without globals.
        value = self.get(state["workflow_id"])
        with set_config_context(config) as context:
            answer = context.run(interrupt, {"workflow_id":value["id"], "candidate_digest":value["candidate"]["digest"]})
        value = self.get(value["id"])
        decision = value.get("decision")
        if not decision or not isinstance(answer, dict) or answer.get("decision_id") != decision["id"]:
            raise ValueError("Approval was not recorded by an authorized request")
        if decision["action"] == "reject":
            self._stage(value["id"], "rejected", "rejected")
        return state

    async def _apply(self, state):
        value = self.get(state["workflow_id"])
        if value["status"] in FINISHED:
            return state
        self.check_workspace(value["spec"]["workspace"])
        decision = value.get("decision", {})
        if decision.get("action") != "approve":
            raise ValueError("An explicit approval is required")
        self._stage(value["id"], "applying", "applying", error="")
        await self.candidates.apply(value["run_id"], decision["candidate_digest"], decision["id"])
        self._stage(value["id"], "applied", "applied")
        return state

    async def decide(self, identifier, decision: Decision):
        async with self.lock:
            value = self.get(identifier)
            self.check_workspace(value["spec"]["workspace"])
            if value.get("decision"):
                if any(value["decision"][k] != v for k,v in decision.model_dump().items()):
                    raise ValueError("A different decision was already recorded")
                return self.public(value)
            if value["status"] != "awaiting_approval" or identifier in self.jobs:
                raise ValueError("This workflow is not ready for approval yet")
            if value["candidate"]["digest"] != decision.candidate_digest:
                raise ValueError("Refresh the candidate before deciding")
            if decision.action == "approve":
                with self.store.connect() as db:
                    self._check_capacity(db, identifier)
                current = await self.candidates.capture(value["run_id"])
                if current["digest"] != decision.candidate_digest:
                    raise ValueError("Candidate changed. Prepare a new workflow.")
            value["decision"] = {"id":str(uuid4()), "at":now(), **decision.model_dump()}
            self.save(value)
            await self._launch(identifier, decision=True)
            return self.public(self.get(identifier))

    async def resume(self, identifier):
        async with self.lock:
            value = self.get(identifier)
            self.check_workspace(value["spec"]["workspace"])
            if value["status"] in FINISHED or identifier in self.jobs:
                raise ValueError("This workflow cannot resume")
            if value["status"] == "awaiting_approval" and not value.get("decision"):
                return self.public(value)
            with self.store.connect() as db:
                self._check_capacity(db, identifier)
            if value.get("run_id") and not value.get("decision"):
                run = self.store.get(value["run_id"])
                if run["status"] not in {"completed", "paused", "interrupted", "needs_attention"}:
                    raise ValueError("Inspect the run and start a new workflow")
            self._stage(identifier, "resuming", "preparing", error="", resume_requested=True)
            await self._launch(identifier, decision=bool(value.get("decision")))
            return self.public(self.get(identifier))

    async def cancel(self, identifier):
        async with self.lock:
            value = self.get(identifier)
            self.check_workspace(value["spec"]["workspace"])
            if value["status"] in FINISHED:
                return self.public(value)
            if value["status"] == "applying" or value.get("decision", {}).get("action") == "approve":
                raise ValueError("An approved application must finish or reconcile before it can stop")
            self._stage(identifier, "cancelled", "cancelled")
            if value.get("run_id") and self.store.get(value["run_id"])["status"] != "completed":
                self.engine.control(value["run_id"], "cancel")
            task = self.jobs.get(identifier)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return self.public(self.get(identifier))

    async def recover(self):
        # Waiting approvals are already durable. Restart alone never authorizes new provider calls.
        with self.store.connect() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT body FROM workflows")]
        for value in values:
            if value["status"] not in FINISHED | {"awaiting_approval", "needs_attention", "interrupted"} or (value["status"] == "awaiting_approval" and value.get("decision")):
                self._stage(value["id"], "interrupted", "interrupted", error="Worker restarted. Resume to reconcile saved work.")

    async def close(self):
        self.closing = True
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if self.connection:
            await self.connection.close()
        self.graph = self.connection = None
