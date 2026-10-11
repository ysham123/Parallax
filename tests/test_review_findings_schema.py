"""Native structured findings preserve grounded locations into revisions."""
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from parallax.api_agent import _validate_schema
from parallax.context import findings, render_json
from parallax.engine import REVIEW_VERDICT_SCHEMA, _validate_review_verdict
from parallax.models import Participant, RunResult, RunSpec
from parallax.providers import _codex_schema
from parallax.workflows import FindingSelection, RevisionRequest
import test_workflows as fixtures


FINDING = {"title":"Document the corrected operation", "body":"Explain why the addition now satisfies the acceptance case.",
    "priority":"P3", "code_location":{"path":"maths.py", "line_range":{"start":2, "end":2}}}


class ReviewSchemaTests(unittest.TestCase):
    def test_supported_native_and_codex_schemas_accept_legacy_and_structured_findings(self):
        verdict = {"approved":True, "summary":"Reviewed", "findings":["Legacy plain text", FINDING,
            {**FINDING, "code_location":None}]}
        before = copy.deepcopy(REVIEW_VERDICT_SCHEMA)
        _validate_review_verdict(verdict)
        _validate_schema(verdict, _codex_schema(REVIEW_VERDICT_SCHEMA))
        self.assertEqual(REVIEW_VERDICT_SCHEMA, before)

    def test_structured_findings_reject_missing_unknown_or_invalid_location_fields(self):
        malformed = [
            {key:value for key,value in FINDING.items() if key != "code_location"},
            {**FINDING,"actor":"claimed reviewer"}, {**FINDING,"priority":"P4"},
            {**FINDING,"body":False},
            {**FINDING,"code_location":{"path":"maths.py"}},
            {**FINDING,"code_location":{"path":"maths.py","line_range":{"start":True,"end":2}}},
            {**FINDING,"code_location":{"path":"maths.py","line_range":{"start":0,"end":2}}},
            {**FINDING,"code_location":{"path":"maths.py","line_range":{"start":3,"end":2}}},
            {**FINDING,"code_location":{"path":"maths.py","line_range":{"start":2,"end":2,"commit":"invented"}}},
        ]
        for finding in malformed:
            with self.subTest(finding=finding), self.assertRaises(ValueError):
                _validate_review_verdict({"approved":True,"findings":[finding],"summary":"Reviewed"})

    def test_context_clipping_keeps_location_priority_title_and_legacy_normalization(self):
        value = {**FINDING,"body":"Long explanation " * 1000}
        clipped = findings([value])[0]
        self.assertLessEqual(len(clipped), 600)
        self.assertIn('"path": "maths.py"', clipped)
        self.assertIn('"start": 2', clipped)
        self.assertIn('"priority": "P3"', clipped)
        self.assertIn(FINDING["title"], clipped)
        legacy = {"file":"maths.py","issue":"Older arbitrary object"}
        self.assertEqual(findings(["legacy", legacy]), ["legacy", render_json(legacy)])


class ReviewFindingsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = fixtures.WorkflowTests.asyncTearDown
    check_project = fixtures.WorkflowTests.check_project
    request = fixtures.WorkflowTests.request
    settle = fixtures.WorkflowTests.settle

    def seeded_run(self):
        identifier = str(uuid4())
        spec = RunSpec(workspace=str(self.project), prompt="Fix addition")
        value = RunResult(run_id=identifier, status="running", spec=spec).model_dump()
        value["artifacts"] = {"directory":str(self.store.home / "runs" / identifier)}
        self.store.save(value)
        return identifier

    async def test_actual_review_persists_structured_and_text_findings_and_requests_known_locations(self):
        identifier = self.seeded_run()
        structured = {"approved":True,"findings":[FINDING,"Legacy note"],"summary":"Reviewed"}
        with patch.object(self.engine, "_provider", AsyncMock(return_value={"ok":True,"structured_output":structured})) as provider:
            review = await self.engine._assess_patch(identifier, Participant(provider="claude"), self.project,
                "Fix addition", {"title":"Addition"}, "integration", patch="diff --git a/maths.py b/maths.py\n")
        self.assertTrue(review["ok"])
        self.assertEqual(review["findings"], structured["findings"])
        self.assertEqual(self.store.get(identifier)["reviews"][0]["findings"], structured["findings"])
        packet = provider.await_args.args[3].render()
        self.assertIn("project-relative file path", packet)
        self.assertIn("Never invent or guess file locations", packet)
        self.assertEqual(provider.await_args.kwargs["schema"], REVIEW_VERDICT_SCHEMA)

    async def test_malformed_cli_finding_cannot_approve_and_is_retried_freshly_once(self):
        identifier = self.seeded_run()
        malformed = {"approved":True,"findings":[{**FINDING,"code_location":{"path":"maths.py","line_range":{"start":"2","end":2}}}],"summary":"Reviewed"}
        with patch.object(self.engine, "_provider", AsyncMock(return_value={"ok":True,"answer":json.dumps(malformed)})) as provider:
            review = await self.engine._assess_patch(identifier, Participant(provider="claude"), self.project,
                "Fix addition", {"title":"Addition"}, "integration")
        self.assertFalse(review["ok"])
        self.assertEqual(review["error"]["code"], "invalid_review")
        self.assertEqual(review["findings"], [])
        self.assertEqual(provider.await_count, 2)
        self.assertTrue(all("session_id" not in call.kwargs for call in provider.await_args_list))

    async def test_malformed_explicit_refusal_cannot_be_retried_into_same_candidate_approval(self):
        identifier = self.seeded_run()
        legacy = {"severity":"error", "file":"maths.py", "message":"Repair the empty-input acceptance case."}
        refused = {"approved":False,"findings":[legacy],"summary":"Acceptance case is not satisfied."}
        later_approval = {"approved":True,"findings":[],"summary":"Approved without another edit."}
        with patch.object(self.engine, "_provider", AsyncMock(side_effect=[
            {"ok":True,"structured_output":refused}, {"ok":True,"structured_output":later_approval},
        ])) as provider:
            review = await self.engine._assess_patch(identifier, Participant(provider="claude"), self.project,
                "Fix addition", {"title":"Addition"}, "integration")
        self.assertFalse(review["ok"])
        self.assertEqual(provider.await_count, 1)
        self.assertEqual(review["summary"], refused["summary"])
        self.assertEqual(review["error"]["code"], "invalid_review")
        self.assertIn(legacy["message"], review["findings"][0])
        self.assertIn(legacy["file"], review["findings"][0])
        self.assertEqual(self.store.get(identifier)["reviews"][0]["findings"], review["findings"])

    async def test_real_candidate_revision_includes_exact_selected_location(self):
        original = self.registry.run
        async def reviewer_with_location(provider, **kwargs):
            outcome = await original(provider, **kwargs)
            if kwargs.get("schema") and kwargs["mode"] != "coordinate":
                outcome["structured_output"] = {"approved":True,"findings":[FINDING],"summary":"Reviewed with an advisory."}
            return outcome
        with patch.object(self.registry, "run", side_effect=reviewer_with_location):
            started = await self.service.start(self.request())
            parent = await self.settle(started["id"])
        self.assertEqual(parent["status"], "awaiting_approval", parent["error"])
        run = self.store.get(parent["run_id"])
        self.assertEqual(run["reviews"][0]["findings"][0], FINDING)
        with patch.object(self.service, "_launch", AsyncMock()):
            child = await self.service.revise(parent["id"], RevisionRequest(request_id=uuid4(),
                candidate_digest=parent["candidate"]["digest"], correction="Explain the corrected operation.",
                findings=[FindingSelection(review=0,finding=0)]))
        self.assertEqual(child["revision"]["findings"], [FINDING])
        self.assertIn(json.dumps([FINDING]), child["spec"]["prompt"])
        self.assertEqual(child["revision"]["parent_digest"], parent["candidate"]["digest"])

