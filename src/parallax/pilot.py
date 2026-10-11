"""Local, scoped pilot evidence; participant reports never become acceptance gates."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import authority
from .candidates import digest
from .evidence import MANAGED_SCHEME
from .recovery import CATEGORIES, classify
from .store import now

PILOT_FEATURES = ["pilot-evaluation-v1", "pilot-observations-v1"]
SHA256 = r"^[a-f0-9]{64}$"


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProviderMeasurement(Measurement):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    model: str | None = Field(default=None, max_length=120)
    effort: str | None = Field(default=None, max_length=40)
    transport: Literal["cli", "api"] | None = None


class UsageMeasurement(Measurement):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    input_tokens: int | None = Field(default=None, ge=0, le=10**12)
    output_tokens: int | None = Field(default=None, ge=0, le=10**12)
    total_tokens: int | None = Field(default=None, ge=0, le=10**12)
    cost_usd: float | None = Field(default=None, ge=0, le=10000)


class EvaluationBudget(Measurement):
    minutes: int | None = Field(default=None, ge=1, le=240)
    attempt_seconds: int | None = Field(default=None, ge=10, le=3600)
    repairs: int | None = Field(default=None, ge=0, le=5)
    workers: int | None = Field(default=None, ge=1, le=8)


class EvaluationInput(Measurement):
    schema_version: Literal["1.0"] = "1.0"
    comparison_id: UUID
    order: Literal["first", "second"]
    outcome: Literal["accepted", "rejected", "failed", "timed_out", "cancelled", "blocked"]
    active_human_seconds: float | None = Field(default=None, ge=0, le=86400)
    setup_seconds: float | None = Field(default=None, ge=0, le=86400)
    review_seconds: float | None = Field(default=None, ge=0, le=86400)
    observed_baseline_sha256: str | None = Field(default=None, pattern=SHA256)
    observed_baseline_scheme: Literal["managed-workspace-state-v1", "readonly-workspace-state-v1", "git-tree-v1"] | None = None
    assessment_method: Literal["participant_report", "independent_assessment", "behavioral_holdout"] = "participant_report"
    providers: list[ProviderMeasurement] = Field(default_factory=list, max_length=9)
    budget: EvaluationBudget | None = None
    provider_usage: list[UsageMeasurement] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def human_time_total(self):
        if self.active_human_seconds is not None and sum(value or 0 for value in (self.setup_seconds, self.review_seconds)) > self.active_human_seconds:
            raise ValueError("Total active human time includes setup and review; recorded phases cannot exceed it")
        return self


class BenchmarkInput(Measurement):
    request_id: UUID
    workflow_id: UUID
    approach: Literal["parallax", "single_agent", "fresh_same_provider", "fresh_cross_provider", "worktree_script", "close_product"]
    duration_seconds: float | None = Field(ge=0, le=86400)
    interventions: int | None = Field(ge=0, le=10000)
    accepted: bool
    provider_cost_usd: float | None = Field(default=None, ge=0, le=10000)
    evaluation: EvaluationInput | None = None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.evaluation is None:
            if self.approach not in {"parallax", "single_agent"}:
                raise ValueError("Additional comparison approaches require a versioned evaluation")
            if self.duration_seconds is None or self.interventions is None:
                raise ValueError("Legacy comparisons require duration and interventions; use a versioned evaluation for unknown measurements")
        elif self.accepted != (self.evaluation.outcome == "accepted"):
            raise ValueError("Acceptance must agree with the reported evaluation outcome")
        return self


class ObservationInput(Measurement):
    request_id: UUID
    workflow_id: UUID
    observation_id: UUID
    content_sha256: str = Field(pattern=SHA256)
    classification: Literal["confirmed_defect", "false_alarm", "unresolved", "escape"]
    finding_index: int | None = Field(default=None, ge=0, le=49)
    comment: str = Field(default="", max_length=4000)


class Pilot:
    def __init__(self, workflows):
        self.workflows = workflows
        self.store = workflows.store
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pilot_setup(workspace TEXT NOT NULL, actor TEXT NOT NULL, ready_at TEXT NOT NULL, PRIMARY KEY(workspace,actor));
                CREATE TABLE IF NOT EXISTS pilot_benchmarks(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, actor TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pilot_measurements(workspace TEXT NOT NULL, actor TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(workspace,actor,id));
                CREATE TABLE IF NOT EXISTS pilot_observations(workspace TEXT NOT NULL, actor TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(workspace,actor,id));
                INSERT OR IGNORE INTO pilot_measurements SELECT workspace,actor,id,body FROM pilot_benchmarks;
            ''')

    @staticmethod
    def scope():
        return (authority.context() or {}).get("workspace", "local")

    def setup(self, project, assessment):
        if assessment["status"] != "ready":
            return
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO pilot_setup VALUES(?,?,?)", (self.scope(), authority.actor(), now()))

    def _workflow(self, identifier):
        value = self.workflows.get(str(identifier))
        caller = authority.context()
        saved = value.get("authority")
        if caller and saved and caller.get("workspace") != saved.get("workspace"):
            raise KeyError(str(identifier))
        self.workflows.check_workspace(value["spec"]["workspace"])
        return value

    def _comparison_context(self, value):
        # A fresh task's parent is context, not revision lineage. Only explicit
        # saved-candidate revisions inherit the root baseline and contract.
        root_id = (value.get("revision") or {}).get("lineage", value["id"])
        root = self._workflow(root_id) if root_id != value["id"] else value
        run = self.store.get(root["run_id"]) if root.get("run_id") else {}
        artifacts = run.get("artifacts", {})
        goal = root.get("original_goal", root.get("prompt", ""))
        checks = artifacts.get("required_checks", root["spec"].get("checks", []))
        settings = self.workflows._task_settings(root)
        spec = root["spec"]
        providers = [{key: item.get(key) for key in ("provider", "model", "effort", "transport", "role")}
                     for item in [spec.get("coordinator", {}), *spec.get("team", [])] if item.get("provider")]
        return {"root_workflow_id":root_id, "baseline_sha256":artifacts.get("baseline_snapshot_sha256"),
                "baseline_scheme":MANAGED_SCHEME, "contract_sha256":digest({"goal":goal,"checks":checks,"settings":settings}),
                "recipe":{key:root.get("template", {}).get(key) for key in ("id", "version")},
                "task_settings_sha256":digest(settings), "providers":providers, "limits":spec.get("limits", {}),
                "acceptance":goal, "required_checks":checks}

    def _record(self, table, request, body):
        # Request IDs belong to the authenticated workspace and actor. A shared
        # UUID neither reveals nor aliases another account's measurements.
        payload = request.model_dump(mode="json")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"SELECT body FROM {table} WHERE workspace=? AND actor=? AND id=?",
                             (self.scope(), authority.actor(), str(request.request_id))).fetchone()
            if row:
                saved = json.loads(row[0])
                if {key:saved.get(key) for key in payload} != payload:
                    raise ValueError("Pilot request ID was reused with different inputs")
                return saved
            db.execute(f"INSERT INTO {table} VALUES(?,?,?,?)", (self.scope(), authority.actor(), str(request.request_id), json.dumps(body)))
        return body

    def benchmark(self, request):
        authority.require_role("owner", "developer")
        value = self._workflow(request.workflow_id)
        comparison = self._comparison_context(value)
        observed = request.evaluation.observed_baseline_sha256 if request.evaluation else None
        scheme = request.evaluation.observed_baseline_scheme if request.evaluation else None
        baseline = comparison["baseline_sha256"]
        baseline_match = "unverified" if observed is None or baseline is None or scheme is None else "matched" if observed == baseline and scheme == comparison["baseline_scheme"] else "mismatch"
        body = {**request.model_dump(mode="json"), "acceptance":comparison["acceptance"], "required_checks":comparison["required_checks"],
                "comparison_context":comparison, "comparability":{"baseline":baseline_match,"source":"participant_reported",
                "actual_execution_verified":False}, "actor":authority.actor(), "observer":authority.actor(), "at":now(), "measurement_source":"participant_reported",
                "cost_status":"observed" if request.provider_cost_usd is not None else "unknown"}
        return self._record("pilot_measurements", request, body)

    def observation(self, request):
        authority.require_role("owner", "developer", "reviewer")
        value = self._workflow(request.workflow_id)
        if not value.get("run_id"):
            raise ValueError("This task has no recorded execution evidence to label")
        evidence = self.store.observation(value["run_id"], str(request.observation_id), request.content_sha256)
        if request.finding_index is not None:
            findings = evidence["evidence"].get("findings")
            if evidence["kind"] != "review" or not isinstance(findings, list) or request.finding_index >= len(findings):
                raise ValueError("The selected finding does not exist in this recorded review")
        body = {"schema_version":"1.0", **request.model_dump(mode="json"), "run_id":value["run_id"], "kind":evidence["kind"],
                "actor":authority.actor(), "at":now(), "source":"human_label", "affects_acceptance":False}
        return self._record("pilot_observations", request, body)

    def _interventions(self, run_id):
        if not run_id:
            return 0
        with self.store.connect() as db:
            # Recovery-generated steering and its linked recovery record describe
            # one request. Historical unlinked records remain activity counts.
            return db.execute("""SELECT COUNT(*) FROM events e WHERE e.run_id=?
                AND e.kind IN ('steering','steer','steer_requested','pause_requested','recovery_requested')
                AND NOT (e.kind='recovery_requested' AND EXISTS (
                    SELECT 1 FROM events s WHERE s.run_id=e.run_id AND s.kind='steering'
                    AND s.sequence=json_extract(e.data,'$.steering_sequence')))""", (run_id,)).fetchone()[0]

    def _lineages(self, rows):
        """All retained, currently authorized members of each visible lineage.

        This is separate from the latest-100 list. Revisions outside that list
        must not disappear from cumulative runtime or provider consumption.
        Missing runtime is an incomplete total, never silently a measured zero.
        """
        output = []
        with self.store.connect() as db:
            managed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_revisions'").fetchone()
        if not managed:
            return output
        for root in dict.fromkeys(row["root_workflow"] for row in rows):
            with self.store.connect() as db:
                identifiers = [root, *[row[0] for row in db.execute("SELECT id FROM workflow_revisions WHERE lineage=? ORDER BY rowid", (root,))]]
            members, usage, runtime, missing, interventions = [], [], 0, False, 0
            complete_scope = True
            for identifier in dict.fromkeys(identifiers):
                try:
                    value = self._workflow(identifier)
                except (ValueError, KeyError, HTTPException):
                    complete_scope = False
                    continue
                run = self.store.get(value["run_id"]) if value.get("run_id") else {}
                duration = run.get("artifacts", {}).get("runtime_seconds")
                if duration is None:
                    missing = True
                else:
                    runtime += duration
                members.append({"workflow":identifier, "status":value["status"], "execution_seconds":duration})
                usage.extend({key:item[key] for key in ("provider", "input_tokens", "output_tokens", "total_tokens", "cost_usd") if key in item}
                             for item in run.get("usage", {}).get("reports", []))
                activity = self._interventions(value.get("run_id"))
                interventions += int(bool(value.get("revision")))+len(value.get("comments", []))+activity
            output.append({"root_workflow":root, "members":members, "workflow_count":len(members), "scope":"all retained currently authorized lineage members",
                           "complete_scope":complete_scope, "execution_seconds":None if missing or not complete_scope else runtime,
                           "observed_execution_seconds":runtime, "execution_time_complete":not missing and complete_scope,
                           "interventions":interventions, "provider_usage":usage, "provider_cost_usd":None, "cost_status":"unknown"})
        return output

    def _evidence(self, identifiers):
        """Readable, capped journal anchors, including interrupted observations."""
        output, warnings, truncated = [], [], False
        for identifier in sorted(identifiers):
            value = self._workflow(identifier)
            if not value.get("run_id"):
                continue
            try:
                journal = self.store.observations(value["run_id"])
            except (KeyError, ValueError):
                warnings.append({"workflow_id":identifier,"code":"invalid_observation_journal"})
                continue
            truncated = truncated or len(journal) > 100
            for item in journal[-100:]:
                if len(output) >= 1000:
                    return output, warnings, True
                evidence, metadata = item["evidence"], item["observation"]
                def short(key, maximum):
                    text = evidence.get(key)
                    return text[:maximum] if isinstance(text, str) else None
                summary = short("summary", 800) if item["kind"] == "review" else short("error", 160)
                findings = []
                if item["kind"] == "review" and isinstance(evidence.get("findings"), list):
                    for index, finding in enumerate(evidence["findings"][:50]):
                        if isinstance(finding, str):
                            findings.append({"index":index,"title":finding[:160],"summary":finding[:800],"code_location":None})
                        elif isinstance(finding, dict):
                            title, body = finding.get("title"), finding.get("body")
                            findings.append({"index":index,"title":title[:160] if isinstance(title,str) else None,
                                             "summary":body[:800] if isinstance(body,str) else None,"code_location":finding.get("code_location")})
                        else:
                            findings.append({"index":index,"title":None,"summary":None,"code_location":None})
                output.append({"workflow_id":identifier,"run_id":value["run_id"],"kind":item["kind"],
                               "name":short("name", 120),"provider":short("provider", 80),"phase":metadata.get("phase"),
                               "outcome":"passed" if evidence.get("ok") is True else "failed" if evidence.get("ok") is False else "unknown",
                               "summary":summary,"findings":findings,"observation":metadata,"legacy":item["legacy"]})
        return output, warnings, truncated

    def report(self):
        rows = []
        for brief in self.workflows.listing():
            try:
                value = self._workflow(brief["id"])
            except (KeyError, ValueError, HTTPException):
                continue
            run = self.store.get(value["run_id"]) if value.get("run_id") else None
            interventions = self._interventions(run["run_id"]) if run else 0
            approval_seconds = None
            if (value.get("decision") or {}).get("action") == "approve" and value.get("candidate"):
                approval_seconds = max(0, (datetime.fromisoformat(value["decision"]["at"])-datetime.fromisoformat(value["candidate"]["captured_at"])).total_seconds())
            usage = [{key:item[key] for key in ("provider", "input_tokens", "output_tokens", "total_tokens", "cost_usd") if key in item}
                     for item in (run or {}).get("usage", {}).get("reports", [])]
            failures = Counter(item.get("category") if item.get("category") in CATEGORIES else classify(str(item.get("message", "")))
                               for item in (run or {}).get("errors", []))
            rows.append({"workflow":value["id"], "status":value["status"], "requester":value.get("requester"), "revision":bool(value.get("revision")),
                "root_workflow":(value.get("revision") or {}).get("lineage", value["id"]), "created_at":value.get("created_at"),
                "interventions":int(bool(value.get("revision")))+len(value.get("comments", []))+interventions,
                "execution_seconds":(run or {}).get("artifacts", {}).get("runtime_seconds"), "approval_seconds":approval_seconds,
                "local_delivery":value.get("delivery", {}).get("local", "legacy"), "publication":value.get("delivery", {}).get("github", "pending"),
                "checks_passed":sum(c["ok"] for c in (run or {}).get("checks", [])), "checks_total":len((run or {}).get("checks", [])),
                "failure_categories":dict(failures), "provider_usage":usage, "provider_cost_usd":None, "cost_status":"unknown"})
        with self.store.connect() as db:
            setup = [dict(row) for row in db.execute("SELECT actor,ready_at FROM pilot_setup WHERE workspace=?", (self.scope(),))]
            benchmarks = [json.loads(row[0]) for row in db.execute("SELECT body FROM pilot_measurements WHERE workspace=?", (self.scope(),))]
            observations = [json.loads(row[0]) for row in db.execute("SELECT body FROM pilot_observations WHERE workspace=?", (self.scope(),))]
        ids = {row["workflow"] for row in rows}
        groups = {}
        delivered = {row["root_workflow"] for row in rows if row["local_delivery"] == "applied" or row["publication"] == "published"}
        for row in rows:
            if row["revision"] or not row["requester"]:
                continue
            group = groups.setdefault(row["requester"], {"actor":row["requester"], "root_tasks":0, "delivered_root_tasks":0})
            group["root_tasks"] += 1
            group["delivered_root_tasks"] += int(row["workflow"] in delivered)
        for group in groups.values():
            group["later_tasks"] = max(0, group["root_tasks"]-1)
        lineages = self._lineages(rows)
        related_ids = ids | {member["workflow"] for lineage in lineages for member in lineage["members"]}
        evidence, evidence_warnings, evidence_truncated = self._evidence(related_ids)
        return {"schema_version":"1.1", "features":PILOT_FEATURES, "scope":"selected worker, latest 100 authorized workflows",
                "evidence_scope":"visible tasks and all retained currently authorized members of their revision lineages",
                "setup":setup, "outcomes":rows, "benchmarks":[b for b in benchmarks if b["workflow_id"] in related_ids],
                "observations":[o for o in observations if o["workflow_id"] in related_ids],
                "lineages":lineages,
                "evidence_observations":evidence,"evidence_warnings":evidence_warnings,"evidence_observations_truncated":evidence_truncated,
                "evidence_observation_limit":{"per_workflow":100,"total":1000},
                "repeat_use":{"actors":list(groups.values()), "voluntary_return":"not measured", "includes_revisions":False},
                "pricing":"manual agreement before enrollment", "launch_status":"requires live acceptance"}
