"""Scoped human measurements and immutable labels cannot authorize delivery."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from parallax import authority
from parallax.executors import encode, permitted
from parallax.evidence import phase_attempt, record_observation
from parallax.pilot import BenchmarkInput, Pilot, PILOT_FEATURES
from parallax.server import create_app
from parallax.store import Store
from test_accounts import HostedFixture, ORIGIN, user
from test_server import Registry


class PilotEvaluationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name) / "project"
        self.project.mkdir()
        self.project = self.project.resolve()
        self.store = Store(Path(folder.name) / "state")
        self.app = create_app(self.store, Registry(), token="private-token",
                              workspace=str(self.project), allowed_workspaces=[self.project])
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization":"Bearer private-token"}
        self.pilot = Pilot(self.app.state.workflows)
        self.value = self.seed()

    def seed(self, *, revision=None, requester="local", status="failed", path=None, authority_context=None):
        identifier, run_id = str(uuid4()), str(uuid4())
        spec = {"workspace":str(path or self.project), "prompt":"Preserve parser compatibility",
                "checks":[{"name":"compatibility","argv":["python3","acceptance.py"],"timeout":120,"cwd":"."}],
                "coordinator":{"provider":"codex","model":"writer-model","effort":"high","transport":"cli"},
                "team":[{"provider":"claude","model":"review-model","role":"reviewer","transport":"cli"}],
                "limits":{"minutes":30,"repairs":2,"workers":2,"attempt_seconds":300}}
        value = {"id":identifier,"run_id":run_id,"status":status,"requester":requester,"spec":spec,
                 "prompt":spec["prompt"],"original_goal":spec["prompt"],"template":{"id":"fixture","version":3,"name":"Fixture","instructions":"Preserve public behavior"},
                 "created_at":"2026-10-11T12:00:00+00:00","updated_at":"2026-10-11T12:00:00+00:00",
                 "comments":[],"delivery":{"local":"pending","github":"pending"}}
        if revision:
            value["revision"] = {"lineage":revision,"parent":revision}
        if authority_context:
            value["authority"] = authority_context
        run = {"run_id":run_id,"status":status,"spec":spec,"summary":"","checks":[],"reviews":[],
               "artifacts":{"baseline_snapshot_sha256":"a"*64,"runtime_seconds":10},
               "errors":[{"category":"interrupted","message":"Provider attempt interrupted"}],
               "usage":{"reports":[{"provider":"claude","input_tokens":10}]}}
        self.store.save(run)
        self.save_workflow(value)
        if revision:
            with self.store.connect() as db:
                db.execute("INSERT INTO workflow_revisions VALUES(?,?,?)", (identifier,revision,revision))
        return value

    def save_workflow(self, value):
        with self.store.connect() as db:
            db.execute("INSERT INTO workflows VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (value["id"],json.dumps(value),value["updated_at"]))

    def benchmark_body(self, **changes):
        body = {"request_id":str(uuid4()),"workflow_id":self.value["id"],"approach":"single_agent",
                "duration_seconds":20,"interventions":2,"accepted":False}
        body.update(changes)
        return body

    def evaluation(self, **changes):
        value = {"schema_version":"1.0","comparison_id":str(uuid4()),"order":"first","outcome":"failed"}
        value.update(changes)
        return value

    def label_body(self, value=None):
        value = value or self.value
        self.store.event(value["run_id"], "review", {"provider":"claude","task_id":"integration","ok":False,"findings":["Compatibility regression"],"error":None})
        evidence = self.store.observations(value["run_id"])[0]
        return {"request_id":str(uuid4()),"workflow_id":value["id"],"observation_id":evidence["observation"]["id"],
                "content_sha256":evidence["observation"]["content_sha256"],"classification":"confirmed_defect","comment":"Reproduced with independent input."}

    def test_legacy_request_still_saves_and_retries_immutably(self):
        body = self.benchmark_body()
        first = self.client.post("/api/pilot/benchmark", json=body, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()
        self.assertEqual(saved["acceptance"], self.value["original_goal"])
        self.assertEqual(saved["required_checks"], self.value["spec"]["checks"])
        self.assertEqual(self.client.post("/api/pilot/benchmark",json=body,headers=self.headers).json(),saved)
        changed = {**body,"interventions":3}
        self.assertEqual(self.client.post("/api/pilot/benchmark",json=changed,headers=self.headers).status_code,400)

    def test_existing_legacy_records_migrate_without_losing_retry_identity(self):
        request = BenchmarkInput(**self.benchmark_body())
        old = {**request.model_dump(mode="json"), "acceptance":self.value["original_goal"],
               "required_checks":self.value["spec"]["checks"],"actor":"local","at":"2026-10-10T00:00:00+00:00"}
        old.pop("evaluation")
        with self.store.connect() as db:
            db.execute("INSERT INTO pilot_benchmarks VALUES(?,?,?,?)",(str(request.request_id),"local","local",json.dumps(old)))
        restored = Pilot(self.app.state.workflows)
        self.assertEqual(restored.benchmark(request),old)

    def test_unknown_measurements_are_null_only_for_versioned_inputs(self):
        body = self.benchmark_body(duration_seconds=None,interventions=None,evaluation=self.evaluation(active_human_seconds=None,setup_seconds=0))
        response = self.client.post("/api/pilot/benchmark",json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        saved = response.json()
        self.assertIsNone(saved["duration_seconds"])
        self.assertIsNone(saved["evaluation"]["active_human_seconds"])
        self.assertEqual(saved["evaluation"]["setup_seconds"],0)
        self.assertEqual(saved["cost_status"],"unknown")
        body.pop("evaluation")
        self.assertEqual(self.client.post("/api/pilot/benchmark",json=body,headers=self.headers).status_code,422)

    def test_nonfinite_out_of_bounds_and_contradictory_reports_rejected(self):
        base = self.benchmark_body(evaluation=self.evaluation())
        bad = [
            {**base,"accepted":True},
            {**base,"duration_seconds":float("nan")},
            {**base,"evaluation":self.evaluation(active_human_seconds=float("inf"))},
            {**base,"evaluation":self.evaluation(review_seconds=-1)},
            {**base,"evaluation":self.evaluation(active_human_seconds=10,setup_seconds=8,review_seconds=3)},
            {**base,"evaluation":self.evaluation(providers=[{"provider":"codex","api_key":"never-accepted"}])},
            {**base,"evaluation":self.evaluation(budget={"workers":9})},
        ]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                BenchmarkInput(**body)
        extra = self.benchmark_body(approach="fresh_same_provider")
        with self.assertRaises(ValidationError):
            BenchmarkInput(**extra)
        extra["evaluation"] = self.evaluation()
        self.assertEqual(BenchmarkInput(**extra).approach,"fresh_same_provider")

    def test_comparability_requires_explicit_compatible_scheme_and_stays_reported(self):
        for scheme, observed, expected in (
            (None,"a"*64,"unverified"),("managed-workspace-state-v1","a"*64,"matched"),
            ("managed-workspace-state-v1","b"*64,"mismatch"),("readonly-workspace-state-v1","a"*64,"mismatch")):
            request = BenchmarkInput(**self.benchmark_body(evaluation=self.evaluation(observed_baseline_sha256=observed,observed_baseline_scheme=scheme)))
            saved = self.pilot.benchmark(request)
            self.assertEqual(saved["comparability"]["baseline"],expected)
            self.assertFalse(saved["comparability"]["actual_execution_verified"])
            self.assertEqual(saved["measurement_source"],"participant_reported")
            self.assertEqual(saved["observer"],"local")
        run = self.store.get(self.value["run_id"])
        run["artifacts"].pop("baseline_snapshot_sha256")
        self.store.save(run)
        request = BenchmarkInput(**self.benchmark_body(evaluation=self.evaluation(observed_baseline_sha256="a"*64,observed_baseline_scheme="managed-workspace-state-v1")))
        self.assertEqual(self.pilot.benchmark(request)["comparability"]["baseline"],"unverified")

    def test_revision_comparison_uses_root_contract_and_original_baseline(self):
        child = self.seed(revision=self.value["id"])
        child["original_goal"] = "Correction text cannot become original criteria"
        child["template"]["version"] = 8
        child["spec"]["limits"]["minutes"] = 100
        self.save_workflow(child)
        run = self.store.get(child["run_id"])
        run["artifacts"]["baseline_snapshot_sha256"] = "b"*64
        self.store.save(run)
        saved = self.pilot.benchmark(BenchmarkInput(**self.benchmark_body(workflow_id=child["id"])))
        context = saved["comparison_context"]
        self.assertEqual(context["root_workflow_id"],self.value["id"])
        self.assertEqual(context["baseline_sha256"],"a"*64)
        self.assertEqual(context["recipe"]["version"],3)
        self.assertEqual(context["limits"]["minutes"],30)
        self.assertEqual(saved["acceptance"],self.value["original_goal"])

    def test_failed_review_labels_are_immutable_and_do_not_change_gates(self):
        body = self.label_body()
        before = self.store.get(self.value["run_id"])
        response = self.client.post("/api/pilot/observations",json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        saved = response.json()
        self.assertFalse(saved["affects_acceptance"])
        self.assertEqual(saved["actor"],"local")
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=self.headers).json(),saved)
        self.assertEqual(self.store.get(self.value["run_id"]),before)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"classification":"false_alarm"},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"request_id":str(uuid4()),"content_sha256":"b"*64},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"request_id":str(uuid4()),"observation_id":str(uuid4())},headers=self.headers).status_code,404)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"request_id":str(uuid4()),"role":"owner"},headers=self.headers).status_code,422)

    def test_label_reference_cannot_cross_runs_or_use_unauthorized_project(self):
        body = self.label_body()
        second = self.seed()
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"workflow_id":second["id"]},headers=self.headers).status_code,404)
        denied = self.seed(path=self.project.parent / "unapproved")
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"workflow_id":denied["id"]},headers=self.headers).status_code,400)

    def test_team_role_project_scope_and_actor_bound_idempotency(self):
        owner = {"version":"2.0","workspace":"team","team":True,"actor":"owner","role":"owner","projects":[str(self.project)]}
        self.value["authority"] = owner
        self.save_workflow(self.value)
        body = self.label_body()
        def headers(ctx):
            return {**self.headers,"X-Parallax-Authority":json.dumps(ctx)}
        for role in ("owner","developer","reviewer"):
            ctx = {**owner,"actor":role,"role":role}
            response = self.client.post("/api/pilot/observations",json=body,headers=headers(ctx))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["actor"],role)
        self.assertEqual(self.client.post("/api/pilot/benchmark",json=self.benchmark_body(),headers=headers({**owner,"role":"reviewer"})).status_code,403)
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=headers({**owner,"projects":[]})).status_code,403)
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=headers({**owner,"workspace":"other"})).status_code,404)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pilot_observations").fetchone()[0],3)

    def test_personal_workspace_mismatch_is_hidden(self):
        self.value["authority"] = {"workspace":"personal-one","team":False}
        self.save_workflow(self.value)
        headers = {**self.headers,"X-Parallax-Authority":json.dumps({"version":"2.0","workspace":"personal-two","team":False,"actor":"other","projects":[str(self.project)]})}
        self.assertEqual(self.client.post("/api/pilot/benchmark",json=self.benchmark_body(),headers=headers).status_code,404)
        self.assertEqual(self.client.get("/api/pilot/report",headers=headers).json()["outcomes"],[])

    def test_lineage_report_keeps_failures_and_ancestors_outside_latest_window(self):
        child = self.seed(revision=self.value["id"],status="cancelled")
        child_run = self.store.get(child["run_id"])
        child_run["artifacts"]["runtime_seconds"] = 20
        self.store.save(child_run)
        second = self.seed(status="cancelled")
        report = self.pilot.report()
        group = report["repeat_use"]["actors"][0]
        self.assertEqual(group["root_tasks"],2)
        self.assertEqual(group["later_tasks"],1)
        self.assertEqual(report["repeat_use"]["voluntary_return"],"not measured")
        self.assertEqual(len(report["outcomes"]),3)
        with patch.object(self.app.state.workflows,"listing",return_value=[{"id":child["id"]}]):
            lineage = self.pilot.report()["lineages"][0]
        self.assertEqual(lineage["workflow_count"],2)
        self.assertEqual(lineage["execution_seconds"],30)
        self.assertEqual(len(lineage["provider_usage"]),2)
        self.assertIn("failed",[member["status"] for member in lineage["members"]])
        self.assertEqual(lineage["cost_status"],"unknown")
        self.assertEqual(lineage["interventions"],1)
        child_run["artifacts"].pop("runtime_seconds")
        self.store.save(child_run)
        with patch.object(self.app.state.workflows,"listing",return_value=[{"id":child["id"]}]):
            lineage = self.pilot.report()["lineages"][0]
        self.assertIsNone(lineage["execution_seconds"])
        self.assertEqual(lineage["observed_execution_seconds"],10)
        self.assertFalse(lineage["execution_time_complete"])

    def test_capabilities_and_anonymous_label_denial(self):
        self.assertEqual(self.client.get("/api/context",headers=self.headers).json()["pilot_features"],PILOT_FEATURES)
        self.assertEqual(self.client.get("/api/pilot/report",headers=self.headers).json()["features"],PILOT_FEATURES)
        self.assertEqual(self.client.post("/api/pilot/observations",json=self.label_body()).status_code,401)
        self.assertTrue(permitted("POST","/api/pilot/observations"))
        self.assertFalse(permitted("POST","/api/pilot/observations","cursor=1"))
        self.assertFalse(permitted("DELETE","/api/pilot/observations"))
        self.assertFalse(permitted("POST","/api/pilot/observations/../benchmark"))

    def test_report_contains_readable_journal_only_failures_and_explicit_caps(self):
        recorded = record_observation(self.store,self.value["run_id"],"review",
            {"provider":"claude","ok":False,"summary":"Interrupted before verdict","error":{"code":"cancelled"}},
            phase_attempt("final", "integration"))
        report = self.pilot.report()
        observed = report["evidence_observations"][0]
        self.assertEqual(observed["observation"]["id"],recorded["observation"]["id"])
        self.assertEqual(observed["outcome"],"failed")
        self.assertEqual(observed["summary"],"Interrupted before verdict")
        self.assertEqual(self.store.get(self.value["run_id"])["reviews"],[])
        body = {"request_id":str(uuid4()),"workflow_id":self.value["id"],"observation_id":observed["observation"]["id"],
                "content_sha256":observed["observation"]["content_sha256"],"classification":"unresolved"}
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=self.headers).status_code,200)
        for _ in range(110):
            self.store.event(self.value["run_id"],"check",{"name":"Compatibility","ok":False,"output":"PRIVATE COMMAND OUTPUT","phase":"baseline"})
        report = self.pilot.report()
        self.assertTrue(report["evidence_observations_truncated"])
        self.assertEqual(len(report["evidence_observations"]),100)
        self.assertNotIn("PRIVATE COMMAND OUTPUT",json.dumps(report["evidence_observations"]))

    def test_tampered_journal_is_unlabelable_and_report_marks_warning(self):
        recorded = record_observation(self.store,self.value["run_id"],"review",
            {"provider":"claude","ok":False,"summary":"Compatibility regression"}, phase_attempt("final"))
        with self.store.connect() as db:
            row = db.execute("SELECT sequence,data FROM events WHERE run_id=? AND kind='evidence_observation'",(self.value["run_id"],)).fetchone()
            data = json.loads(row["data"])
            data["evidence"]["ok"] = True
            db.execute("UPDATE events SET data=? WHERE sequence=?",(json.dumps(data),row["sequence"]))
        report = self.pilot.report()
        self.assertEqual(report["evidence_observations"],[])
        self.assertEqual(report["evidence_warnings"],[{"workflow_id":self.value["id"],"code":"invalid_observation_journal"}])
        body = {"request_id":str(uuid4()),"workflow_id":self.value["id"],"observation_id":recorded["observation"]["id"],
                "content_sha256":recorded["observation"]["content_sha256"],"classification":"false_alarm"}
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=self.headers).status_code,400)

    def test_finding_labels_bind_original_review_indices_and_reject_check_references(self):
        self.store.event(self.value["run_id"],"review",{"provider":"claude","ok":False,"findings":[
            {"title":"Real defect","body":"Independent input fails","priority":"P1","code_location":None},
            "Advisory is not a reproduced defect"]})
        metadata = self.store.observations(self.value["run_id"])[0]["observation"]
        body = {"request_id":str(uuid4()),"workflow_id":self.value["id"],"observation_id":metadata["id"],
                "content_sha256":metadata["content_sha256"],"classification":"false_alarm","finding_index":1}
        response = self.client.post("/api/pilot/observations",json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["finding_index"],1)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"finding_index":0},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"request_id":str(uuid4()),"finding_index":2},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post("/api/pilot/observations",json={**body,"request_id":str(uuid4()),"finding_index":50},headers=self.headers).status_code,422)
        findings = self.pilot.report()["evidence_observations"][0]["findings"]
        self.assertEqual([finding["index"] for finding in findings],[0,1])
        self.assertEqual(findings[1]["title"],"Advisory is not a reproduced defect")
        self.store.event(self.value["run_id"],"check",{"name":"Compatibility","ok":False,"phase":"final"})
        metadata = self.store.observations(self.value["run_id"])[1]["observation"]
        body.update(request_id=str(uuid4()),observation_id=metadata["id"],content_sha256=metadata["content_sha256"],finding_index=0)
        self.assertEqual(self.client.post("/api/pilot/observations",json=body,headers=self.headers).status_code,400)

    def test_one_recovery_request_does_not_count_its_generated_steering_twice(self):
        run = self.store.get(self.value["run_id"])
        run["status"] = "needs_attention"
        run["errors"] = [{"category":"failed_checks","message":"Check failed"}]
        self.store.save(run)
        with patch.object(self.app.state.engine,"control",return_value={"ok":True}):
            self.app.state.engine.recover_run(self.value["run_id"],"repair_candidate")
        report = self.pilot.report()
        self.assertEqual(report["outcomes"][0]["interventions"],1)
        self.assertEqual(report["lineages"][0]["interventions"],1)
        self.store.event(self.value["run_id"],"steering",{"message":"Distinct user correction"})
        self.assertEqual(self.pilot.report()["outcomes"][0]["interventions"],2)


class PilotQueuedAuthorizationTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.owner = self.signed_in(user(9701,"pilot-owner"))
        self.reviewer = self.signed_in(user(9702,"pilot-reviewer"))
        self.headers = {"Origin":ORIGIN}
        self.team = self.owner.post("/api/workspaces",json={"name":"Pilot team"},headers=self.headers).json()["id"]
        self.owner.post("/api/workspaces/"+self.team+"/switch",headers=self.headers)
        invitation = self.owner.post("/api/workspaces/invitations",json={"role":"reviewer"},headers=self.headers).json()
        self.reviewer.post("/api/invitations/accept",json={"token":invitation["token"]},headers=self.headers)
        self.reviewer.post("/api/workspaces/"+self.team+"/switch",headers=self.headers)
        self.worker = self.pair(self.owner,workspaces=("/approved",))
        self.app.state.executors.features(self.worker["id"],["workflow-v2",*PILOT_FEATURES])
        self.owner.post("/api/workspaces/projects",json={"worker":self.worker["id"],"path":"/approved"},headers=self.headers)
        self.principal = self.app.state.accounts.principal(self.reviewer.cookies.get("parallax_session"))
        self.auth = self.app.state.accounts.teams.context(self.principal,self.worker["id"])

    def queue(self, path="/api/pilot/observations", body=None):
        identifier = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)",
                       (identifier,self.worker["id"],encode({"method":"POST","path":path,"query":"","body":body or {},
                        "authority":self.auth,"expires_at":time.time()+60}),time.time()))
        return identifier

    def response(self, identifier):
        with self.store.connect() as db:
            return json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?",(identifier,)).fetchone()[0])

    def test_reviewer_can_label_but_cannot_record_benchmarks(self):
        teams = self.app.state.accounts.teams
        self.assertEqual(teams.reauthorize(self.auth,self.worker["id"],"POST","/api/pilot/observations")["role"],"reviewer")
        with self.assertRaises(HTTPException):
            teams.reauthorize(self.auth,self.worker["id"],"POST","/api/pilot/benchmark")

    def test_removed_member_invalidates_queued_label(self):
        identifier = self.queue()
        self.owner.delete("/api/workspaces/members/"+self.principal.account["id"],headers=self.headers)
        self.assertEqual(self.app.state.executors.pending(self.worker["id"]),[])
        self.assertEqual(self.response(identifier)["status"],403)

    def test_changed_project_grant_invalidates_queued_label(self):
        identifier = self.queue()
        with self.store.connect() as db:
            db.execute("UPDATE project_bindings SET members=?", (json.dumps([self.owner.get("/api/session").json()["account"]["id"]]),))
        self.assertEqual(self.app.state.executors.pending(self.worker["id"]),[])
        self.assertEqual(self.response(identifier)["status"],403)

    def test_downgraded_worker_refuses_new_operations_before_dispatch(self):
        observation = self.queue()
        measurement = self.queue("/api/pilot/benchmark",{"evaluation":{"schema_version":"1.0"}})
        self.app.state.executors.features(self.worker["id"],["workflow-v2"])
        self.assertEqual(self.app.state.executors.pending(self.worker["id"]),[])
        self.assertEqual(self.response(observation)["status"],409)
        self.assertEqual(self.response(measurement)["status"],409)
        response = self.reviewer.post("/api/executors/"+self.worker["id"]+"/proxy/pilot/observations",json={},headers=self.headers)
        self.assertEqual(response.status_code,409,response.text)

    def test_revoked_worker_cannot_dispatch_queued_label(self):
        self.queue()
        self.owner.delete("/api/executors/"+self.worker["id"],headers=self.headers)
        with self.assertRaises(HTTPException):
            self.app.state.executors.pending(self.worker["id"])


if __name__ == "__main__":
    unittest.main()
