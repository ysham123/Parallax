"""Crash-boundary and measurement tests using disposable real Git projects."""
import asyncio
from contextlib import contextmanager
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from parallax import authority
from parallax.pilot import BenchmarkInput, Pilot
from parallax.workflows import ApprovalRequest, DeliveryRequest, RevisionRequest, Workflows
from parallax.workspaces import WorkspaceManager
import test_workflows as fixtures


class Crash(BaseException):
    """Process-loss simulation without asyncio's special KeyboardInterrupt handling."""


class DataRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = fixtures.WorkflowTests.asyncTearDown
    check_project = fixtures.WorkflowTests.check_project
    request = fixtures.WorkflowTests.request
    settle = fixtures.WorkflowTests.settle
    candidate = fixtures.WorkflowTests.candidate
    restart = fixtures.WorkflowTests.restart

    async def approved(self):
        value = await self.service.start(self.request().model_copy(update={"schema_version": "2.0"}))
        value = await self.settle(value["id"])
        self.assertEqual(value["status"], "awaiting_approval", value.get("error"))
        request = ApprovalRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        await self.service.approve(value["id"], request)
        return await self.settle(value["id"])

    async def publication_candidate(self):
        value = await self.approved()
        manager = self.service.candidates.manager(self.store.get(value["run_id"]))
        meta = manager.prepare()
        value["github_target"] = {"id": str(uuid4()), "base_commit": meta["source_state"]["head"],
            "base_tree": manager._oid(manager.workspace, meta["snapshot_commit"] + "^{tree}"),
            "full_name": "fixture/repo", "base": "main"}
        self.service.save(value)
        return value

    async def test_publication_reservation_and_exact_bundle_commit_together(self):
        value = await self.publication_candidate()
        request = DeliveryRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        connect = self.store.connect

        class FailBundleSave:
            def __init__(self, db): self.db = db
            def __getattr__(self, name): return getattr(self.db, name)
            def execute(self, sql, *args):
                if sql.startswith("UPDATE workflow_operations SET state='completed'"):
                    raise RuntimeError("crash before exact bundle becomes durable")
                return self.db.execute(sql, *args)

        @contextmanager
        def fault_connection():
            with connect() as db:
                yield FailBundleSave(db)

        with patch.object(self.service.candidates, "capture", AsyncMock(return_value=value["candidate"])), \
                patch.object(self.store, "connect", fault_connection):
            with self.assertRaisesRegex(RuntimeError, "exact bundle"):
                await self.service.begin_publication(value["id"], request)
        restored = self.service.get(value["id"])
        self.assertNotEqual(restored["delivery"]["github"], "publishing")
        self.assertIsNone(restored.get("publication_operation"))
        await self.restart()
        with patch.object(self.service.candidates, "capture", AsyncMock(return_value=value["candidate"])):
            package = await self.service.begin_publication(value["id"], request)
        self.assertEqual(package["digest"], request.candidate_digest)

    async def test_apply_retries_crash_before_filesystem_transaction(self):
        value = await self.approved()
        request = DeliveryRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        with patch.object(WorkspaceManager, "apply", side_effect=Crash("before first write")):
            with self.assertRaises(Crash):
                await self.service.apply_candidate(value["id"], request)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        await self.restart()
        result = await self.service.apply_candidate(value["id"], request)
        self.assertEqual(result["status"], "applied")
        self.assertIn("return a + b", (self.project / "maths.py").read_text())
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(fixtures.git(self.project, "diff", "--cached"), self.staging)

    async def test_apply_retries_partial_crash_after_verified_rollback(self):
        original_run = self.registry.run
        async def edit_two_files(provider, **kwargs):
            outcome = await original_run(provider, **kwargs)
            if kwargs["mode"] == "coordinate" and outcome.get("structured_output", {}).get("action") == "plan":
                outcome["structured_output"]["tasks"][0]["files"].append("readme.txt")
            if kwargs["mode"] == "edit":
                (kwargs["workspace"] / "readme.txt").write_text("Candidate documentation\n")
            return outcome
        with patch.object(self.registry, "run", side_effect=edit_two_files):
            value = await self.approved()
        request = DeliveryRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        write = WorkspaceManager._write_file
        def crash_after_write(*args):
            write(*args)
            raise Crash("after first write")
        with patch.object(WorkspaceManager, "_write_file", side_effect=crash_after_write):
            with self.assertRaises(Crash):
                await self.service.apply_candidate(value["id"], request)
        await self.restart()
        result = await self.service.apply_candidate(value["id"], request)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.project / "readme.txt").read_text(), "Candidate documentation\n")
        self.assertIn("return a + b", (self.project / "maths.py").read_text())
        self.assertEqual(self.registry.calls, [])

    async def test_apply_retry_after_crash_still_refuses_external_edits(self):
        value = await self.approved()
        request = DeliveryRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        with patch.object(WorkspaceManager, "apply", side_effect=Crash()):
            with self.assertRaises(Crash):
                await self.service.apply_candidate(value["id"], request)
        (self.project / "maths.py").write_text("Developer changed this after crash\n")
        await self.restart()
        with self.assertRaises(ValueError):
            await self.service.apply_candidate(value["id"], request)
        self.assertEqual((self.project / "maths.py").read_text(), "Developer changed this after crash\n")

    async def test_no_change_filesystem_application_is_durable(self):
        manager = WorkspaceManager(self.project, self.root / "unchanged-run")
        manager.prepare()
        self.assertTrue(manager.apply()["ok"])
        restored = WorkspaceManager(self.project, self.root / "unchanged-run")
        self.assertTrue(restored.load())
        self.assertTrue(restored.prepare()["applied"])

    async def test_approval_retry_reconciles_decision_saved_before_launch(self):
        value = await self.service.start(self.request().model_copy(update={"schema_version": "2.0"}))
        value = await self.settle(value["id"])
        request = ApprovalRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        with patch.object(self.service, "_launch", AsyncMock(side_effect=RuntimeError("crash before checkpoint resume"))):
            with self.assertRaises(RuntimeError): await self.service.approve(value["id"], request)
        await self.restart()
        await self.service.approve(value["id"], request)
        recovered = await self.settle(value["id"])
        self.assertEqual(recovered["status"], "approved")
        self.assertEqual(recovered["approval"]["id"], str(request.request_id))
        self.assertEqual(self.registry.calls, [])
        self.assertIn("return a-b", (self.project / "maths.py").read_text())

    async def test_completed_approval_operation_reconciles_unresumed_checkpoint(self):
        value = await self.service.start(self.request().model_copy(update={"schema_version":"2.0"}))
        value = await self.settle(value["id"])
        request = ApprovalRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        # Simulate durable approval success followed by process loss before the
        # newly scheduled graph task has a chance to resume its interrupt.
        with patch.object(self.service, "_launch", AsyncMock()):
            await self.service.approve(value["id"], request)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM workflow_operations WHERE id=?", (str(request.request_id),)).fetchone()[0], "completed")
        await self.restart()
        await self.service.approve(value["id"], request)
        self.assertEqual((await self.settle(value["id"]))["status"], "approved")
        self.assertEqual(self.registry.calls, [])

    async def test_metrics_count_interventions_after_event_page_boundary(self):
        value = await self.candidate()
        for _ in range(260): self.store.event(value["run_id"], "agent_output", {})
        self.store.event(value["run_id"], "steer_requested", {})
        report = Pilot(self.service).report()
        row = next(row for row in report["outcomes"] if row["workflow"] == value["id"])
        self.assertEqual(row["interventions"], 1)

    async def test_unknown_cost_stays_unknown_and_comparison_is_immutable(self):
        value = await self.candidate()
        pilot = Pilot(self.service)
        report = pilot.report()["outcomes"][0]
        self.assertIsNone(report["provider_cost_usd"])
        self.assertEqual(report["cost_status"], "unknown")
        request = BenchmarkInput(request_id=uuid4(), workflow_id=value["id"], approach="single_agent",
            duration_seconds=20, interventions=2, accepted=True)
        saved = pilot.benchmark(request)
        self.assertEqual(pilot.benchmark(request), saved)
        with self.assertRaisesRegex(ValueError, "reused"):
            pilot.benchmark(request.model_copy(update={"duration_seconds": 21}))
        self.assertEqual(saved["acceptance"], value["original_goal"])
        self.assertEqual(saved["required_checks"], value["spec"]["checks"])

    async def test_team_reviewer_assignment_requires_project_access(self):
        ctx = {"version":"2.0", "team":True, "workspace":"team", "actor":"owner", "role":"owner",
            "projects":[str(self.project)], "reviewers":["allowed", "restricted"],
            "reviewers_by_project":{str(self.project):["allowed"]}}
        token = authority.current.set(ctx)
        try:
            with patch.object(self.service, "_launch", AsyncMock()):
                value = await self.service.start(self.request().model_copy(update={"template_id":"verified-change"}))
            with self.assertRaisesRegex(ValueError, "access to this project"):
                self.service.assign(value["id"], "restricted")
            self.assertEqual(self.service.assign(value["id"], "allowed")["reviewer"], "allowed")
            authority.current.set({k:v for k,v in ctx.items() if k != "reviewers_by_project"})
            with self.assertRaises(ValueError): self.service.assign(value["id"], "allowed")
        finally:
            authority.current.reset(token)

    async def test_versioned_start_request_cannot_be_replayed_by_another_actor(self):
        request = self.request().model_copy(update={"schema_version":"2.0"})
        token = authority.current.set({"actor":"developer-a"})
        try:
            with patch.object(self.service, "_launch", AsyncMock()):
                value = await self.service.start(request)
            authority.current.set({"actor":"developer-b"})
            with self.assertRaisesRegex(ValueError, "another actor"):
                await self.service.start(request)
            self.assertEqual(self.service.get(value["id"])["requester"], "developer-a")
        finally:
            authority.current.reset(token)

    async def test_revision_request_cannot_be_replayed_by_another_actor(self):
        parent = await self.candidate()
        request = RevisionRequest(request_id=uuid4(), candidate_digest=parent["candidate"]["digest"], correction="Explain the fix")
        token = authority.current.set({"actor":"developer-a"})
        try:
            with patch.object(self.service, "_launch", AsyncMock()):
                child = await self.service.revise(parent["id"], request)
            authority.current.set({"actor":"developer-b"})
            with self.assertRaisesRegex(ValueError, "another actor"):
                await self.service.revise(parent["id"], request)
            self.assertEqual(self.service.get(child["id"])["requester"], "developer-a")
        finally:
            authority.current.reset(token)

    async def test_shared_recipe_cannot_reclassify_personal_or_builtin_recipe(self):
        for identifier in (self.template["id"], "verified-change"):
            recipe={**self.template, "id":identifier}
            recipe.pop("builtin", None)
            token = authority.current.set({"team":True,"workspace":"team","actor":"owner","role":"owner","recipes":[recipe]})
            try:
                with self.assertRaisesRegex(ValueError, "collides"):
                    self.service.install_shared_recipes()
            finally:
                authority.current.reset(token)
            with self.store.connect() as db:
                self.assertIsNone(db.execute("SELECT workspace FROM workflow_template_scope WHERE id=?", (identifier,)).fetchone())
        self.assertEqual(self.service.template(self.template["id"], 1)["name"], self.template["name"])

    async def test_shared_recipe_version_is_immutable(self):
        recipe={**self.template, "id":str(uuid4())}
        recipe.pop("builtin", None)
        token = authority.current.set({"team":True,"workspace":"team","actor":"owner","role":"owner","recipes":[recipe]})
        try:
            self.service.install_shared_recipes()
            authority.current.set({**authority.context(), "recipes":[{**recipe, "instructions":"changed"}]})
            with self.assertRaisesRegex(ValueError, "cannot be changed"):
                self.service.install_shared_recipes()
        finally:
            authority.current.reset(token)

    async def test_duplicate_start_across_services_is_idempotent(self):
        other = Workflows(self.engine, self.check_project)
        request = self.request().model_copy(update={"schema_version":"2.0"})
        entered = 0
        gate = asyncio.Event()
        async def simultaneous_validation(spec):
            nonlocal entered
            entered += 1
            if entered == 2: gate.set()
            await gate.wait()
        with patch.object(self.engine, "validate_settings", side_effect=simultaneous_validation), \
                patch.object(self.service, "_launch", AsyncMock()), patch.object(other, "_launch", AsyncMock()):
            first, second = await asyncio.gather(self.service.start(request), other.start(request))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.service.listing()), 1)
        await other.close()

    async def test_duplicate_revision_across_services_is_idempotent(self):
        parent = await self.candidate()
        other = Workflows(self.engine, self.check_project)
        request = RevisionRequest(request_id=uuid4(), candidate_digest=parent["candidate"]["digest"], correction="Document the fix")
        entered = 0
        gate = asyncio.Event()
        async def simultaneous_validation(spec):
            nonlocal entered
            entered += 1
            if entered == 2: gate.set()
            await gate.wait()
        with patch.object(self.engine, "validate_settings", side_effect=simultaneous_validation), \
                patch.object(self.service, "_launch", AsyncMock()), patch.object(other, "_launch", AsyncMock()):
            first, second = await asyncio.gather(self.service.revise(parent["id"], request), other.revise(parent["id"], request))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.service.get(parent["id"])["superseded_by"], first["id"])
        self.assertEqual(len(self.service.listing()), 2)
        await other.close()

    async def test_revision_during_approval_inspection_cannot_revive_parent(self):
        value = await self.service.start(self.request().model_copy(update={"schema_version":"2.0"}))
        value = await self.settle(value["id"])
        other = Workflows(self.engine, self.check_project)
        inspecting = asyncio.Event()
        release = asyncio.Event()
        async def slow_capture(run_id):
            inspecting.set()
            await release.wait()
            return value["candidate"]
        approval = ApprovalRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"])
        with patch.object(self.service.candidates, "capture", side_effect=slow_capture), \
                patch.object(self.service, "_launch", AsyncMock()), patch.object(other, "_launch", AsyncMock()):
            pending = asyncio.create_task(self.service.approve(value["id"], approval))
            await asyncio.wait_for(inspecting.wait(), 3)
            child = await other.revise(value["id"], RevisionRequest(request_id=uuid4(), candidate_digest=value["candidate"]["digest"], correction="Improve the candidate"))
            release.set()
            with self.assertRaisesRegex(ValueError, "not ready for approval"):
                await pending
        parent = self.service.get(value["id"])
        self.assertEqual(parent["status"], "superseded")
        self.assertEqual(parent["superseded_by"], child["id"])
        self.assertNotIn("approval", parent)
        await other.close()
