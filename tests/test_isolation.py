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
