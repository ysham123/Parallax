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
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .candidates import Candidates, digest
from .models import Participant, Limits, CheckSpec, RunSpec
from .store import now
from . import authority

FINISHED = {"applied", "rejected", "cancelled", "superseded"}
BUILTINS = (
    ("verified-change", "Verified change", "A focused change with independent review and project checks.", "Meet the requested outcome. Preserve existing behavior outside the requested scope."),
    ("fix-a-bug", "Fix a bug", "Reproduce the failure, fix its cause, and add a regression check.", "Reproduce the reported bug. Add a regression test that distinguishes the broken and corrected behavior. Fix the root cause."),
    ("safe-refactor", "Safe refactor", "Improve the structure while preserving observable behavior.", "Preserve observable behavior and public interfaces. Use existing checks and add focused coverage where behavior is not protected."),
    ("modernize-one-component", "Modernize one component", "Upgrade one legacy component while preserving its recorded behavior and interfaces.", "Modernize one explicitly scoped legacy component. Assess its current behavior and dependencies before editing. Record the owner-approved target, compatibility contract, required checks, allowed files and rollback boundary. Run baseline characterization checks and keep their evidence. Preserve external interfaces and business behavior unless a change is explicitly accepted. Keep supplied characterization and holdout expectations unchanged; do not weaken checks. Separate implementation from independent compatibility review, then verify the combined candidate in the required available environments. If dependencies, unknown behavior or a broad rewrite exceed the agreed component scope, stop and report the blocker. Deliver a small reviewable patch with remaining risks. Do not migrate production data, merge, deploy or claim whole-system equivalence."),
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


class WorkflowTaskSettings(BaseModel):
    """Task-local overrides; omitted values inherit the saved recipe or parent."""
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0"] = "1.0"
    instructions: str | None = Field(default=None, max_length=4000)
    checks: list[CheckSpec] | None = Field(default=None, max_length=64)

    @field_validator("checks", mode="before")
    @classmethod
    def strict_checks(cls, value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Task checks must be an array")
        return [CheckSpec.model_validate(check, strict=True) for check in value]


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    schema_version: Literal["1.0", "2.0"] = "1.0"
    github_binding: UUID | None = None
    parent_workflow_id: UUID | None = None
    template_id: str = Field(default="verified-change", pattern=r"^[a-z0-9-]{1,80}$")
    template_version: int = Field(default=1, ge=1)
    workspace: str = Field(min_length=1, max_length=4096)
    prompt: str = Field(min_length=1, max_length=12000)
    # Explicit selections become part of this execution's immutable settings.
    coordinator: Participant | None = None
    team: list[Participant] | None = Field(default=None, min_length=1, max_length=8)
    minutes: int | None = Field(default=None, ge=1, le=240)
    # Explicit only when changed from the recipe or parent, so older workers and request hashes are unaffected.
    coordinator_turns: int | None = Field(default=None, ge=2, le=60)
    task_settings: WorkflowTaskSettings | None = None

    @model_validator(mode="after")
    def versioned_task_settings(self):
        if self.task_settings is not None and self.schema_version != "2.0":
            raise ValueError("Task settings require versioned workflows; use schema_version 2.0")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "reject"]


class FindingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review: int = Field(ge=0)
    finding: int = Field(ge=0)


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    correction: str = Field(min_length=1, max_length=12000)
    findings: list[FindingSelection] = Field(default_factory=list, max_length=50)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "reject"] = "approve"

class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

class ReviewerAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=64)

