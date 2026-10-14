"""Readiness warns about a selected provider that recently ran out of plan quota."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from parallax.engine import Engine
from parallax.store import Store
from test_engine import FakeRegistry


class QuotaPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.engine = Engine(self.store, FakeRegistry(), memory=False)
        self.now = datetime.now(timezone.utc)

    def event(self, kind, data, ago):
        with self.store.connect() as db:
            db.execute("INSERT INTO events(run_id,timestamp,kind,task_id,data) VALUES(?,?,?,?,?)",
                       ("run", (self.now - ago).isoformat(), kind, None, json.dumps(data)))

    def failure(self, provider, message, ago, code="provider_error"):
        self.event("provider_failure", {"provider": provider, "provider_error_code": code, "message": message}, ago)

    def test_stated_reset_in_the_future_warns_with_the_reset_time(self):
        self.failure("antigravity", "Individual quota reached. Resets in 150h0m0s.", timedelta(hours=6))
        self.event("provider_exhausted", {"provider": "antigravity", "reason": "quota"}, timedelta(hours=6) - timedelta(seconds=1))
        [warning] = self.engine._quota_warnings({"antigravity", "codex"})
        self.assertEqual((warning["severity"], warning["category"], warning["provider"]), ("warning", "provider_quota", "antigravity"))
        reset = self.now - timedelta(hours=6) + timedelta(hours=150)
        self.assertIn(f"resets around {reset:%b} {reset.day}", warning["message"])

    def test_passed_reset_unselected_provider_and_rate_limits_do_not_warn(self):
        self.failure("antigravity", "Individual quota reached. Resets in 1h0m0s.", timedelta(hours=3))
        self.failure("claude", "Claude usage limit reached. Resets in 2h.", timedelta(minutes=10))
        self.failure("codex", "individual quota exceeded; retry after 1s", timedelta(minutes=5), code="rate_limit_exceeded")
        self.assertEqual(self.engine._quota_warnings({"antigravity", "codex"}), [])

    def test_unstated_reset_warns_only_for_a_day(self):
        self.failure("claude", "Claude usage limit reached.", timedelta(hours=2))
        self.assertIn("did not say when", self.engine._quota_warnings({"claude"})[0]["message"])
        self.store = Store(Path(self.temp.name) / "other"); self.engine = Engine(self.store, FakeRegistry(), memory=False)
        self.failure("claude", "Claude usage limit reached.", timedelta(hours=30))
        self.assertEqual(self.engine._quota_warnings({"claude"}), [])

    def test_native_clock_reset_expires_from_the_recorded_failure_time(self):
        from unittest.mock import patch
        from parallax.recovery import quota_reset_after
        observed = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)
        message = "You've hit your session limit · resets 8:30pm (America/Detroit)"
        self.assertEqual(quota_reset_after(message, observed_at=observed), 3.5 * 3600)
        self.failure("claude", message, self.now - observed)
        with patch("datetime.datetime") as clock:
            clock.now.return_value = observed + timedelta(hours=1)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            [warning] = self.engine._quota_warnings({"claude"})
            self.assertIn("Oct 15, 00:30 UTC", warning["message"])
            clock.now.return_value = observed + timedelta(hours=4)
            self.assertEqual(self.engine._quota_warnings({"claude"}), [])

    def test_unknown_reset_format_keeps_the_provider_message(self):
        self.failure("claude", "You've hit your weekly limit · resets Oct 19 at 8am (America/Detroit)", timedelta(minutes=5))
        [warning] = self.engine._quota_warnings({"claude"})
        self.assertIn("resets Oct 19 at 8am", warning["message"])
        self.assertNotIn("did not say when", warning["message"])


if __name__ == "__main__":
    unittest.main()
