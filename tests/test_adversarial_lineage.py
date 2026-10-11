"""Saved candidates can be corrected repeatedly without parallel siblings."""
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from parallax.workflows import ApprovalRequest, RevisionRequest
import test_workflows as fixtures


class RevisionLineageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = fixtures.WorkflowTests.asyncTearDown
    check_project = fixtures.WorkflowTests.check_project
    request = fixtures.WorkflowTests.request
    settle = fixtures.WorkflowTests.settle
    candidate = fixtures.WorkflowTests.candidate
    restart = fixtures.WorkflowTests.restart

    async def child(self, parent):
        self.registry.turn = 0
        request = RevisionRequest(request_id=uuid4(), candidate_digest=parent["candidate"]["digest"], correction="Clarify the saved candidate.")
        original_run = self.registry.run
        async def correction(provider, **kwargs):
            result = await original_run(provider, **kwargs)
            if kwargs["mode"] == "edit":
                (kwargs["workspace"] / "maths.py").write_text("def add(a,b):\n    # correction " + str(request.request_id) + "\n    return a + b\n")
            return result
        with patch.object(self.registry, "run", side_effect=correction):
            value = await self.service.revise(parent["id"], request)
            value = await self.settle(value["id"])
        self.assertEqual(value["status"], "awaiting_approval", value.get("error"))
        return value

    async def test_revision_of_revision_preserves_original_baseline_and_parent(self):
        original = await self.candidate()
        first = await self.child(original)
        first_manager = self.service.candidates.manager(self.store.get(first["run_id"]))
        saved_tree = first_manager.fingerprint(first_manager.integration_path)
        await self.restart()
        second = await self.child(first)
        self.assertEqual(second["revision"]["lineage"], original["id"])
        self.assertEqual(second["revision"]["parent"], first["id"])
        self.assertEqual(self.service.get(first["id"])["status"], "superseded")
        self.assertEqual(first_manager.fingerprint(first_manager.integration_path), saved_tree)
        self.assertEqual(self.store.get(second["run_id"])["artifacts"]["baseline_snapshot_sha256"],
                         self.store.get(original["run_id"])["artifacts"]["baseline_snapshot_sha256"])
        self.assertNotEqual(second["candidate"]["digest"], first["candidate"]["digest"])
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        self.assertEqual(fixtures.git(self.project, "diff", "--cached"), self.staging)
        with self.assertRaisesRegex(ValueError, "already active"):
            await self.child(original)

    async def test_approved_revision_can_be_corrected_but_queued_child_blocks_siblings(self):
        first = await self.child(await self.candidate())
        await self.service.approve(first["id"], ApprovalRequest(request_id=uuid4(), candidate_digest=first["candidate"]["digest"]))
        first = await self.settle(first["id"])
        self.assertEqual(first["status"], "approved")
        request = RevisionRequest(request_id=uuid4(), candidate_digest=first["candidate"]["digest"], correction="One more correction.")
        with patch.object(self.service, "_launch", AsyncMock()):
            child = await self.service.revise(first["id"], request)
            self.assertEqual(child["status"], "queued")
            with self.assertRaisesRegex(ValueError, "already active"):
                await self.service.revise(first["id"], request.model_copy(update={"request_id":uuid4()}))