class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)

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
                CREATE TABLE IF NOT EXISTS workflow_template_scope(id TEXT PRIMARY KEY, workspace TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_templates(id TEXT NOT NULL, version INTEGER NOT NULL,
                    body TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_operations(id TEXT PRIMARY KEY, workflow TEXT NOT NULL,
                    kind TEXT NOT NULL, actor TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_revisions(id TEXT PRIMARY KEY, lineage TEXT NOT NULL, parent TEXT NOT NULL);
            """)
            for identifier, name, description, instructions in BUILTINS:
                template = TemplateInput(name=name, description=description, instructions=instructions).model_dump()
                db.execute("INSERT OR IGNORE INTO workflow_templates VALUES(?,1,?,?)", (identifier,json.dumps(template),now()))

    def templates(self):
        self.install_shared_recipes()
        with self.store.connect() as db:
            rows = db.execute("SELECT id,version,body FROM workflow_templates t WHERE version=(SELECT MAX(version) FROM workflow_templates WHERE id=t.id) ORDER BY created,id").fetchall()
        return [{"id":r[0], "version":r[1], **json.loads(r[2]), "builtin":r[0] in {b[0] for b in BUILTINS}} for r in rows if self.template_allowed(r[0])]

    def install_shared_recipes(self):
        ctx=authority.context()
        if not ctx or not ctx.get("team"): return
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for recipe in ctx.get("recipes",[]):
                body=TemplateInput.model_validate({k:v for k,v in recipe.items() if k not in {"id","version"}})
                existing=db.execute("SELECT workspace FROM workflow_template_scope WHERE id=?",(recipe["id"],)).fetchone()
                if existing and existing[0]!=ctx["workspace"]: raise ValueError("Shared recipe scope mismatch")
                if not existing and db.execute("SELECT 1 FROM workflow_templates WHERE id=?", (recipe["id"],)).fetchone():
                    raise ValueError("Shared recipe identifier collides with an existing personal or built-in recipe")
                version=db.execute("SELECT body FROM workflow_templates WHERE id=? AND version=?", (recipe["id"],recipe["version"])).fetchone()
                if version and json.loads(version[0]) != body.model_dump():
                    raise ValueError("A saved shared recipe version cannot be changed")
                db.execute("INSERT OR IGNORE INTO workflow_template_scope VALUES(?,?)",(recipe["id"],ctx["workspace"]))
                db.execute("INSERT OR IGNORE INTO workflow_templates VALUES(?,?,?,?)",(recipe["id"],recipe["version"],json.dumps(body.model_dump()),now()))

    def template_allowed(self, identifier):
        if identifier in {b[0] for b in BUILTINS}: return True
        with self.store.connect() as db:
            row=db.execute("SELECT workspace FROM workflow_template_scope WHERE id=?",(identifier,)).fetchone()
        ctx=authority.context()
        return bool(ctx and ctx.get("team") and row and row[0]==ctx["workspace"]) if ctx and ctx.get("team") else row is None

    def template(self, identifier, version):
        self.install_shared_recipes()
        if not self.template_allowed(identifier): raise KeyError(identifier)
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM workflow_templates WHERE id=? AND version=?", (identifier,version)).fetchone()
        if not row:
            raise KeyError(identifier)
        return {"id":identifier,"version":version, **json.loads(row[0])}

    def save_template(self, body: TemplateInput, identifier=None):
        authority.require_role("owner", "developer")
        if (authority.context() or {}).get("team"): raise ValueError("Save shared recipes through the workspace relay")
        if identifier and not self.template_allowed(identifier): raise KeyError(identifier)
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

    def get(self, identifier, *, internal=False):
        with self.store.connect() as db:
            row = db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        value = json.loads(row[0])
        if not internal: authority.require_scope(value)
        return value

    def save(self, value):
        value["updated_at"] = now()
        with self.store.connect() as db:
            db.execute("UPDATE workflows SET body=?,updated=? WHERE id=?", (json.dumps(value),value["updated_at"],value["id"]))

    def listing(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT body FROM workflows ORDER BY updated DESC LIMIT 10000").fetchall()
        result = []
        for row in rows:
            value = json.loads(row[0])
            try:
                authority.require_scope(value)
                self.check_workspace(value["spec"]["workspace"])
            except (ValueError, KeyError, HTTPException):
                continue
            result.append(self.public(value, brief=True))
            if len(result) == 100: break
        return result

    def public(self, value, *, brief=False):
        out = {key:value.get(key) for key in ("id", "title", "status", "stage", "created_at", "updated_at", "run_id", "error", "candidate", "decision", "timeline")}
        out["parent_workflow_id"] = value.get("parent_workflow_id")
        for key in ("schema_version", "revision", "superseded_by", "requester", "reviewer", "delivery", "approval", "comments", "github_target", "publication", "required_worker_features"):
            out[key] = value.get(key)
        out["template"] = {key:value["template"][key] for key in ("id", "version", "name")}
        out["workspace"] = value["spec"]["workspace"]
        if value.get("publication_operation"): out["publication_operation"] = value["publication_operation"]
        if value.get("run_id"):
            run = self.store.get(value["run_id"])
            out["run_status"] = run["status"]
            out["runtime_seconds"] = run["artifacts"].get("runtime_seconds", 0)
            out["summary"] = run["summary"]
        if brief:
            out.pop("timeline", None)
            out.pop("candidate", None)
            out["comment_count"] = len(value.get("comments") or [])
            out.pop("comments", None)
        else:
            out["spec"] = value["spec"]
            out["prompt"] = value["prompt"]
            out["original_goal"] = value.get("original_goal", value["prompt"])
            out["task_settings"] = self._task_settings(value)
            out["template_details"] = {key:value["template"].get(key, "")
                for key in ("id", "version", "name", "description", "instructions")}
        return out

    def _task_settings(self, value):
        # Legacy records kept requirements on the recipe and checks on the spec.
        # Return a copy so callers cannot mutate the saved recipe or execution.
        settings = value.get("task_settings") or {"schema_version":"1.0",
            "instructions":value["template"]["instructions"], "checks":value["spec"]["checks"]}
        return WorkflowTaskSettings.model_validate(settings).model_dump()

    def _followup_prompt(self, parent, request, instructions):
        # Keep the root request separate from composed execution prompts so a
        # follow-up chain never recursively copies its entire history.
        original_goal = parent.get("original_goal", parent["prompt"])
        if len(original_goal) > 12000:
            raise ValueError("The original goal is too long for a follow-up. Start a new task.")
        summary = "No completed result was recorded."
        if parent.get("run_id"):
            run = self.store.get(parent["run_id"])
            summary = run.get("summary") or summary
        if len(summary) > 2000:
            summary = summary[:2000] + "\n[Prior result truncated to 2,000 characters.]"
        prompt = (
            "This is a new task linked to earlier work. Start from the current project. "
            "Candidate code from the prior task is not reused. Changes already applied "
            "to the project are part of the current project. Independently build, review, "
            "and verify a new candidate for this request.\n\n"
            "Original goal:\n" + original_goal +
            "\n\nPrior task status: " + parent["status"] +
            "\nPrior result (context only; inspect the current project):\n" + summary +
            "\n\nNew request:\n" + request.prompt +
            "\n\nWorkflow requirements:\n" + instructions
        )
        return prompt, original_goal

    def _stage(self, identifier, stage, status=None, **changes):
        value = self.get(identifier, internal=True)
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
        graph.add_conditional_edges("approval", lambda state: "apply" if self.get(state["workflow_id"]).get("decision", {}).get("action") == "approve" and self.get(state["workflow_id"]).get("schema_version", "1.0") != "2.0" else END)
        graph.add_edge("apply", END)
        self.graph = graph.compile(checkpointer=saver)

    async def start(self, request: WorkflowStart):
        async with self.lock:
            authority.require_role("owner", "developer")
            identifier = str(request.request_id)
            request.workspace = str(Path(request.workspace).expanduser().resolve())
            self.check_workspace(request.workspace)
            if not request.prompt.strip():
                raise ValueError("Describe the outcome you want")
            parent = None
            if request.parent_workflow_id:
                parent = self.get(str(request.parent_workflow_id))
                # Authorize before reading the parent's recipe, prompt, run, or
                # result, including on retries of an existing child request.
                self.check_workspace(parent["spec"]["workspace"])
                if Path(parent["spec"]["workspace"]).expanduser().resolve() != Path(request.workspace):
                    raise ValueError("A follow-up must use the same project as its parent task")
            # Preserve old root request hashes and ignore recipe selectors that
            # have no meaning when the immutable parent settings are inherited.
            ignored = {"template_id", "template_version"} if parent else {"parent_workflow_id"}
            if request.schema_version == "1.0": ignored.add("schema_version")
            if request.github_binding is None: ignored.add("github_binding")
            if request.task_settings is None: ignored.add("task_settings")
            if request.coordinator_turns is None: ignored.add("coordinator_turns")
            request_hash = digest(request.model_dump(mode="json", exclude=ignored))
            try:
                existing = self.get(identifier)
                self.check_workspace(existing["spec"]["workspace"])
                if existing["request_hash"] != request_hash:
                    raise ValueError("This start request was already used with different inputs")
                if existing.get("schema_version") == "2.0" and existing.get("requester") != authority.actor():
                    raise ValueError("This start request belongs to another actor")
                return self.public(existing)
            except KeyError:
                pass
            # A new task counts against the plan; the retry above never does.
            await self.engine.license.ensure_can_start("build")
            if parent:
                template = parent["template"]
                spec = RunSpec.model_validate(parent["spec"]).model_copy(deep=True)
                spec.workspace = request.workspace
                settings = self._task_settings(parent)
                spec.mode, spec.integrate = "build", False
                if request.coordinator is not None:
                    spec.coordinator = request.coordinator
                if request.team is not None:
                    spec.team = request.team
            else:
                template = self.template(request.template_id, request.template_version)
                original_goal = request.prompt
                settings = {"schema_version":"1.0", "instructions":template["instructions"], "checks":template["checks"]}
                spec = RunSpec(workspace=request.workspace, prompt=request.prompt,
                    coordinator=request.coordinator or template["coordinator"], team=request.team or template["team"],
                    limits=template["limits"], checks=template["checks"], mode="build", integrate=False)
                # A saved project profile scopes assessment to the folder's packages (for example
                # one workspace of a monorepo); the roots become part of this task's fixed settings.
                spec.package_roots = self.store.project_roots(request.workspace)
            if request.task_settings:
                for key in ("instructions", "checks"):
                    override = getattr(request.task_settings, key)
                    if override is not None:
                        settings[key] = [check.model_dump() for check in override] if key == "checks" else override
            settings = WorkflowTaskSettings.model_validate(settings).model_dump()
            spec.checks = [CheckSpec.model_validate(check) for check in settings["checks"]]
            if parent:
                spec.prompt, original_goal = self._followup_prompt(parent, request, settings["instructions"])
            else:
                spec.prompt = request.prompt.strip()+"\n\nWorkflow requirements:\n"+settings["instructions"]
            if request.minutes:
                spec.limits.minutes = request.minutes
            if request.coordinator_turns:
                spec.limits.coordinator_turns = request.coordinator_turns
            await self.engine.validate_settings(spec)
            value = {"id":identifier, "request_hash":request_hash, "title":request.prompt.strip()[:160], "prompt":request.prompt,
                "parent_workflow_id":str(request.parent_workflow_id) if request.parent_workflow_id else None,
                "original_goal":original_goal,
                "template":template, "task_settings":settings, "spec":spec.model_dump(), "status":"queued", "stage":"queued",
                "required_worker_features":["workflow-task-settings-v1"] if request.task_settings is not None or (parent or {}).get("required_worker_features") else [],
                "created_at":now(), "updated_at":now(), "timeline":[], "error":"",
                "schema_version":"2.0" if (authority.context() or {}).get("team") else request.schema_version,
                "authority":authority.context(), "github_target":(authority.context() or {}).get("github_target"), "requester":authority.actor(), "delivery":{"local":"pending", "github":"pending"}}
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()
                if row:
                    existing = json.loads(row[0])
                    authority.require_scope(existing)
                    if existing["request_hash"] != request_hash:
                        raise ValueError("This start request was already used with different inputs")
                    if existing.get("schema_version") == "2.0" and existing.get("requester") != authority.actor():
                        raise ValueError("This start request belongs to another actor")
                    return self.public(existing)
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

    async def revise(self, identifier, request: RevisionRequest):
        async with self.lock:
            authority.require_role("owner", "developer")
            parent = self.get(identifier)
            self.check_workspace(parent["spec"]["workspace"])
            request_hash = digest({"parent":identifier, **request.model_dump(mode="json")})
            child_id = str(request.request_id)
            try:
                existing = self.get(child_id)
            except KeyError:
                existing = None
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError("This revision request was already used with different inputs")
                if existing.get("requester") != authority.actor():
                    raise ValueError("This revision request belongs to another actor")
                return self.public(existing)
            await self.engine.license.ensure_can_start("build")
            if not request.correction.strip() or parent.get("candidate", {}).get("digest") != request.candidate_digest:
                raise ValueError("Refresh the candidate and describe the correction")
            if parent["status"] not in {"awaiting_approval", "rejected", "superseded", "approved", "published"} or identifier in self.jobs:
                raise ValueError("Wait for an unapplied saved candidate before revising")
            if parent.get("delivery", {}).get("github") == "publishing":
                raise ValueError("Reconcile the pending publication before revising")
            candidate = await self.candidates.capture(parent["run_id"])
            if candidate["digest"] != request.candidate_digest:
                raise ValueError("The original project or candidate changed. Start a new task from the current project.")
            run = self.store.get(parent["run_id"])
            selected = []
            for selection in request.findings:
                try:
                    finding = run["reviews"][selection.review]["findings"][selection.finding]
                except (IndexError, KeyError, TypeError):
                    raise ValueError("A selected review finding no longer exists") from None
                selected.append(finding)
            spec = RunSpec.model_validate(parent["spec"]).model_copy(deep=True)
            settings = self._task_settings(parent)
            original_goal = parent.get("original_goal", parent["prompt"])
            acceptance = self.engine._integration_requirements(run, spec)
            spec.prompt = ("Revise the saved candidate. Preserve the original acceptance criteria and required checks.\n\n"
                "Original goal:\n" + original_goal + "\n\nAcceptance criteria:\n" + json.dumps(acceptance) +
                "\n\nWorkflow requirements:\n" + settings["instructions"] +
                "\n\nRequested correction:\n" + request.correction + "\n\nSelected findings (including locations):\n" + json.dumps(selected))
            spec.integrate = False
            await self.engine.validate_settings(spec)
            lineage = (parent.get("revision") or {}).get("lineage", identifier)
            value = {"id":child_id, "request_hash":request_hash, "schema_version":"2.0", "title":request.correction.strip()[:160],
                "prompt":request.correction, "original_goal":original_goal, "parent_workflow_id":identifier,
                "template":parent["template"], "task_settings":settings, "spec":spec.model_dump(), "status":"queued", "stage":"queued",
                "required_worker_features":parent.get("required_worker_features", []),
                "created_at":now(), "updated_at":now(), "timeline":[], "error":"",
                "revision":{"lineage":lineage, "parent":identifier, "parent_digest":request.candidate_digest,
                    "findings":selected, "acceptance":acceptance},
                "authority":authority.context(), "github_target":parent.get("github_target"), "parent_publication":parent.get("publication") or parent.get("parent_publication"), "requester":authority.actor(), "delivery":{"local":"pending", "github":"pending"},
                "candidate_seed":{"run_id":parent["run_id"], "digest":candidate["digest"], "source":candidate["identity"]["source"]}}
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT body FROM workflows WHERE id=?", (child_id,)).fetchone()
                if row:
                    existing = json.loads(row[0])
                    authority.require_scope(existing)
                    if existing["request_hash"] != request_hash:
                        raise ValueError("This revision request was already used with different inputs")
                    if existing.get("requester") != authority.actor():
                        raise ValueError("This revision request belongs to another actor")
                    return self.public(existing)
                self._check_capacity(db)
                # A second runtime may have reserved delivery while the candidate
                # was inspected. Re-read under the durable write lock before
                # superseding the saved parent or replacing its latest comments.
                parent = json.loads(db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()[0])
                if parent.get("delivery", {}).get("github") == "publishing":
                    raise ValueError("Reconcile the pending publication before revising")
                if parent["status"] not in {"awaiting_approval", "rejected", "superseded", "approved", "published"}:
                    raise ValueError("Wait for an unapplied saved candidate before revising")
                # The selected saved parent is being superseded atomically here;
                # only another live candidate or execution blocks its correction.
                rows = db.execute("SELECT w.body FROM workflow_revisions r JOIN workflows w ON r.id=w.id WHERE r.lineage=? AND r.id<>?", (lineage,identifier))
                if any(json.loads(row[0])["status"] not in FINISHED | {"published"} for row in rows):
                    raise ValueError("A revision in this lineage is already active")
                if db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= 10000:
                    raise ValueError("Workflow history limit reached")
                parent.update(status="superseded", stage="superseded", superseded_by=child_id)
                db.execute("INSERT INTO workflows VALUES(?,?,?)", (child_id,json.dumps(value),now()))
                db.execute("INSERT INTO workflow_revisions VALUES(?,?,?)", (child_id,lineage,identifier))
                db.execute("UPDATE workflows SET body=?,updated=? WHERE id=?", (json.dumps(parent),now(),identifier))
            await self._launch(child_id)
            return self.public(self.get(child_id))

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
        run = await self.engine.start(RunSpec.model_validate(value["spec"]), request_key=identifier+":build", candidate_seed=value.get("candidate_seed"), authorization={**(value.get("authority") or {}), **({"github_target":value["github_target"]} if value.get("github_target") else {})} or None)
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
        elif value.get("schema_version") == "2.0":
            self._stage(value["id"], "approved", "approved")
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

    async def decide(self, identifier, decision: Decision, *, operation=None):
        async with self.lock:
            value = self.get(identifier)
            self.check_workspace(value["spec"]["workspace"])
            if value.get("schema_version") == "2.0" and not operation:
                raise ValueError("Use the versioned approval operation for this workflow")
            if operation and (value.get("authority") or {}).get("team"):
                if authority.actor() == value["requester"]:
                    raise ValueError("Team approval requires a different human, including for owners")
                if value.get("reviewer") and value["reviewer"] != authority.actor():
                    raise ValueError("This candidate is assigned to another reviewer")
            if value.get("decision"):
                if any(value["decision"][k] != v for k,v in decision.model_dump().items()):
                    raise ValueError("A different decision was already recorded")
                if value["status"] in {"awaiting_approval", "interrupted", "needs_attention"}:
                    # Approval may have become durable just before graph launch
                    # was interrupted. Retry resumes that same decision and never
                    # creates a new provider budget or application identity.
                    await self._launch(identifier, decision=True)
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
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                value = json.loads(db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()[0])
                # Candidate inspection awaits a project lock. Another runtime can
                # supersede or assign this candidate while that inspection runs.
                if operation and (value.get("authority") or {}).get("team"):
                    if authority.actor() == value["requester"]:
                        raise ValueError("Team approval requires a different human, including for owners")
                    if value.get("reviewer") and value["reviewer"] != authority.actor():
                        raise ValueError("This candidate is assigned to another reviewer")
                if value.get("decision"):
                    if any(value["decision"][k] != v for k,v in decision.model_dump().items()):
                        raise ValueError("A different decision was already recorded")
                else:
                    if value["status"] != "awaiting_approval" or value.get("superseded_by"):
                        raise ValueError("This workflow is not ready for approval yet")
                    value["decision"] = {"id":operation or str(uuid4()), "actor":authority.actor(), "at":now(), **decision.model_dump()}
                    value["approval"] = value["decision"]
                    value["updated_at"] = now()
                    db.execute("UPDATE workflows SET body=?,updated=? WHERE id=?", (json.dumps(value), value["updated_at"], identifier))
            await self._launch(identifier, decision=True)
            return self.public(self.get(identifier))

    def operation(self, identifier, kind, request):
        value = self.get(identifier)
        self.check_workspace(value["spec"]["workspace"])
        payload = {"workflow":identifier,"kind":kind,"actor":authority.actor(),"request":request.model_dump(mode="json")}
        fingerprint = digest(payload)
        key = str(request.request_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM workflow_operations WHERE id=?", (key,)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint: raise ValueError("Operation request ID was reused with different inputs")
                return dict(row)
            db.execute("INSERT INTO workflow_operations VALUES(?,?,?,?,?,'pending',?)", (key,identifier,kind,authority.actor(),fingerprint,json.dumps(payload)))
        return {"id":key,"state":"pending"}

    def complete_operation(self, key, result):
        with self.store.connect() as db:
            db.execute("UPDATE workflow_operations SET state='completed',body=? WHERE id=?", (json.dumps(result),key))

    async def approve(self, identifier, request: ApprovalRequest):
        op = self.operation(identifier, "approval", request)
        value = self.get(identifier)
        if op["state"] == "completed" and value["status"] not in {"awaiting_approval", "interrupted", "needs_attention"}:
            return self.public(value)
        result = await self.decide(identifier, Decision(action=request.action,candidate_digest=request.candidate_digest),operation=op["id"])
        self.complete_operation(op["id"], result)
        return result

    async def apply_candidate(self, identifier, request: DeliveryRequest):
        authority.require_role("owner", "developer")
        async with self.lock:
            op = self.operation(identifier, "apply", request)
            value = self.get(identifier)
            if op["state"] == "completed": return self.public(value)
            if value["status"] not in {"approved", "applying", "interrupted", "needs_attention", "applied"} or value.get("approval", {}).get("action") != "approve":
                raise ValueError("Approve this candidate before choosing local application")
            if request.candidate_digest != value.get("approval", {}).get("candidate_digest"):
                raise ValueError("Delivery must bind to the approved candidate digest")
            if value.get("superseded_by"): raise ValueError("This candidate was superseded")
            self._stage(identifier,"applying","applying")
            try:
                await self.candidates.apply(value["run_id"],request.candidate_digest,op["id"])
            except Exception as exc:
                self._stage(identifier,"needs_attention","needs_attention",error=str(exc)[:2000])
                raise
            value = self.get(identifier)
            value["delivery"]["local"] = "applied"
            self.save(value)
            self._stage(identifier,"applied","applied")
            result = self.public(self.get(identifier))
            self.complete_operation(op["id"],result)
            return result

    def assign(self, identifier, reviewer):
        authority.require_role("owner", "developer")
        value = self.get(identifier)
        self.check_workspace(value["spec"]["workspace"])
        ctx = authority.context() or {}
        if ctx.get("team") and reviewer not in ctx.get("reviewers_by_project", {}).get(value["spec"]["workspace"], []):
            raise ValueError("Assign a current workspace member with access to this project")
        if ctx.get("team") and reviewer == value["requester"]: raise ValueError("Assign another human")
        if value.get("decision"): raise ValueError("Approval was already recorded")
        value["reviewer"] = reviewer
        self.save(value)
        return self.public(value)

    def comment(self, identifier, request):
        op = self.operation(identifier,"comment",request)
        value = self.get(identifier)
        if op["state"] != "completed" and not any(c["id"] == op["id"] for c in value.get("comments", [])):
            if len(value.get("comments", [])) >= 200: raise ValueError("Review comment limit reached for this task")
            value.setdefault("comments", []).append({"id":op["id"],"actor":authority.actor(),"message":request.message,"at":now()})
            self.save(value)
        if op["state"] != "completed":
            self.complete_operation(op["id"],{})
        return self.public(value)

    async def publication_preview(self, identifier, request: DeliveryRequest):
        authority.require_role("owner", "developer")
        value = self.get(identifier)
        self.check_workspace(value["spec"]["workspace"])
        if value["status"] not in {"approved", "published"} or value.get("approval",{}).get("candidate_digest") != request.candidate_digest:
            raise ValueError("Fresh human approval is required before publication")
        target = value.get("github_target")
        if not target: raise ValueError("This task uses local delivery. Start a GitHub task from a clean captured remote baseline")
        candidate = await self.candidates.capture(value["run_id"])
        if candidate["digest"] != request.candidate_digest: raise ValueError("Approved candidate changed")
        run = self.store.get(value["run_id"])
        manager = self.candidates.manager(run)
        parent = value.get("parent_publication")
        previous = None
        if parent:
            original = self.get(parent["request"]["workflow"])
            previous = self.candidates.manager(self.store.get(original["run_id"])).prepare()["integration_commit"]
        package = await self.engine._workspace_call(self.candidates.publication_tree, manager, target, previous)
        return {**package,"workflow":identifier,"digest":request.candidate_digest,"binding":target["id"],
            "branch":parent["branch"] if parent else "parallax/"+identifier,
            "parent_head":parent["commit"] if parent else None}

    async def begin_publication(self, identifier, request: DeliveryRequest):
        authority.require_role("owner", "developer")
        async with self.lock:
            op = self.operation(identifier, "publication", request)
            value = self.get(identifier)
            pending = value.get("publication_operation")
            if pending and pending != op["id"]:
                raise ValueError("Retry the saved publication operation before starting another")
            if op["state"] == "completed":
                return json.loads(op["body"])
            package = await self.publication_preview(identifier, request)
            # Reserve delivery and save the exact managed bundle in one commit.
            # A crash cannot leave a reservation whose bundle was never saved.
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                value = json.loads(db.execute("SELECT body FROM workflows WHERE id=?", (identifier,)).fetchone()[0])
                pending = value.get("publication_operation")
                if pending and pending != op["id"]:
                    raise ValueError("Retry the saved publication operation before starting another")
                if value.get("superseded_by") or value["status"] not in {"approved", "published"}:
                    raise ValueError("Fresh human approval is required before publication")
                value["publication_operation"] = op["id"]
                value["delivery"]["github"] = "publishing"
                value["updated_at"] = now()
                db.execute("UPDATE workflows SET body=?,updated=? WHERE id=?", (json.dumps(value), value["updated_at"], identifier))
                db.execute("UPDATE workflow_operations SET state='completed',body=? WHERE id=?", (json.dumps(package), op["id"]))
            return package

    def record_publication(self, identifier, value):
        workflow = self.get(identifier)
        self.check_workspace(workflow["spec"]["workspace"])
        if workflow.get("approval",{}).get("candidate_digest") != value["request"]["candidate_digest"]:
            raise ValueError("Publication receipt does not match approved candidate")
        if workflow.get("publication_operation") != value["request"]["request_id"] or workflow.get("superseded_by"):
            raise ValueError("Publication receipt does not match the reserved delivery operation")
        workflow["publication"] = value
        workflow["delivery"]["github"] = "published"
        self.save(workflow)
        self._stage(identifier,"published","published")
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
            if value["status"] not in FINISHED | {"awaiting_approval", "approved", "published", "needs_attention", "interrupted"} or (value["status"] == "awaiting_approval" and value.get("decision")):
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
