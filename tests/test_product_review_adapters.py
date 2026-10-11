"""Independently verify real review contracts through provider and packet adapters."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from parallax.api_agent import _validate_schema
from parallax.context import findings, render_json
from parallax.engine import Engine
from parallax.models import Participant, RunResult, RunSpec
from parallax.providers import _codex_schema
from parallax.store import Store

from test_engine import FakeRegistry


class ReviewAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "candidate"
        self.target.mkdir()
        (self.target / "average.py").write_text("def average(values):\n    return sum(values) / len(values)\n")
        self.store = Store(self.root / "state")
        self.engine = Engine(self.store, FakeRegistry())
        self.run_id = str(uuid4())
        run = RunResult(run_id=self.run_id, status="reviewing", spec=RunSpec(workspace=str(self.target), prompt="Reject empty input")).model_dump()
        run["artifacts"]["directory"] = str(self.root / "run")
        self.store.save(run)

    async def asyncTearDown(self):
        await self.engine.shutdown()

    def finding(self):
        return {"title": "Reject empty input", "body": "The empty sequence must raise an explicit error.", "priority": "P1",
                "code_location": {"path": "average.py", "line_range": {"start": 2, "end": 2}}}

    async def assess(self, payload, *, following=None):
        responses = [{"ok": True, "structured_output": value, "answer": json.dumps(value), "error": None}
                     for value in [payload, *(following or [])]]
        provider = AsyncMock(side_effect=responses) if following is not None else AsyncMock(return_value=responses[0])
        with patch.object(self.engine, "_provider", provider):
            result = await self.engine._assess_patch(self.run_id, Participant(provider="claude", role="reviewer"), self.target,
                "Reject empty input", {"acceptance": ["Empty input raises ValueError"]}, "integration",
                patch="diff --git a/average.py b/average.py\n--- a/average.py\n+++ b/average.py\n@@ -1,2 +1,4 @@\n def average(values):\n+    if not values:\n+        raise ValueError('empty input')\n     return sum(values) / len(values)\n")
        return result, provider

    async def schema(self):
        _, provider = await self.assess({"approved": True, "findings": [], "summary": "Passed"})
        return provider.await_args.kwargs["schema"]

    async def test_actual_review_schema_supports_legacy_structured_and_unknown_locations_in_both_adapters(self):
        schema = await self.schema()
        normalized = _codex_schema(schema)
        self.assertEqual(schema, await self.schema(), "Codex normalization must not mutate the runtime's contract")
        unknown = self.finding()
        unknown["code_location"] = None
        for candidate in (schema, normalized):
            for value in ([], ["Existing plain finding"], [self.finding()], [unknown], ["Legacy", self.finding(), unknown]):
                with self.subTest(codex=candidate is normalized, value=value):
                    _validate_schema({"approved": True, "findings": value, "summary": "Recorded review"}, candidate)
        def inspect(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)
        inspect(normalized)

    async def test_provider_adapters_refuse_unknown_fields_and_invalid_line_types(self):
        schema = await self.schema()
        malformed = []
        extra = self.finding(); extra["filesystem_write"] = "untrusted"; malformed.append(extra)
        missing = self.finding(); missing.pop("body"); malformed.append(missing)
        for line in (True, 0, -1, 1.5, "2"):
            value = self.finding(); value["code_location"]["line_range"]["start"] = line; malformed.append(value)
        for candidate in (schema, _codex_schema(schema)):
            for value in malformed:
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        _validate_schema({"approved": True, "findings": [value], "summary": "Invalid"}, candidate)

    async def test_cli_success_claim_with_malformed_finding_cannot_approve_the_candidate(self):
        malformed = self.finding()
        malformed["code_location"]["line_range"] = {"start": 10, "end": 2}
        result, provider = await self.assess({"approved": True, "findings": [malformed], "summary": "Claims success"})
        self.assertFalse(result["ok"])
        self.assertEqual(provider.await_count, 2, "One fresh correction attempt follows a malformed review")
        self.assertIsNotNone(result["error"])
        self.assertFalse(self.store.get(self.run_id)["reviews"][-1]["ok"])

    async def test_explicit_refusal_is_not_replaced_by_an_approval_during_format_retry(self):
        refused = {"approved": False, "findings": [{"file": "average.py", "issue": "Empty input remains broken"}],
                   "summary": "Do not approve this candidate"}
        approved = {"approved": True, "findings": [], "summary": "Claims approval without a repair"}
        result, provider = await self.assess(refused, following=[approved])
        self.assertFalse(result["ok"], "An explicit review refusal must survive malformed finding format")
        self.assertEqual(provider.await_count, 1, "The next action must repair the candidate, not ask a second reviewer to approve the same bytes")
        self.assertEqual(result["summary"], refused["summary"])
        self.assertEqual(result["error"]["code"], "invalid_review")
        self.assertIn("average.py", "\n".join(result["findings"]))
        self.assertIn("Empty input remains broken", "\n".join(result["findings"]))
        self.assertFalse(self.store.get(self.run_id)["reviews"][-1]["ok"])

    async def test_nonboolean_false_like_values_still_require_a_valid_review_verdict(self):
        approved = {"approved": True, "findings": [], "summary": "Valid fresh review"}
        for value in (0, None, "false"):
            with self.subTest(value=value):
                malformed = {"approved": value, "findings": [], "summary": "Malformed approval value"}
                result, provider = await self.assess(malformed, following=[approved])
                self.assertEqual(provider.await_count, 2)
                self.assertTrue(result["ok"])
                self.assertEqual(result["summary"], approved["summary"])

    async def test_structured_location_reaches_saved_evidence_and_bounded_repair_context(self):
        value = self.finding()
        result, _ = await self.assess({"approved": False, "findings": [value, "Legacy finding"], "summary": "Changes requested"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["findings"], [value, "Legacy finding"])
        self.assertEqual(self.store.get(self.run_id)["reviews"][-1]["findings"], [value, "Legacy finding"])
        long = self.finding()
        long["body"] = "Detailed concern. " * 400
        for budget in (300, 600):
            brief = findings([long], each=budget)[0]
            self.assertLessEqual(len(brief), budget)
            self.assertIn("average.py", brief)
            self.assertIn("Reject empty input", brief)
            self.assertIn("P1", brief)
            self.assertRegex(brief, r"2(?:[–:-]2)?")
        legacy = {"file": "legacy.py", "issue": "Legacy arbitrary object"}
        self.assertEqual(findings(["Legacy finding", legacy]), ["Legacy finding", render_json(legacy)])
