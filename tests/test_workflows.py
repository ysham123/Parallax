"""Real graphs, durable checkpoints, real Git effects, deterministic providers."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from parallax.candidates import Candidates
from parallax.engine import Engine
from parallax.models import CheckSpec, Limits, Participant, RunSpec
from parallax.receipt import get_receipt
from parallax.server import create_app
from parallax.store import Store
from parallax.workflows import Workflows, WorkflowStart, TemplateInput, Decision
from test_engine import FakeRegistry, git


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        git(self.project, "init", "-q")
        git(self.project, "config", "user.name", "Test")
        git(self.project, "config", "user.email", "test@example.com")
        (self.project / "maths.py").write_text("def add(a,b):\n    return a-b\n")
        (self.project / "check.py").write_text("from maths import add\nassert add(2,3)==5\n")
        git(self.project, "add", ".")
        git(self.project, "commit", "-qm", "baseline")
        (self.project / "notes.txt").write_text("staged user work")
        git(self.project, "add", "notes.txt")
        self.staging = git(self.project, "diff", "--cached")
        self.store = Store(self.root / "state")
        self.registry = FakeRegistry()
        self.engine = Engine(self.store, self.registry)
        self.service = Workflows(self.engine, self.check_project)
        self.template = self.service.save_template(TemplateInput(name="Addition fix",
            coordinator=Participant(provider="codex"), team=[Participant(provider="claude")],
            checks=[CheckSpec(name="addition", argv=[sys.executable,"-B","check.py"])]))

    def check_project(self, value):
        if Path(value).resolve() != self.project:
            raise ValueError("Project not approved")

    async def asyncTearDown(self):
        await self.service.close()
        await self.engine.shutdown()

    def request(self):
        return WorkflowStart(request_id=uuid4(), workspace=str(self.project), prompt="Fix addition",
            template_id=self.template["id"], template_version=self.template["version"])

    async def settle(self, identifier):
        job = self.service.jobs.get(identifier)
        if job:
            await asyncio.wait_for(asyncio.shield(job), 30)
        await asyncio.sleep(0)
        return self.service.get(identifier)

    async def candidate(self):
        started = await self.service.start(self.request())
        value = await self.settle(started["id"])
        self.assertEqual(value["status"], "awaiting_approval", value.get("error"))
        return value

    async def restart(self):
        await self.service.close()
        await self.engine.shutdown()
        self.store = Store(self.root / "state")
        self.registry = FakeRegistry()
        self.engine = Engine(self.store, self.registry)
        self.engine.recover()
        self.service = Workflows(self.engine, self.check_project)
        await self.service.recover()

    async def approve(self, value):
        await self.service.decide(value["id"], Decision(action="approve", candidate_digest=value["candidate"]["digest"]))
        return await self.settle(value["id"])

    async def test_candidate_waits_for_approval_and_preserves_staging(self):
        value = await self.candidate()
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        self.assertEqual(git(self.project, "diff", "--cached"), self.staging)
        self.assertEqual(value["candidate"]["check_count"], 1)
        result = await self.approve(value)
        self.assertEqual(result["status"], "applied", result.get("error"))
        self.assertIn("return a + b", (self.project / "maths.py").read_text())
        self.assertEqual(git(self.project, "diff", "--cached"), self.staging)
        receipt = get_receipt(self.store, value["run_id"])
        self.assertEqual(receipt["outcome"], "applied")
        self.assertEqual(receipt["approval"]["digest"], value["candidate"]["digest"])
        self.assertEqual(receipt["approval"]["state"], "applied")
        self.assertTrue(all(gate["status"] == "passed" for gate in receipt["gates"]))

    async def test_waiting_approval_survives_restart_without_provider_calls(self):
        value = await self.candidate()
        await self.restart()
        self.assertEqual(self.service.get(value["id"])["status"], "awaiting_approval")
        result = await self.approve(value)
        self.assertEqual(result["status"], "applied", result.get("error"))
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(len(self.store.runs()), 1)

    async def test_rejection_and_repeated_decisions_are_durable(self):
        value = await self.candidate()
        decision = Decision(action="reject", candidate_digest=value["candidate"]["digest"])
        await self.service.decide(value["id"], decision)
        self.assertEqual((await self.settle(value["id"]))["status"], "rejected")
        await self.restart()
        self.assertEqual((await self.service.decide(value["id"], decision))["status"], "rejected")
        with self.assertRaises(ValueError):
            await self.approve(value)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())

    async def test_changed_source_or_candidate_cannot_be_approved(self):
        value = await self.candidate()
        (self.project / "notes.txt").write_text("changed while waiting")
        with self.assertRaisesRegex(ValueError, "changed"):
            await self.approve(value)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        (self.project / "notes.txt").write_text("staged user work")
        run = self.store.get(value["run_id"])
        metadata = json.loads((Path(run["artifacts"]["directory"]) / "workspace.json").read_text())
        (Path(metadata["integration_path"]) / "maths.py").write_text("unverified content")
        with self.assertRaises(ValueError):
            await self.approve(value)

    async def test_evidence_change_and_wrong_digest_block_approval(self):
        value = await self.candidate()
        with self.assertRaisesRegex(ValueError, "Refresh"):
            await self.service.decide(value["id"], Decision(action="approve", candidate_digest="0"*64))
        run = self.store.get(value["run_id"])
        run["checks"][0]["output"] += "altered evidence"
        self.store.save(run)
        with self.assertRaisesRegex(ValueError, "changed"):
            await self.approve(value)

    async def test_candidate_metadata_damage_reports_actionable_failure(self):
        value = await self.candidate()
        run = self.store.get(value["run_id"])
        metadata = Path(run["artifacts"]["directory"]) / "workspace.json"
        saved = json.loads(metadata.read_text())
        saved["integration_path"] = str(self.project)
        metadata.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "Prepare a new workflow"):
            await self.approve(value)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())

    async def test_project_change_after_decision_is_rechecked_before_application(self):
        value = await self.candidate()
        with patch.object(self.service, "_launch", AsyncMock()):
            await self.service.decide(value["id"], Decision(action="approve", candidate_digest=value["candidate"]["digest"]))
        (self.project / "notes.txt").write_text("new user edit after approval")
        await self.restart()
        await self.service.resume(value["id"])
        result = await self.settle(value["id"])
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("changed", result["error"])
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        self.assertEqual((self.project / "notes.txt").read_text(), "new user edit after approval")

    async def test_decision_persisted_before_checkpoint_resume_recovers(self):
        value = await self.candidate()
        with patch.object(self.service, "_launch", AsyncMock()):
            await self.service.decide(value["id"], Decision(action="approve", candidate_digest=value["candidate"]["digest"]))
        await self.restart()
        self.assertEqual(self.service.get(value["id"])["status"], "interrupted")
        await self.service.resume(value["id"])
        result = await self.settle(value["id"])
        self.assertEqual(result["status"], "applied", result.get("error"))
        self.assertEqual(self.registry.calls, [])

    async def test_applied_files_before_result_save_are_reconciled_once(self):
        value = await self.candidate()
        with patch.object(self.service.candidates, "_finish", side_effect=RuntimeError("simulated crash after file transaction")):
            result = await self.approve(value)
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("return a + b", (self.project / "maths.py").read_text())
        await self.restart()
        await self.service.resume(value["id"])
        result = await self.settle(value["id"])
        self.assertEqual(result["status"], "applied", result.get("error"))
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(git(self.project, "diff", "--cached"), self.staging)

    async def test_start_retries_keep_one_workflow_and_engine_run(self):
        request = self.request()
        first, second = await asyncio.gather(self.service.start(request), self.service.start(request))
        self.assertEqual(first["id"], second["id"])
        await self.settle(first["id"])
        count = len(self.registry.calls)
        self.assertEqual((await self.service.start(request))["id"], first["id"])
        self.assertEqual(len(self.registry.calls), count)
        self.assertEqual(len(self.store.runs()), 1)
        with self.assertRaises(ValueError):
            await self.service.start(request.model_copy(update={"prompt":"Different task"}))

    async def test_capacity_applies_to_new_starts_approvals_and_resumption(self):
        candidate = await self.candidate()
        with patch.object(self.service, "_launch", AsyncMock()):
            interrupted = await self.service.start(self.request())
            self.service._stage(interrupted["id"], "interrupted", "interrupted")
            for _ in range(3):
                await self.service.start(self.request())
            with self.assertRaisesRegex(ValueError, "Three workflows"):
                await self.service.start(self.request())
            with self.assertRaisesRegex(ValueError, "Three workflows"):
                await self.service.resume(interrupted["id"])
            with self.assertRaisesRegex(ValueError, "Three workflows"):
                await self.approve(candidate)
            self.assertNotIn("decision", self.service.get(candidate["id"]))

    async def test_engine_run_committed_before_workflow_checkpoint_is_reused(self):
        request = self.request()
        with patch.object(self.service, "_launch", AsyncMock()):
            initial = await self.service.start(request)
        saved = self.service.get(initial["id"])
        run = await self.engine.start(RunSpec.model_validate(saved["spec"]), request_key=initial["id"]+":build")
        job = self.engine.jobs.get(run["run_id"])
        if job:
            await asyncio.wait_for(job, 30)
        await self.restart()
        await self.service.resume(initial["id"])
        result = await self.settle(initial["id"])
        self.assertEqual(result["status"], "awaiting_approval", result.get("error"))
        self.assertEqual(result["run_id"], run["run_id"])
        self.assertEqual(self.registry.calls, [])

    async def test_failed_run_persistence_dispatches_nothing_and_resume_recovers(self):
        with patch.object(self.store, "save_requested_run", side_effect=RuntimeError("simulated storage failure")):
            value = await self.service.start(self.request())
            failed = await self.settle(value["id"])
        self.assertEqual(failed["status"], "needs_attention")
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(self.store.runs(), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM project_locks").fetchone()[0], 0)
            # A separate crash can leave a database claim before any run was saved.
            db.execute("INSERT INTO project_locks VALUES(?,?)", (str(self.project),str(uuid4())))
        await self.service.resume(value["id"])
        recovered = await self.settle(value["id"])
        self.assertEqual(recovered["status"], "awaiting_approval", recovered.get("error"))
        self.assertEqual(len(self.store.runs()), 1)

    async def test_template_edits_do_not_change_existing_execution(self):
        request = self.request()
        with patch.object(self.service, "_launch", AsyncMock()):
            value = await self.service.start(request)
        updated = self.service.save_template(TemplateInput(name="Changed recipe",instructions="new instructions"), self.template["id"])
        self.assertEqual(updated["version"], 2)
        self.assertEqual(self.service.get(value["id"])["template"]["name"], "Addition fix")
        self.assertEqual(self.service.get(value["id"])["template"]["version"], 1)

    async def test_followup_inherits_exact_saved_spec_and_recipe_version(self):
        template = self.service.save_template(TemplateInput(name="Original recipe", instructions="Preserve the original API.",
            limits=Limits(workers=2, repairs=4, minutes=32, attempt_seconds=150, coordinator_turns=12),
            checks=[CheckSpec(name="original check", argv=[sys.executable, "-B", "check.py"], timeout=47)]))
        request = self.request().model_copy(update={"template_id":template["id"], "template_version":1,
            "minutes":29, "coordinator":Participant(provider="codex", model="saved-model", effort="medium"),
            "team":[Participant(provider="claude", effort="low"), Participant(provider="grok", role="reviewer")]})
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(request)
            saved = self.service.get(parent["id"])
            saved["spec"].update(package_roots=["src", "tests"], profile="Saved project profile", mode="compare", integrate=True)
            self.service.save(saved)
            self.service.save_template(TemplateInput(name="Changed recipe", instructions="Different requirements.",
                limits=Limits(workers=8, repairs=0, minutes=100)), template["id"])
            child = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"],
                workspace=str(self.project / "."), prompt="Add a boundary case."))
            expected = {**saved["spec"], "prompt":child["spec"]["prompt"], "mode":"build", "integrate":False}
            self.assertEqual(child["spec"], expected)
            self.assertEqual(child["template"], {"id":template["id"], "version":1, "name":"Original recipe"})
            self.assertEqual(child["template_details"]["instructions"], "Preserve the original API.")
            self.assertEqual(child["prompt"], "Add a boundary case.")
            self.assertEqual(child["original_goal"], request.prompt)
            self.assertEqual(child["parent_workflow_id"], parent["id"])
            self.assertEqual(self.service.get(parent["id"])["spec"], saved["spec"])

            override = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"],
                workspace=str(self.project), prompt="Use a different team.", minutes=11,
                coordinator=Participant(provider="grok"), team=[Participant(provider="claude", model="new-model")]))
            self.assertEqual(override["spec"]["coordinator"]["provider"], "grok")
            self.assertEqual(override["spec"]["team"][0]["model"], "new-model")
            self.assertEqual(override["spec"]["limits"], {**saved["spec"]["limits"], "minutes":11})
            self.assertEqual(override["spec"]["checks"], saved["spec"]["checks"])
            self.assertEqual(override["spec"]["package_roots"], saved["spec"]["package_roots"])

    async def test_followup_builds_from_current_project_with_its_own_approval(self):
        parent = await self.candidate()
        await self.service.decide(parent["id"], Decision(action="reject", candidate_digest=parent["candidate"]["digest"]))
        await self.settle(parent["id"])
        self.registry.turn = 0
        observed = []
        original_run = self.registry.run

        async def inspect_current_project(provider, **kwargs):
            if kwargs["mode"] == "edit":
                observed.append((kwargs["workspace"] / "maths.py").read_text())
            return await original_run(provider, **kwargs)

        with patch.object(self.registry, "run", side_effect=inspect_current_project):
            started = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"],
                workspace=str(self.project), prompt="Fix addition with the original signature."))
            child = await self.settle(started["id"])
        self.assertEqual(child["status"], "awaiting_approval", child.get("error"))
        self.assertEqual(observed, ["def add(a,b):\n    return a-b\n"])
        self.assertNotEqual(child["run_id"], parent["run_id"])
        self.assertNotEqual(child["candidate"]["digest"], parent["candidate"]["digest"])
        self.assertNotIn("decision", child)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        with self.assertRaisesRegex(ValueError, "Refresh"):
            await self.service.decide(child["id"], Decision(action="approve", candidate_digest=parent["candidate"]["digest"]))
        result = await self.approve(child)
        self.assertEqual(result["status"], "applied", result.get("error"))
        self.assertEqual(self.service.get(parent["id"])["status"], "rejected")
        self.assertEqual(git(self.project, "diff", "--cached"), self.staging)

    async def test_followup_links_and_original_goal_survive_restart_and_chain(self):
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(self.request())
            child = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"],
                workspace=str(self.project), prompt="First follow-up request."))
        await self.restart()
        restored = self.service.public(self.service.get(child["id"]))
        self.assertEqual(restored["parent_workflow_id"], parent["id"])
        self.assertEqual(restored["prompt"], "First follow-up request.")
        self.assertEqual(restored["original_goal"], parent["prompt"])
        self.assertEqual(next(row for row in self.service.listing() if row["id"] == child["id"])["parent_workflow_id"], parent["id"])
        with patch.object(self.service, "_launch", AsyncMock()):
            grandchild = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=child["id"],
                workspace=str(self.project), prompt="Second follow-up request."))
        self.assertEqual(grandchild["original_goal"], parent["prompt"])
        self.assertEqual(grandchild["parent_workflow_id"], child["id"])
        self.assertEqual(grandchild["prompt"], "Second follow-up request.")
        self.assertNotIn("First follow-up request.", grandchild["spec"]["prompt"])
        self.assertEqual(grandchild["spec"]["prompt"].count("Original goal:"), 1)
        self.assertIn("Candidate code from the prior task is not reused.", grandchild["spec"]["prompt"])

    async def test_followup_context_bounds_prior_result_without_cutting_new_request(self):
        parent = await self.candidate()
        run = self.store.get(parent["run_id"])
        run["summary"] = "x" * 10000 + "NOT INCLUDED"
        self.store.save(run)
        prompt = "New request " + "y" * 11988
        with patch.object(self.service, "_launch", AsyncMock()):
            child = await self.service.start(WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"],
                workspace=str(self.project), prompt=prompt))
        self.assertEqual(child["prompt"], prompt)
        self.assertIn(prompt, child["spec"]["prompt"])
        self.assertIn("[Prior result truncated to 2,000 characters.]", child["spec"]["prompt"])
        self.assertNotIn("NOT INCLUDED", child["spec"]["prompt"])
        self.assertLess(len(child["spec"]["prompt"]), 20000)

    async def test_followup_parent_requires_authorization_and_same_project(self):
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(self.request())
        request = WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"], workspace=str(self.project), prompt="Follow up")
        with self.assertRaises(KeyError):
            await self.service.start(request.model_copy(update={"parent_workflow_id":uuid4()}))
        saved = self.service.get(parent["id"])
        saved["spec"]["workspace"] = str(self.root / "other-project")
        self.service.save(saved)
        with patch.object(self.service, "_followup_prompt", side_effect=AssertionError("Read unauthorized context")), \
                patch.object(self.service.store, "get", side_effect=AssertionError("Read unauthorized run")):
            with self.assertRaisesRegex(ValueError, "Project not approved"):
                await self.service.start(request)
        self.service.check_workspace = lambda _: None
        with self.assertRaisesRegex(ValueError, "same project"):
            await self.service.start(request)
        self.assertEqual(len(self.service.listing()), 1)

    async def test_followup_request_retries_are_idempotent_and_reject_changed_inputs(self):
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(self.request())
            other_parent = await self.service.start(self.request())
            request = WorkflowStart(request_id=uuid4(), parent_workflow_id=parent["id"], workspace=str(self.project), prompt="Follow up")
            child = await self.service.start(request)
            retry = await self.service.start(request.model_copy(update={"template_id":"not-used", "template_version":900}))
            self.assertEqual(child["id"], retry["id"])
            for changes in ({"prompt":"Different request"}, {"parent_workflow_id":other_parent["id"]}, {"minutes":12}):
                with self.assertRaisesRegex(ValueError, "different inputs"):
                    await self.service.start(request.model_copy(update=changes))
        self.assertEqual(len(self.service.listing()), 3)

    async def test_preexisting_root_request_hash_remains_retryable(self):
        request = self.request()
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(request)
        saved = self.service.get(parent["id"])
        saved.pop("parent_workflow_id")
        saved.pop("original_goal")
        self.service.save(saved)
        retry = await self.service.start(request)
        self.assertEqual(retry["id"], parent["id"])
        self.assertIsNone(retry["parent_workflow_id"])
        self.assertEqual(retry["original_goal"], request.prompt)

    async def test_cancel_waiting_candidate_keeps_project_unchanged(self):
        value = await self.candidate()
        self.assertEqual((await self.service.cancel(value["id"]))["status"], "cancelled")
        with self.assertRaises(ValueError):
            await self.approve(value)
        self.assertIn("return a-b", (self.project / "maths.py").read_text())

    async def test_removed_project_blocks_approval_and_history(self):
        value = await self.candidate()
        self.service.check_workspace = lambda _: (_ for _ in ()).throw(ValueError("Project removed"))
        self.assertEqual(self.service.listing(), [])
        with self.assertRaisesRegex(ValueError, "removed"):
            await self.approve(value)

    async def test_http_workflow_routes_reject_unapproved_projects_and_bearerless_calls(self):
        app = create_app(Store(self.root / "api-state"), FakeRegistry(), token="test-token", allowed_workspaces=(self.project,))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            self.assertEqual((await client.get("/api/workflow-templates")).status_code, 401)
            client.headers["Authorization"] = "Bearer test-token"
            self.assertEqual(len((await client.get("/api/workflow-templates")).json()), 3)
            response = await client.post("/api/workflows", json={"request_id":str(uuid4()), "workspace":str(self.root), "prompt":"Edit"})
            self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
