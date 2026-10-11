"""Durable native audit diagnostics never import raw hook payloads or pass gates."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from parallax.engine import Engine, _boundary_evidence, _handoff
from parallax.models import Participant, RunResult, RunSpec
from parallax.recovery import recovery_options
from parallax.store import Store


class OutcomeRegistry:
    def __init__(self, outcome):
        self.outcome = outcome

    async def run(self, provider, **kwargs):
        return copy.deepcopy(self.outcome)


class BoundaryDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name) / "project"
        self.project.mkdir()
        self.store = Store(Path(folder.name) / "state")

    async def invoke(self, outcome):
        engine = Engine(self.store, OutcomeRegistry(outcome), memory=False)
        run_id = str(uuid4())
        spec = RunSpec(workspace=str(self.project), prompt="Bounded migration")
        result = RunResult(run_id=run_id,status="needs_attention",spec=spec).model_dump()
        result["artifacts"] = {"runtime_seconds":12.34,"consumed_budget_marker":"retained"}
        self.store.save(result)
        engine.cancel_flags[run_id] = asyncio.Event()
        returned = await engine._provider(run_id,Participant(provider="antigravity"),self.project,"Inspect the assigned task",
                                          mode="edit",task_id="migration",attempt=1)
        return self.store.get(run_id), returned

    async def test_success_and_guard_failure_retain_safe_audit_without_acceptance_or_budget_change(self):
        audit = {"pre_tool_gate":[
            {"tool":"view_file","decision":"allow","path":"/PRIVATE-SCRATCH-PATH","arguments":{"token":"PRIVATE-TOKEN"}},
            {"tool":"write_to_file","decision":"deny","raw_log":"PRIVATE-AUDIT-LOG"},
            {"tool":"PRIVATE-TOOL-SECRET","decision":"deny"}],
            "scratch_path":"/PRIVATE-SCRATCH-PATH","raw_audit":"PRIVATE-AUDIT-LOG","token":"PRIVATE-TOKEN"}
        for succeeded in (True,False):
            with self.subTest(succeeded=succeeded):
                outcome = {"ok":succeeded,"answer":"","boundary_evidence":audit,
                           "error":None if succeeded else {"code":"unsafe_configuration","message":"Adapter rejected an unsupported tool"}}
                saved, returned = await self.invoke(outcome)
                recorded = saved["sessions"][0]["boundary_evidence"]
                self.assertEqual(recorded["pre_tool_gate"],[{"tool":"view_file","decision":"allow"},
                    {"tool":"write_to_file","decision":"deny"},{"tool":"unrecognized","decision":"deny"}])
                self.assertEqual(recorded["pre_tool_gate_status"],"observed")
                self.assertEqual(recorded["pre_tool_gate_counts"]["deny"],2)
                self.assertEqual(_handoff(returned)["boundary_evidence"],recorded)
                serialized = json.dumps({"sessions":saved["sessions"],"handoff":_handoff(returned)})
                for private in ("PRIVATE-SCRATCH-PATH","PRIVATE-AUDIT-LOG","PRIVATE-TOKEN","PRIVATE-TOOL-SECRET"):
                    self.assertNotIn(private,serialized)
                self.assertEqual(saved["artifacts"],{"runtime_seconds":12.34,"consumed_budget_marker":"retained"})
                self.assertEqual(saved["status"],"needs_attention")
                self.assertEqual(saved["checks"],[])
                self.assertEqual(saved["reviews"],[])
                if not succeeded:
                    self.assertEqual(saved["errors"][-1]["category"],"configuration")
                    self.assertEqual(recovery_options(saved)["actions"][0]["id"],"fix_configuration")

    async def test_timeout_with_empty_audit_is_unrecorded_and_still_failure(self):
        saved, returned = await self.invoke({"ok":False,"error":{"code":"timeout","message":"Provider exceeded 120 seconds"},
                                             "boundary_evidence":{"pre_tool_gate":[]}})
        audit = saved["sessions"][0]["boundary_evidence"]
        self.assertEqual(audit["pre_tool_gate_status"],"unrecorded")
        self.assertEqual(audit["pre_tool_gate_counts"]["reported"],0)
        self.assertFalse(returned["ok"])
        self.assertEqual(saved["errors"][-1]["provider_error_code"],"timeout")
        self.assertEqual(_handoff(returned)["boundary_evidence"],audit)

    async def test_absent_audit_does_not_invent_provider_boundary_proof(self):
        saved, returned = await self.invoke({"ok":True,"answer":"Inspection complete"})
        self.assertNotIn("boundary_evidence",saved["sessions"][0])
        self.assertNotIn("boundary_evidence",_handoff(returned))

    def test_large_or_malformed_audits_are_bounded_and_never_labelled_enforced(self):
        audit = _boundary_evidence({"pre_tool_gate":[{"tool":"view_file","decision":"allow","secret":"PRIVATE"}]*300})
        self.assertEqual(len(audit["pre_tool_gate"]),256)
        self.assertTrue(audit["truncated"])
        self.assertEqual(audit["pre_tool_gate_counts"]["reported"],300)
        self.assertEqual(audit["pre_tool_gate_counts"]["retained"],256)
        self.assertNotIn("PRIVATE",json.dumps(audit))
        self.assertEqual(_boundary_evidence({"pre_tool_gate":"PRIVATE"})["pre_tool_gate_status"],"invalid")
        malformed = _boundary_evidence({"pre_tool_gate":[None,{"tool":"view_file","decision":"PRIVATE"}]})
        self.assertEqual(malformed["pre_tool_gate_status"],"invalid")
        self.assertNotIn("PRIVATE",json.dumps(malformed))
        self.assertNotIn("enforced",json.dumps(audit))


if __name__ == "__main__":
    unittest.main()
