"""Recorded rejection and missing duration are not measured approvals or zeros."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from parallax.pilot import Pilot
from parallax.store import Store


class MeasurementSemanticsTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name))
        self.run = {"run_id":"run", "status":"completed", "spec":{"workspace":"/fixture"},
                    "artifacts":{}, "checks":[]}
        self.store.save(self.run)
        self.workflow = {"id":"workflow", "run_id":"run", "status":"rejected",
                         "spec":{"workspace":"/fixture"},
                         "candidate":{"captured_at":"2026-10-09T12:00:00+00:00"},
                         "decision":{"action":"reject", "at":"2026-10-09T12:00:05+00:00"}}
        self.pilot = Pilot(SimpleNamespace(store=self.store,
            listing=lambda:[{"id":"workflow"}], get=lambda _:self.workflow, check_workspace=lambda _:None))

    def outcome(self):
        return self.pilot.report()["outcomes"][0]

    def test_rejection_does_not_count_as_approval_latency(self):
        self.assertIsNone(self.outcome()["approval_seconds"])
        self.workflow["decision"]["action"] = "approve"
        self.assertEqual(self.outcome()["approval_seconds"], 5)

    def test_missing_runtime_is_unknown_and_recorded_zero_is_preserved(self):
        self.assertIsNone(self.outcome()["execution_seconds"])
        self.run["artifacts"]["runtime_seconds"] = 0
        self.store.save(self.run)
        self.assertEqual(self.outcome()["execution_seconds"], 0)

    def test_pending_decision_has_no_approval_latency(self):
        self.workflow["decision"] = None
        self.assertIsNone(self.outcome()["approval_seconds"])


if __name__ == '__main__':
    unittest.main()
