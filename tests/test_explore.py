"""Exploration: isolated variants, blind reviews, independent checks, selection, and recovery."""
import asyncio
import json
import unittest
import uuid
from pathlib import Path
from parallax.engine import Engine
from parallax.models import CoordinatorAction, VariantSpec
from parallax.receipt import get_receipt
import test_engine
from test_isolation import RecordingRegistry

IMPLEMENTATIONS = {
    "DIRECTIVE-A": "def add(a, b):\n    return a + b\n",
    "DIRECTIVE-B": "def add(a, b):\n    return b + a  # variant b\n",
    "DIRECTIVE-BROKEN": "def add(a, b):\n    return a * b\n",
}


class DirectiveRegistry(RecordingRegistry):
    """Writes maths.py according to the directive marker in the worker's prompt; plays a scripted coordinator."""

    def __init__(self, script=(), **kwargs):
        super().__init__(**kwargs)
        self.script = list(script)
        self.turns = 0

    async def run(self, provider, **kwargs):
        if kwargs["mode"] == "coordinate" and self.script:
            self.records.append({"provider": provider, "mode": "coordinate", "prompt": kwargs["prompt"], "session_id": kwargs.get("session_id"),
                                 "workspace": kwargs["workspace"], "model": kwargs.get("model"), "schema": kwargs.get("schema")})
            action = self.script[min(self.turns, len(self.script) - 1)]
            self.turns += 1
            return {"ok": True, "answer": json.dumps(action), "structured_output": action, "session_id": str(uuid.uuid4())}
        if kwargs["mode"] == "edit":
            self.records.append({"provider": provider, "mode": "edit", "prompt": kwargs["prompt"], "session_id": kwargs.get("session_id"),
                                 "workspace": kwargs["workspace"], "model": kwargs.get("model"), "schema": None})
            marker = next((m for m in sorted(IMPLEMENTATIONS, key=len, reverse=True) if m in kwargs["prompt"]), "DIRECTIVE-A")
            (Path(kwargs["workspace"]) / "maths.py").write_text(IMPLEMENTATIONS[marker])
            return {"ok": True, "answer": "done", "session_id": str(uuid.uuid4()), "effective_settings": {"model": "fake", "effort": "high"}}
        return await super().run(provider, **kwargs)


def explore(*variants, task="fix", identifier="e1"):
    return CoordinatorAction(id=identifier, action="explore", task_ids=[task],
                             variants=[VariantSpec(id=v, directive=d) for v, d in variants])


class ExplorationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec
    seed = test_engine.EngineTests.seed
    task = test_engine.EngineTests.task
    finish = test_engine.EngineTests.finish

    def prepared(self, registry):
        run_id, spec, manager = self.seed()
        result = self.store.get(run_id); result["tasks"] = [self.task()]; self.store.save(result)
        engine = Engine(self.store, registry); engine.cancel_flags[run_id] = asyncio.Event()
        return run_id, spec, manager, engine

    def tasks(self, run_id):
        return {t["id"]: t for t in self.store.get(run_id)["tasks"]}

    async def test_variants_run_isolated_and_nothing_merges_until_selection(self):
        registry = DirectiveRegistry()
        run_id, spec, manager, engine = self.prepared(registry)
        await engine._action(run_id, spec, manager, explore(("v1", "DIRECTIVE-A use the plus operator directly"),
                                                            ("v2", "DIRECTIVE-B swap the operands and document why")))
        tasks = self.tasks(run_id)
        self.assertEqual((tasks["fix"]["status"], tasks["fix"]["explore_round"], tasks["fix"]["attempts"]), ("exploring", 1, 1))
        self.assertEqual((tasks["v1"]["status"], tasks["v2"]["status"]), ("candidate", "candidate"))
        self.assertEqual(self.store.get(run_id)["diff"], "")
        edits = {Path(r["workspace"]).name: r["prompt"] for r in registry.records if r["mode"] == "edit"}
        self.assertEqual(sorted(edits), ["v1-1", "v2-1"])
        self.assertIn("DIRECTIVE-A", edits["v1-1"]); self.assertNotIn("DIRECTIVE-B", edits["v1-1"])
        self.assertIn("DIRECTIVE-B", edits["v2-1"]); self.assertNotIn("DIRECTIVE-A", edits["v2-1"])
        reviews = registry.prompts(schema=True)
        self.assertEqual(len(reviews), 2)
        for review in reviews:
            self.assertNotIn("DIRECTIVE", review)
            self.assertNotIn('"v1"', review); self.assertNotIn('"v2"', review)
            self.assertIn('"id":"fix"', review)
        checks = [e for e in self.store.events(run_id) if e["kind"] == "check"]
        self.assertEqual(sorted((e["task_id"], e["data"]["phase"]) for e in checks), [("v1", "alternative"), ("v2", "alternative")])
        with self.assertRaisesRegex(ValueError, "Unfinished tasks block integration"):
            await engine._action(run_id, spec, manager, CoordinatorAction(id="i1", action="request_integration"))

    async def test_round_without_a_candidate_returns_the_task_to_failed(self):
        registry = DirectiveRegistry()
        run_id, spec, manager, engine = self.prepared(registry)
        await engine._action(run_id, spec, manager, explore(("v1", "DIRECTIVE-BROKEN multiply instead"),
                                                            ("v2", "DIRECTIVE-BROKEN product approach with a different rationale entirely")))
        tasks = self.tasks(run_id)
        self.assertEqual(tasks["fix"]["status"], "failed")
        self.assertIn("no selectable candidate", tasks["fix"]["result"]["error"])
        self.assertEqual({tasks["v1"]["discarded_reason"], tasks["v2"]["discarded_reason"]}, {"round_failed"})
        # A new round supersedes the failed one.
        await engine._action(run_id, spec, manager, explore(("v3", "DIRECTIVE-A use the plus operator directly"),
                                                            ("v4", "DIRECTIVE-B swap the operands and document why"), identifier="e2"))
        tasks = self.tasks(run_id)
        self.assertEqual((tasks["fix"]["status"], tasks["fix"]["explore_round"]), ("exploring", 2))
        self.assertEqual((tasks["v3"]["status"], tasks["v4"]["status"]), ("candidate", "candidate"))

    async def test_invalid_explorations_are_rejected_before_any_work(self):
        registry = DirectiveRegistry()
        run_id, spec, manager, engine = self.prepared(registry)
        cases = [
            (explore(("v1", "DIRECTIVE-A only one variant")), "between 2"),
            (explore(("v1", "DIRECTIVE-A use the plus operator"), ("v2", "DIRECTIVE-A use the plus operator")), "substantially different"),
            (explore(("integration", "DIRECTIVE-A use plus"), ("v2", "DIRECTIVE-B swap operands entirely")), "reserved"),
            (explore(("fix", "DIRECTIVE-A use plus"), ("v2", "DIRECTIVE-B swap operands entirely")), "new, unique"),
            (explore(("v1", "DIRECTIVE-A use plus"), ("v2", "DIRECTIVE-B swap operands"), task="missing"), "one known task"),
        ]
        for action, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                await engine._action(run_id, spec, manager, action)
        spec.mode = "compare"
        with self.assertRaisesRegex(ValueError, "Build runs"):
            await engine._action(run_id, spec, manager, explore(("v1", "DIRECTIVE-A plus"), ("v2", "DIRECTIVE-B swap operands")))
        spec.mode = "build"; spec.limits.workers = 1
        with self.assertRaisesRegex(ValueError, "at least 2 concurrent workers"):
            await engine._action(run_id, spec, manager, explore(("v1", "DIRECTIVE-A plus"), ("v2", "DIRECTIVE-B swap operands")))
        self.assertEqual(registry.prompts(mode="edit"), [])
        self.assertEqual(list(self.tasks(run_id)), ["fix"])

    async def test_explored_build_selects_one_variant_and_passes_every_gate(self):
        fix = {"id": "fix", "title": "Fix addition", "provider": "claude", "prompt": "Fix addition", "files": ["maths.py"], "acceptance": ["2+3 returns 5"]}
        script = [
            {"id": "plan", "action": "plan", "tasks": [fix]},
            {"id": "explore", "action": "explore", "task_ids": ["fix"], "variants": [
                {"id": "v1", "directive": "DIRECTIVE-A use the plus operator directly", "provider": None},
                {"id": "v2", "directive": "DIRECTIVE-B swap the operands and document why", "provider": None}]},
            {"id": "pick", "action": "select_variant", "task_ids": ["fix"], "selected_task": "v2"},
            {"id": "check", "action": "validate"},
            {"id": "ship", "action": "request_integration"},
            {"id": "done", "action": "finish", "summary": "Selected the commutative variant"},
        ]
        registry = DirectiveRegistry(script)
        engine = Engine(self.store, registry)
        result = await self.finish(engine, await engine.start(self.spec()))
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertIn("variant b", (self.project / "maths.py").read_text())
        tasks = {t["id"]: t for t in result["tasks"]}
        self.assertEqual((tasks["fix"]["status"], tasks["fix"]["resolved_by"]), ("resolved", "v2"))
        self.assertEqual((tasks["v1"]["status"], tasks["v1"]["discarded_reason"]), ("discarded", "not_selected"))
        self.assertEqual(tasks["v2"]["status"], "completed")
        receipt = get_receipt(self.store, result["run_id"])
        self.assertTrue(all(g["status"] == "passed" for g in receipt["gates"]), receipt["gates"])
        integration = [r for r in result["reviews"] if r.get("task_id") == "integration"]
        self.assertEqual(integration[-1]["provider"], "grok")
        coordinator = [r["prompt"] for r in registry.records if r["mode"] == "coordinate"]
        self.assertIn('"variants":[', coordinator[2])  # The planner sees each variant's evidence under its task.

    async def test_recovery_recognizes_exploration_and_selection_effects(self):
        registry = DirectiveRegistry()
        run_id, spec, manager, engine = self.prepared(registry)
        action = explore(("v1", "DIRECTIVE-A use the plus operator directly"), ("v2", "DIRECTIVE-B swap the operands and document why"))
        self.store.save_action(run_id, "e1", {"state": "issued", "action": action.model_dump(), "task_ids": ["fix"]})
        await engine._action(run_id, spec, manager, action)
        result = self.store.get(run_id); result["tasks"][-1]["status"] = "interrupted"; self.store.save(result)
        engine._reconcile_actions(run_id)
        self.assertEqual(self.store.action(run_id, "e1")["state"], "interrupted")
        result = self.store.get(run_id); result["tasks"][-1]["status"] = "candidate"; self.store.save(result)
        pick = CoordinatorAction(id="s1", action="select_variant", task_ids=["fix"], selected_task="v1")
        self.store.save_action(run_id, "s1", {"state": "issued", "action": pick.model_dump(), "task_ids": ["fix"]})
        await engine._action(run_id, spec, manager, pick)
        engine._reconcile_actions(run_id)
        self.assertEqual(self.store.action(run_id, "s1")["state"], "completed")
        self.assertEqual(self.tasks(run_id)["fix"]["resolved_by"], "v1")


if __name__ == "__main__":
    unittest.main()
