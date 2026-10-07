"""Context isolation, session policy, and the engine fixes they depend on.

Fixtures are borrowed from EngineTests by attribute (as test_delivery.py does)
so these tests never re-run the engine suite.
"""
import asyncio
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch
from parallax.engine import Engine
from parallax.models import CoordinatorAction
import test_engine
from test_engine import FakeRegistry


class RecordingRegistry(FakeRegistry):
    """FakeRegistry that records every call's mode, prompt, session, and workspace."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.records = []

    async def run(self, provider, **kwargs):
        self.records.append({"provider": provider, "mode": kwargs["mode"], "prompt": kwargs["prompt"],
                             "session_id": kwargs.get("session_id"), "workspace": kwargs["workspace"],
                             "model": kwargs.get("model"), "schema": kwargs.get("schema")})
        return await super().run(provider, **kwargs)

    def prompts(self, mode=None, schema=None):
        return [r["prompt"] for r in self.records if (mode is None or r["mode"] == mode)
                and (schema is None or bool(r["schema"]) == schema)]


class EngineFixesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec
    seed = test_engine.EngineTests.seed
    task = test_engine.EngineTests.task

    def engine(self, registry, run_id):
        engine = Engine(self.store, registry)
        engine.cancel_flags[run_id] = asyncio.Event()
        return engine

    async def test_integration_review_sees_the_checks_just_run(self):
        run_id, spec, manager = self.seed()
        registry = RecordingRegistry()
        engine = self.engine(registry, run_id)
        task = self.task(); task["status"] = "completed"
        result = self.store.get(run_id); result["tasks"] = [task]
        result["checks"] = [{"name": "Stale", "ok": False, "output": "STALE-OUTPUT"}]
        self.store.save(result)
        fresh = [{"name": "Addition check", "ok": True, "argv": [sys.executable, "-B", "check.py"], "output": "CANARY-FRESH-CHECK"}]
        with patch.object(engine, "_checks", new=AsyncMock(return_value=fresh)):
            await engine._verify(run_id, spec, manager, spec.checks)
        reviews = [p for p in registry.prompts(schema=True) if "Combined integration" in p]
        self.assertEqual(len(reviews), 1)
        self.assertIn("CANARY-FRESH-CHECK", reviews[0])
        self.assertNotIn("STALE-OUTPUT", reviews[0])

    async def test_merge_conflict_fails_the_attempt_and_counts_against_repairs(self):
        run_id, spec, manager = self.seed()
        engine = self.engine(RecordingRegistry(), run_id)
        result = self.store.get(run_id); result["tasks"] = [self.task()]; self.store.save(result)
        real_merge = manager.merge
        calls = []
        def merge(path):
            calls.append(Path(path).name)
            return {"ok": False, "error": "CONFLICT (content): maths.py"} if len(calls) == 1 else real_merge(path)
        with patch.object(manager, "merge", side_effect=merge):
            await engine._action(run_id, spec, manager, CoordinatorAction(id="d1", action="dispatch", task_ids=["fix"]))
            saved = self.store.get(run_id)["tasks"][0]
            self.assertEqual(saved["status"], "failed")
            self.assertFalse(saved["result"]["ok"])
            self.assertIn("Merge conflict", saved["result"]["error"])
            self.assertEqual(saved["active_attempt"]["state"], "merge_failed")
            await engine._action(run_id, spec, manager, CoordinatorAction(id="d2", action="dispatch", task_ids=["fix"]))
        saved = self.store.get(run_id)["tasks"][0]
        self.assertEqual(calls, ["fix-1", "fix-2"])
        self.assertEqual((saved["status"], saved["attempts"]), ("completed", 2))

    async def test_merge_conflict_redispatch_respects_the_repair_limit(self):
        run_id, spec, manager = self.seed()
        spec.limits.repairs = 0
        result = self.store.get(run_id); result["spec"] = spec.model_dump(); result["tasks"] = [self.task()]; self.store.save(result)
        engine = self.engine(RecordingRegistry(), run_id)
        with patch.object(manager, "merge", return_value={"ok": False, "error": "conflict"}):
            await engine._action(run_id, spec, manager, CoordinatorAction(id="d1", action="dispatch", task_ids=["fix"]))
            with self.assertRaisesRegex(ValueError, "repair limit"):
                await engine._action(run_id, spec, manager, CoordinatorAction(id="d2", action="dispatch", task_ids=["fix"]))

    async def test_failed_attempt_interrupted_before_bookkeeping_is_not_rerun(self):
        run_id, spec, manager = self.seed()
        result = self.store.get(run_id); result["tasks"] = [self.task()]; self.store.save(result)
        failing = self.engine(RecordingRegistry(fail_review=True), run_id)
        outcome = await failing._worker(run_id, spec, manager, self.store.get(run_id)["tasks"][0])
        self.assertFalse(outcome["ok"])
        # The runtime crashed before the dispatch loop recorded the failure.
        result = self.store.get(run_id); result["tasks"][0]["status"] = "interrupted"; self.store.save(result)
        registry = RecordingRegistry()
        again = await self.engine(registry, run_id)._worker(run_id, spec, manager, self.store.get(run_id)["tasks"][0])
        self.assertFalse(again["ok"])
        self.assertEqual(registry.prompts(mode="edit"), [])
        self.assertEqual(self.store.get(run_id)["tasks"][0]["attempts"], 1)

    async def test_stale_running_tasks_become_interrupted_before_reconciliation(self):
        run_id, spec, manager = self.seed()
        task = self.task(); task["status"] = "running"
        result = self.store.get(run_id); result["tasks"] = [task]; self.store.save(result)
        Engine(self.store, FakeRegistry())._normalize_tasks(run_id)
        self.assertEqual(self.store.get(run_id)["tasks"][0]["status"], "interrupted")

    def test_session_binding_is_specific_to_the_attempt(self):
        run_id, spec, manager = self.seed()
        target = manager.create_worker("fix-1")
        member = spec.team[0]
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        result = self.store.get(run_id)
        result["sessions"] = [{"task_id": "fix", "provider": "claude", "transport": "cli", "connection_id": None,
                               "workspace": str(target), "mode": "edit", "session_id": first}]
        self.store.save(result)
        self.store.event(run_id, "provider", {"type": "system", "session_id": second, "provider": "claude", "mode": "edit",
                                              "transport": "cli", "connection_id": None, "workspace": str(target), "attempt": 2}, "fix")
        engine = Engine(self.store, FakeRegistry())
        self.assertEqual(engine._resume_session(run_id, "fix", target, member, "edit", attempt=2)["session_id"], second)
        self.assertEqual(engine._resume_session(run_id, "fix", target, member, "edit", attempt=1)["session_id"], first)
        self.assertIsNone(engine._resume_session(run_id, "fix", target, member, "edit", attempt=3))


class NarratingRegistry(RecordingRegistry):
    """Implementers report a narrative that evaluators must never see."""

    async def run(self, provider, **kwargs):
        outcome = await super().run(provider, **kwargs)
        if kwargs["mode"] == "edit":
            outcome = {**outcome, "answer": "IMPLEMENTER-NARRATIVE: I chose this approach because..."}
        return outcome


class EvaluatorIsolationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec
    seed = test_engine.EngineTests.seed
    task = test_engine.EngineTests.task
    finish = test_engine.EngineTests.finish

    def section(self, prompt, name):
        if f"### {name}\n" not in prompt:
            return None
        return prompt.split(f"### {name}\n", 1)[1].split("<<<end ", 1)[0]

    async def test_task_reviewer_sees_the_patch_but_not_the_implementer(self):
        run_id, spec, manager = self.seed()
        result = self.store.get(run_id); result["tasks"] = [self.task()]; self.store.save(result)
        registry = NarratingRegistry()
        engine = Engine(self.store, registry); engine.cancel_flags[run_id] = asyncio.Event()
        outcome = await engine._worker(run_id, spec, manager, self.store.get(run_id)["tasks"][0])
        self.assertTrue(outcome["ok"], outcome.get("error"))
        [review] = registry.prompts(schema=True)
        self.assertIn("+    return a + b", self.section(review, "Candidate patch"))
        self.assertIsNone(self.section(review, "Check evidence"))
        self.assertNotIn("provider", self.section(review, "Requirements"))
        self.assertNotIn("IMPLEMENTER-NARRATIVE", review)
        self.assertNotIn("claude", review.lower())
        contexts = [e for e in self.store.events(run_id) if e["kind"] == "context"]
        self.assertEqual([e["data"]["role"] for e in contexts], ["reviewer"])
        self.assertNotIn("return a + b", json.dumps(contexts))

    async def test_resolution_review_sees_only_the_failed_tasks_files(self):
        run_id, spec, manager = self.seed()
        worker = manager.create_worker("replacement-1")
        (worker / "maths.py").write_text("def add(a, b):\n    return a + b\n")
        (worker / "check.py").write_text("from maths import add\nassert add(2,3)==5\n# other change\n")
        manager.collect(worker)
        self.assertTrue(manager.merge(worker)["ok"])
        failed = {**self.task(), "status": "failed", "attempts": 1}
        replacement = {**self.task(), "id": "replacement", "status": "completed", "attempts": 1, "files": ["maths.py", "check.py"]}
        result = self.store.get(run_id); result["tasks"] = [failed, replacement]
        result["artifacts"]["validated_fingerprint"] = manager.diff()
        result["checks"] = [{"name": "Addition check", "ok": True, "output": "COMBINED-CHECK-PASSED"}]
        self.store.save(result)
        registry = RecordingRegistry()
        engine = Engine(self.store, registry); engine.cancel_flags[run_id] = asyncio.Event()
        await engine._action(run_id, spec, manager, CoordinatorAction(id="r1", action="resolve_task", task_ids=["fix"], selected_task="replacement"))
        [review] = registry.prompts(schema=True)
        patch_text = self.section(review, "Candidate patch")
        self.assertIn("diff --git a/maths.py", patch_text)
        self.assertNotIn("check.py", patch_text)
        self.assertIn("COMBINED-CHECK-PASSED", self.section(review, "Check evidence"))

    async def test_review_mode_synthesis_is_blind_and_labeled_afterwards(self):
        from parallax.models import Participant, RunSpec
        registry = RecordingRegistry()
        engine = Engine(self.store, registry)
        spec = RunSpec(workspace=str(self.project), prompt="Assess the addition helper", mode="review",
                       team=[Participant(provider="claude"), Participant(provider="grok", role="reviewer")])
        result = await self.finish(engine, await engine.start(spec))
        self.assertEqual(result["status"], "completed", result["errors"])
        synthesis = [p for p in registry.prompts(mode="consult") if p.startswith("Synthesize")]
        self.assertEqual(len(synthesis), 1)
        assessments = self.section(synthesis[0], "Assessments")
        self.assertIn('"label":"A"', assessments)
        self.assertIn('"label":"B"', assessments)
        for provider in ("claude", "grok"):
            self.assertNotIn(provider, assessments)
        self.assertTrue(result["summary"].endswith("Assessment labels: A = claude, B = grok"))
        roles = sorted(e["data"]["role"] for e in self.store.events(result["run_id"]) if e["kind"] == "context")
        self.assertEqual(roles, ["consultant", "consultant", "synthesizer"])


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec

    async def test_oversized_build_requests_are_rejected_before_any_run(self):
        spec = self.spec(); spec.prompt = "x" * 150_001
        engine = Engine(self.store, FakeRegistry())
        with self.assertRaisesRegex(ValueError, "150,000"):
            await engine.start(spec)
        self.assertEqual(self.store.runs(), [])


if __name__ == "__main__":
    unittest.main()
