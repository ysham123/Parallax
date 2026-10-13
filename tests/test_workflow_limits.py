"""A follow-up can raise the decision limit that stopped its parent; omitting it changes nothing."""
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import ValidationError

from parallax.workflows import WorkflowStart
import test_workflows as workflow_fixtures


class WorkflowLimitTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflow_fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = workflow_fixtures.WorkflowTests.asyncTearDown
    check_project = workflow_fixtures.WorkflowTests.check_project
    request = workflow_fixtures.WorkflowTests.request

    async def start(self, request):
        with patch.object(self.service, "_launch", AsyncMock()):
            return self.service.get((await self.service.start(request))["id"])

    async def test_followup_raises_decision_limit_and_keeps_the_rest(self):
        parent = await self.start(self.request())
        inherited = parent["spec"]["limits"]
        child = await self.start(WorkflowStart(request_id=uuid4(), workspace=str(self.project), prompt="Try again",
                                               parent_workflow_id=parent["id"], coordinator_turns=24))
        self.assertEqual(child["spec"]["limits"]["coordinator_turns"], 24)
        self.assertEqual({k: v for k, v in child["spec"]["limits"].items() if k != "coordinator_turns"},
                         {k: v for k, v in inherited.items() if k != "coordinator_turns"})

    async def test_omitted_override_inherits_and_keeps_request_identity(self):
        parent = await self.start(self.request())
        request = WorkflowStart(request_id=uuid4(), workspace=str(self.project), prompt="Try again", parent_workflow_id=parent["id"])
        child = await self.start(request)
        self.assertEqual(child["spec"]["limits"]["coordinator_turns"], parent["spec"]["limits"]["coordinator_turns"])
        # A retry of the same request is recognized, with or without the new optional field absent.
        with patch.object(self.service, "_launch", AsyncMock()):
            self.assertEqual((await self.service.start(request))["id"], child["id"])

    def test_bounds(self):
        for value in (1, 61):
            with self.assertRaises(ValidationError):
                WorkflowStart(request_id=uuid4(), workspace="/tmp", prompt="x", coordinator_turns=value)


if __name__ == "__main__":
    unittest.main()
