"""Actual Engine dispatch stops futile quota loops without blocking alternatives."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from parallax.engine import Engine
from parallax.models import CheckSpec, Limits, Participant, RunSpec
from parallax.recovery import recovery_options
from parallax.store import Store
from test_engine import git


class QuotaRegistry:
    def __init__(self, *, alternate=False, error=None):
        self.calls = []
        self.turn = 0
        self.error = error or {"code": "provider_error", "message": "Individual quota reached. Resets in 12h59m36s."}
        def plan(identifier, provider):
            return {"id": "plan-" + identifier, "action": "plan", "tasks": [{"id": identifier, "title": "Fix addition", "provider": provider, "prompt": "Correct addition", "files": ["maths.py"], "acceptance": ["2+3 returns 5"]}]}
        self.actions = [plan("fix", "antigravity"), {"id": "dispatch-fix", "action": "dispatch", "task_ids": ["fix"]}]
        if alternate:
            self.actions += [plan("replacement", "claude"),
                {"id": "dispatch-replacement", "action": "dispatch", "task_ids": ["replacement"]},
                {"id": "validate", "action": "validate"},
                {"id": "resolve", "action": "resolve_task", "task_ids": ["fix"], "selected_task": "replacement"},
                {"id": "integrate", "action": "request_integration"},
                {"id": "finish", "action": "finish", "summary": "Alternate implementation verified"}]

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
        if kwargs["mode"] == "edit" and provider == "antigravity":
            return {"ok": False, "error": self.error, "exit_code": 3, "diagnostics": self.error["message"], "session_id": None}
        if kwargs["mode"] == "edit":
            (kwargs["workspace"] / "maths.py").write_text("def add(a, b):\n    return a + b\n")
            return {"ok": True, "answer": "Corrected addition", "session_id": None}
        verdict = {"approved": True, "findings": [], "summary": "Independent compatibility review passed"}
        return {"ok": True, "answer": json.dumps(verdict), "structured_output": verdict, "session_id": None}


class SoleImplementerQuotaTests(unittest.IsolatedAsyncioTestCase):
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
        (self.project / "notes.txt").write_text("Unrelated staged work")
        git(self.project, "add", "notes.txt")
        self.index = git(self.project, "diff", "--cached")
        self.original = (self.project / "maths.py").read_bytes()
        self.store = Store(self.root / "state")

    def spec(self, *, alternate=False, reviewer=False):
        team = [Participant(provider="antigravity", role="implementer")]
        if alternate:
            team.append(Participant(provider="claude", role="implementer"))
        if reviewer:
            team.append(Participant(provider="grok", role="reviewer"))
        return RunSpec(workspace=str(self.project), prompt="Fix addition", integrate=False, team=team,
            checks=[CheckSpec(name="addition", argv=[sys.executable, "-B", "check.py"])],
            limits=Limits(workers=1, repairs=1 if alternate else 0, minutes=1, attempt_seconds=10, coordinator_turns=10 if alternate else 4))

    async def finish(self, engine, run_id):
        job = engine.jobs[run_id]
        await asyncio.wait_for(job, 30)
        await asyncio.sleep(0)
        return self.store.get(run_id)

    def preserved(self, result):
        self.assertEqual((self.project / "maths.py").read_bytes(), self.original)
        self.assertEqual(git(self.project, "diff", "--cached"), self.index)
        self.assertFalse(result["artifacts"].get("integration_applied"))

    async def test_sole_quota_failure_stops_before_more_coordinator_calls_and_preserves_budget(self):
        registry = QuotaRegistry()
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec())
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(registry.calls, [("codex", "coordinate"), ("codex", "coordinate"), ("antigravity", "edit")])
        self.assertEqual(result["artifacts"]["coordinator_turns"], 2)
        self.assertEqual(result["tasks"][0]["status"], "failed")
        self.assertEqual(result["tasks"][0]["attempts"], 1)
        self.assertGreater(result["artifacts"]["runtime_seconds"], 0)
        self.assertIn("exhausted its provider quota", result["errors"][-1]["message"])
        self.assertEqual(result["errors"][-1]["category"], "provider_quota")
        self.assertEqual(len([event for event in self.store.events(started["run_id"]) if event["kind"] == "provider_exhausted"]), 1)
        self.assertEqual(self.store.actions(started["run_id"])[-1]["state"], "failed")
        self.preserved(result)
        # Explicit recovery is available, and its original limits/attempts stay intact.
        self.assertIn("retry_interrupted", [action["id"] for action in recovery_options(result)["actions"]])
        used = result["artifacts"]["runtime_seconds"]
        baseline = result["artifacts"]["baseline_snapshot_sha256"]
        engine.recover_run(started["run_id"], "retry_interrupted")
        resumed = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("antigravity", "edit")), 1)
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 4)
        self.assertGreaterEqual(resumed["artifacts"]["runtime_seconds"], used)
        self.assertEqual(resumed["artifacts"]["baseline_snapshot_sha256"], baseline)
        self.assertEqual(resumed["spec"]["limits"]["repairs"], 0)
        self.assertEqual(resumed["tasks"][0]["attempts"], 1)
        self.preserved(resumed)

    async def test_reviewer_slot_is_not_an_alternate_writer(self):
        registry = QuotaRegistry()
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec(reviewer=True))
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 2)
        self.assertNotIn(("grok", "edit"), registry.calls)
        self.assertIn("exhausted its provider quota", result["errors"][-1]["message"])
        self.preserved(result)

    async def test_explicit_quota_error_code_stops_without_provider_specific_text(self):
        registry = QuotaRegistry(error={"code": "insufficient_quota", "message": "Provider allocation is unavailable"})
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec())
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 2)
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("exhausted its provider quota", result["errors"][-1]["message"])
        self.preserved(result)

    async def test_authorized_alternate_writer_can_complete_verified_replacement(self):
        registry = QuotaRegistry(alternate=True)
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec(alternate=True))
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(registry.calls.count(("antigravity", "edit")), 1)
        self.assertEqual(registry.calls.count(("claude", "edit")), 1)
        self.assertEqual(result["tasks"][0]["status"], "resolved")
        self.assertTrue(result["artifacts"]["verified_only"])
        self.assertFalse(any(event["kind"] == "provider_exhausted" for event in self.store.events(started["run_id"])))
        self.assertTrue(all(check["ok"] for check in result["checks"]))
        self.preserved(result)

    async def test_generic_429_rate_limit_is_not_terminal_quota(self):
        registry = QuotaRegistry(error={"code": "rate_limit_exceeded", "message": "RESOURCE_EXHAUSTED HTTP429; requests per minute exceeded, retry later"})
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec())
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 4)
        self.assertNotIn("exhausted its provider quota", result["errors"][-1]["message"])
        self.assertFalse(any(event["kind"] == "provider_exhausted" for event in self.store.events(started["run_id"])))
        self.preserved(result)

    async def test_rate_limit_code_takes_precedence_over_quota_wording(self):
        registry = QuotaRegistry(error={"code": "rate_limit_exceeded", "message": "HTTP429: individual quota exceeded; request allocation retries after 1s"})
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec())
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 4)
        self.assertFalse(any(event["kind"] == "provider_exhausted" for event in self.store.events(started["run_id"])))
        self.preserved(result)

    async def test_ambiguous_per_minute_quota_wording_is_not_terminal(self):
        registry = QuotaRegistry(error={"code": "provider_error", "message": "HTTP429: per-minute quota exceeded; retry after 1s"})
        engine = Engine(self.store, registry, memory=False)
        started = await engine.start(self.spec())
        result = await self.finish(engine, started["run_id"])
        self.assertEqual(registry.calls.count(("codex", "coordinate")), 4)
        self.assertFalse(any(event["kind"] == "provider_exhausted" for event in self.store.events(started["run_id"])))
        self.preserved(result)
