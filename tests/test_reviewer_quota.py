"""An exhausted independent reviewer is skipped when another exists and stops the run when none does."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from parallax.engine import Engine
from parallax.models import CheckSpec, Limits, Participant, RunSpec
from parallax.recovery import classify, provider_quota_exhausted, recovery_options
from parallax.store import Store
from test_engine import git

QUOTA = {"code": "provider_error", "message": "Individual quota reached. Resets in 150h1m4s."}


class ReviewerQuotaRegistry:
    def __init__(self, error=None, healthy_reviews=0):
        self.calls = []
        self.healthy_reviews = healthy_reviews
        self.turn = 0
        self.error = error or QUOTA
        self.actions = [
            {"id": "plan-fix", "action": "plan", "tasks": [{"id": "fix", "title": "Fix addition", "provider": "codex", "prompt": "Correct addition", "files": ["maths.py"], "acceptance": ["2+3 returns 5"]}]},
            {"id": "dispatch-fix", "action": "dispatch", "task_ids": ["fix"]},
            {"id": "validate", "action": "validate"},
            {"id": "integrate", "action": "request_integration"},
            {"id": "finish", "action": "finish", "summary": "Verified"}]

    async def discover(self):
        return []

    def validate(self, participant):
        return {"provider": participant.provider, "model": "fixture", "effort": "high"}

    async def run(self, provider, **kwargs):
        self.calls.append((provider, kwargs["mode"]))
        if kwargs["mode"] == "coordinate":
            action = self.actions[self.turn] if self.turn < len(self.actions) else {"id": f"inspect-{self.turn}", "action": "inspect_results"}
            self.turn += 1
            return {"ok": True, "answer": json.dumps(action), "structured_output": action, "session_id": None}
        if kwargs["mode"] == "edit":
            (kwargs["workspace"] / "maths.py").write_text("def add(a, b):\n    return a + b\n")
            return {"ok": True, "answer": "Corrected addition", "session_id": None}
        if provider == "antigravity" and self.reviews("antigravity") > self.healthy_reviews:
            return {"ok": False, "error": self.error, "exit_code": 3, "diagnostics": self.error["message"], "session_id": None}
        verdict = {"approved": True, "findings": [], "summary": "Independent review passed"}
        return {"ok": True, "answer": json.dumps(verdict), "structured_output": verdict, "session_id": None}

    def reviews(self, provider):
        return len([call for call in self.calls if call[0] == provider and call[1] not in {"coordinate", "edit"}])


class ReviewerQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        git(self.project, "init", "-q")
        git(self.project, "config", "user.name", "Fixture")
        git(self.project, "config", "user.email", "fixture@example.com")
        (self.project / "maths.py").write_text("def add(a, b):\n    return a - b\n")
        (self.project / "check.py").write_text("from maths import add\nassert add(2, 3) == 5\n")
        git(self.project, "add", ".")
        git(self.project, "commit", "-qm", "Baseline")
        self.original = (self.project / "maths.py").read_bytes()
        self.store = Store(self.root / "state")

    def spec(self, *reviewers):
        team = [Participant(provider="codex", role="implementer"), *[Participant(provider=name, role="reviewer") for name in reviewers]]
        return RunSpec(workspace=str(self.project), prompt="Fix addition", integrate=False, team=team,
            checks=[CheckSpec(name="addition", argv=[sys.executable, "-B", "check.py"])],
            limits=Limits(workers=1, repairs=1, minutes=1, attempt_seconds=10, coordinator_turns=8))

    async def finish(self, engine, run_id):
        await asyncio.wait_for(engine.jobs[run_id], 30)
        await asyncio.sleep(0)
        return self.store.get(run_id)

    async def test_sole_reviewer_quota_stops_with_provider_quota_recovery(self):
        registry = ReviewerQuotaRegistry()
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec("antigravity"))
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(result["status"], "needs_attention")
        # The futile review is not retried and the coordinator gets no further turn after the stop.
        self.assertEqual(registry.reviews("antigravity"), 1)
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 2)
        error = result["errors"][-1]
        self.assertIn("Every independent reviewer exhausted its provider quota (antigravity)", error["message"])
        self.assertEqual(error["category"], "provider_quota")
        options = recovery_options(result)
        self.assertEqual(options["category"], "provider_quota")
        self.assertIn("retry_interrupted", [action["id"] for action in options["actions"]])
        events = [event for event in self.store.events(started["run_id"]) if event["kind"] == "provider_exhausted"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["provider"], "antigravity")
        self.assertEqual((self.project / "maths.py").read_bytes(), self.original)

    async def test_quota_during_final_review_stops_instead_of_spending_coordinator_turns(self):
        # The live failure: task review passed, then the only independent reviewer ran out before the combined review.
        registry = ReviewerQuotaRegistry(healthy_reviews=1)
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec("antigravity"))
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(registry.reviews("antigravity"), 2)
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 3)
        self.assertEqual(result["errors"][-1]["category"], "provider_quota")
        self.assertEqual(recovery_options(result)["category"], "provider_quota")
        self.assertFalse(result["artifacts"].get("validated_fingerprint"))

    async def test_exhausted_reviewer_is_skipped_for_the_rest_of_the_run(self):
        registry = ReviewerQuotaRegistry()
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec("antigravity", "grok"))
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(result["status"], "completed", result["errors"])
        # Task review falls through to grok; the final combined review never asks antigravity again.
        self.assertEqual(registry.reviews("antigravity"), 1)
        self.assertEqual(registry.reviews("grok"), 2)
        self.assertEqual({review["provider"] for review in result["reviews"] if review["ok"]}, {"grok"})
        self.assertTrue(all(check["ok"] for check in result["checks"]))

    async def test_rate_limit_from_reviewer_is_not_quota(self):
        registry = ReviewerQuotaRegistry(error={"code": "rate_limit_exceeded", "message": "HTTP429: individual quota exceeded; retry after 1s"})
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec("antigravity", "grok"))
        result = await self.finish(engine, started["run_id"])
        self.assertFalse(any(event["kind"] == "provider_exhausted" for event in self.store.events(started["run_id"])))
        self.assertNotIn("exhausted its provider quota", " ".join(error["message"] for error in result["errors"]))


class QuotaClassificationTests(unittest.TestCase):
    def test_quota_wording_and_codes(self):
        self.assertTrue(provider_quota_exhausted({"code": "insufficient_quota", "message": ""}))
        self.assertTrue(provider_quota_exhausted("Claude usage limit reached. Resets at 5pm."))
        self.assertFalse(provider_quota_exhausted({"code": "rate_limited", "message": "account quota exceeded"}))
        self.assertFalse(provider_quota_exhausted("HTTP429: per-minute quota exceeded; retry after 1s"))
        self.assertEqual(classify("Individual quota reached. Resets in 150h."), "provider_quota")

    def test_post_run_memory_failure_does_not_replace_the_stop_cause(self):
        # Recorded shape of the October 12 run: the distiller failed after the coordinator limit stopped it.
        result = {"status": "needs_attention", "spec": {"mode": "build"}, "tasks": [], "artifacts": {},
                  "errors": [{"code": "run_blocked", "category": "configuration", "message": "Coordinator decision limit reached; work and evidence are preserved"},
                             {"code": "provider_failure", "provider": "antigravity", "task_id": "distill", "category": "configuration",
                              "message": "Individual quota reached. Resets in 150h25m7s."}]}
        options = recovery_options(result)
        self.assertEqual(options["category"], "configuration")
        self.assertIn("Coordinator decision limit", options["message"])


if __name__ == "__main__":
    unittest.main()
