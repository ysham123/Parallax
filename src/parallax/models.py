"""Versioned shared contracts for CLI, MCP, Studio and the team engine."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Provider = str

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Participant(Contract):
    provider: Provider = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    transport: Literal["cli", "api"] = "cli"
    connection_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model: str | None = None
    effort: str | None = "high"
    role: Literal["implementer", "reviewer", "generalist"] = "generalist"

class Limits(Contract):
    workers: int = Field(default=3, ge=1, le=8)
    repairs: int = Field(default=2, ge=0, le=5)
    minutes: int = Field(default=45, ge=1, le=240)
    attempt_seconds: int = Field(default=600, ge=10, le=3600)
    coordinator_turns: int = Field(default=20, ge=2, le=60)

class CheckSpec(Contract):
    name: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    timeout: int = Field(default=120, ge=1, le=1800)
    cwd: str = "."

    @field_validator("cwd")
    @classmethod
    def relative_root(cls, value):
        from pathlib import PurePosixPath
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or any(p.startswith(".git") or p.startswith(".parallax") for p in path.parts) or "\\" in value or "\x00" in value:
            raise ValueError("Package roots must be relative project directories")
        return str(path)

class ProjectProfile(Contract):
    schema_version: Literal["1.1"] = "1.1"
    workspace: str
    package_roots: list[str] = Field(default_factory=list, max_length=32)
    checks: list[CheckSpec] = Field(default_factory=list, max_length=64)

    @field_validator("package_roots")
    @classmethod
    def safe_roots(cls, values):
        return list(dict.fromkeys(CheckSpec.relative_root(value) for value in values))

class ProjectAssessment(Contract):
    schema_version: Literal["1.1"] = "1.1"
    workspace: str
    assessed_at: str
    git: bool
    status: Literal["ready", "needs_configuration", "blocked"]
    packages: list[dict] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    proposed_checks: list[CheckSpec] = Field(default_factory=list)
    execution: dict = Field(default_factory=dict)
    providers: list[dict] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)

class CheckEvidence(Contract):
    schema_version: Literal["1.1"] = "1.1"
    name: str
    argv: list[str]
    cwd: str = "."
    phase: Literal["baseline", "final", "alternative"] = "final"
    ok: bool
    exit_code: int | None = None
    output: str = ""
    elapsed_seconds: float = 0
    error: str | None = None
    task_id: str | None = None
    environment: dict = Field(default_factory=dict)

class RunSpec(Contract):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    workspace: str
    prompt: str = Field(min_length=1, max_length=200000)
    mode: Literal["review", "build", "compare"] = "build"
    coordinator: Participant = Field(default_factory=lambda: Participant(provider="codex"))
    team: list[Participant] = Field(default_factory=lambda: [Participant(provider="claude"), Participant(provider="grok", role="reviewer"), Participant(provider="antigravity")])
    limits: Limits = Field(default_factory=Limits)
    checks: list[CheckSpec] = Field(default_factory=list)
    profile: str = "Quality first"
    integrate: bool = True
    package_roots: list[str] = Field(default_factory=list, max_length=32)
    _safe_roots = field_validator("package_roots")(ProjectProfile.safe_roots.__func__)

class TaskSpec(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=1)
    provider: Provider = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    prompt: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)

class CoordinatorAction(Contract):
    id: str = Field(min_length=1)
    action: Literal["plan", "dispatch", "inspect_results", "validate", "resolve_task", "request_integration", "finish"]
    summary: str = ""
    tasks: list[TaskSpec] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    checks: list[CheckSpec] = Field(default_factory=list)
    selected_task: str | None = None

class RunEvent(Contract):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    sequence: int
    run_id: str
    timestamp: str
    kind: str
    task_id: str | None = None
    data: dict = Field(default_factory=dict)

class RunResult(Contract):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    run_id: str
    status: str
    spec: RunSpec
    summary: str = ""
    tasks: list[dict] = Field(default_factory=list)
    sessions: list[dict] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    diff: str = ""
    reviews: list[dict] = Field(default_factory=list)
    checks: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
    artifacts: dict = Field(default_factory=dict)
