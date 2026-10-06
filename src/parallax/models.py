"""Versioned shared contracts for CLI, MCP, Studio and the team engine."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

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

class RunSpec(Contract):
    schema_version: Literal["1.0"] = "1.0"
    workspace: str
    prompt: str = Field(min_length=1, max_length=200000)
    mode: Literal["review", "build", "compare"] = "build"
    coordinator: Participant = Field(default_factory=lambda: Participant(provider="codex"))
    team: list[Participant] = Field(default_factory=lambda: [Participant(provider="claude"), Participant(provider="grok", role="reviewer"), Participant(provider="antigravity")])
    limits: Limits = Field(default_factory=Limits)
    checks: list[CheckSpec] = Field(default_factory=list)
    profile: str = "Quality first"
    integrate: bool = True

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
    schema_version: Literal["1.0"] = "1.0"
    sequence: int
    run_id: str
    timestamp: str
    kind: str
    task_id: str | None = None
    data: dict = Field(default_factory=dict)

class RunResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
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
