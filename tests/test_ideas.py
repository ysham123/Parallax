"""Project memory: scoping, whitelisted projection, deterministic retrieval, and coordinator-only exposure."""
import asyncio
import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from parallax.engine import Engine
from parallax.ideas import IdeaStore, project_key, tokenize
import test_engine
from test_isolation import RecordingRegistry


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def make_repo(root: Path, content="one") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q"); git(root, "config", "user.name", "T"); git(root, "config", "user.email", "t@example.com")
    (root / "file.txt").write_text(content); git(root, "add", "."); git(root, "commit", "-qm", content)
    return root


def run_result(run_id, prompt="Fix invoice totals", status="completed", tasks=None):
    return {"run_id": run_id, "status": status, "spec": {"prompt": prompt, "mode": "build"},
            "artifacts": {}, "sessions": [{"task_id": "invoice", "effective_settings": {"model": "fake-model"}}],
            "tasks": tasks if tasks is not None else [{
                "id": "invoice", "title": "Repair invoice totals", "prompt": "Fix sum for empty invoices", "provider": "claude",
                "files": ["billing/invoice.py"], "acceptance": ["empty=0"], "status": "completed", "attempts": 2,
                "result": {"ok": True, "patch": "+SENTINEL-PATCH\n", "changed_files": ["billing/invoice.py"],
                           "provider_result": {"answer": "SENTINEL-ANSWER"},
                           "review": {"ok": True, "findings": ["handles empty input"], "summary": "ok"}}}]}


def add_lesson(store: IdeaStore, text, files, status="active", support=3.0, kind="avoid"):
    identifier = store.node_id("lesson", None, text)
    with store.connect() as db:
        store._node(db, identifier, None, "lesson", text, text[:160], text, files, "model", None, None, {}, time.time())
        db.execute("INSERT INTO lessons(node_id,kind,status,support,refute,last_support_seq) VALUES(?,?,?,?,0,?)",
                   (identifier, kind, status, support, store._current_seq(db)))
    return identifier


class IdeaStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_repo(self.root / "project")
        self.store = IdeaStore(self.root / "home", str(self.project))

    def test_keys_separate_paths_and_repositories_at_the_same_path(self):
        other = make_repo(self.root / "other")
        self.assertNotEqual(project_key(str(self.project)), project_key(str(other)))
        before = project_key(str(self.project))
        subprocess.run(["rm", "-rf", str(self.project / ".git")], check=True)
        make_repo(self.project, "different history")
        self.assertNotEqual(project_key(str(self.project)), before)
        self.assertEqual(oct(self.store.path.stat().st_mode & 0o777), "0o600")

    def test_projection_is_idempotent_and_whitelisted(self):
        run_id = str(uuid.uuid4())
        checks = [{"sequence": 7, "task_id": "invoice", "data": {"name": "unit", "ok": False, "output": "SENTINEL-OUTPUT", "error": "check_failed", "phase": "final"}}]
        self.store.project(run_result(run_id), checks)
        with self.store.connect() as db:
            first = sorted(tuple(r) for r in db.execute("SELECT id,kind,outcome FROM nodes"))
        self.store.project(run_result(run_id), checks)
        with self.store.connect() as db:
            second = sorted(tuple(r) for r in db.execute("SELECT id,kind,outcome FROM nodes"))
            edges = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        self.assertEqual(first, second)
        self.assertEqual(edges, 3)  # pursues, review supports, check refutes
        raw = self.store.path.read_bytes() + Path(str(self.store.path) + "-wal").read_bytes() if Path(str(self.store.path) + "-wal").exists() else self.store.path.read_bytes()
        for sentinel in (b"SENTINEL-PATCH", b"SENTINEL-ANSWER", b"SENTINEL-OUTPUT"):
            self.assertNotIn(sentinel, raw)

    def test_retrieval_needs_relevance_and_ranks_deterministically(self):
        for index in range(3):
            self.store.project(run_result(str(uuid.uuid4()), prompt=f"Fix invoice totals case {index}"), [])
        unrelated = add_lesson(self.store, "Rotate the TLS certificates before deploys", ["infra/certs"])
        relevant = add_lesson(self.store, "Empty invoice lists must total zero", ["billing/invoice.py"])
        disabled = add_lesson(self.store, "Invoice totals use decimal rounding", ["billing/invoice.py"], status="disabled")
        hits = [h["id"] for h in self.store.search("invoice totals for empty lists", ["billing/invoice.py"])]
        self.assertIn(relevant, hits)
        self.assertNotIn(unrelated, hits)
        self.assertNotIn(disabled, hits)
        self.assertEqual(hits, [h["id"] for h in self.store.search("invoice totals for empty lists", ["billing/invoice.py"])])
        self.assertLessEqual(len([h for h in hits if h.startswith("L-")]), 3)
        self.assertLessEqual(len([h for h in hits if not h.startswith("L-")]), 3)

    def test_recent_runs_rank_above_old_ones(self):
        old = str(uuid.uuid4())
        self.store.project(run_result(old, prompt="Fix invoice totals for refunds"), [])
        for _ in range(30):
            self.store.project(run_result(str(uuid.uuid4()), prompt="Unrelated logging cleanup",
                                          tasks=[{"id": "log", "title": "Logging", "prompt": "tidy logs", "files": ["log.py"], "status": "completed"}]), [])
        new = str(uuid.uuid4())
        self.store.project(run_result(new, prompt="Fix invoice totals for credits"), [])
        hits = self.store.search("fix invoice totals", [])
        ids = [h["id"] for h in hits]
        self.assertLess(ids.index(self.store.node_id("goal", new, "goal")), ids.index(self.store.node_id("goal", old, "goal")))

    def test_exposure_counts_once_per_run_and_lessons_go_stale(self):
        lesson = add_lesson(self.store, "Empty invoice lists must total zero", ["billing/invoice.py"])
        self.store.expose("run-a", [lesson], "primer")
        self.store.expose("run-a", [lesson], "search")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT exposures_since_support FROM lessons").fetchone()[0], 1)
        for index in range(12):
            self.store.expose(f"run-{index}", [lesson], "primer")
        self.assertEqual(self.store.lessons()[0]["status"], "stale")

    def test_lessons_whose_scope_disappeared_are_not_rendered(self):
        (self.project / "billing").mkdir()
        kept = add_lesson(self.store, "Empty invoice lists must total zero", ["billing/invoice.py"])
        gone = add_lesson(self.store, "The legacy exporter needs UTF-8", ["legacy/export.py"])
        rendered = [r["id"] for r in self.store.render([kept, gone], workspace=str(self.project))]
        self.assertEqual(rendered, [kept])

    def test_tokenizer_splits_code_identifiers(self):
        self.assertEqual(tokenize("parseInvoiceTotals billing/invoice_items.py"), ["parse", "invoice", "total", "bill", "invoice", "item", "py"])


class MemoryEngineTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec
    finish = test_engine.EngineTests.finish

    async def test_memory_reaches_only_coordinators_and_never_the_run_record(self):
        from parallax.ideas import IdeaStore
        ideas = IdeaStore(self.store.home, str(self.project))
        ideas.project(run_result(str(uuid.uuid4()), prompt="Fix the addition bug in maths",
                                 tasks=[{"id": "fix", "title": "Fix addition", "prompt": "Fix addition", "files": ["maths.py"], "status": "failed", "attempts": 1}]), [])
        lesson = add_lesson(ideas, "MEMORY-SENTINEL fixing the addition bug: the add helper subtracted; verify negative numbers too", ["maths.py"])
        registry = RecordingRegistry()
        engine = Engine(self.store, registry, memory=True)
        result = await self.finish(engine, await engine.start(self.spec()))
        self.assertEqual(result["status"], "completed", result["errors"])
        coordinator = [r["prompt"] for r in registry.records if r["mode"] == "coordinate"]
        others = [r["prompt"] for r in registry.records if r["mode"] != "coordinate"]
        self.assertTrue(coordinator and all("MEMORY-SENTINEL" in p for p in coordinator))
        self.assertFalse(any("MEMORY-SENTINEL" in p for p in others))
        self.assertNotIn("MEMORY-SENTINEL", json.dumps(self.store.get(result["run_id"])))
        self.assertNotIn("MEMORY-SENTINEL", json.dumps(self.store.events(result["run_id"])))
        self.assertIn(lesson, self.store.get(result["run_id"])["artifacts"]["memory"]["primer"])
        # The finished run was projected for future runs.
        with ideas.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 2)

    async def test_search_results_are_journaled_locally_and_shown_once(self):
        from parallax.ideas import IdeaStore
        ideas = IdeaStore(self.store.home, str(self.project))
        add_lesson(ideas, "SEARCH-SENTINEL integer addition check asserts add(2,3) equals five", ["check.py"])
        fix = {"id": "fix", "title": "Fix addition", "provider": "claude", "prompt": "Fix addition", "files": ["maths.py"], "acceptance": ["2+3 returns 5"]}
        script = [{"id": "q", "action": "search_ideas", "query": "integer addition check", "task_ids": []},
                  {"id": "plan", "action": "plan", "tasks": [fix]}, {"id": "go", "action": "dispatch", "task_ids": ["fix"]},
                  {"id": "check", "action": "validate"}, {"id": "ship", "action": "request_integration"}, {"id": "done", "action": "finish"}]
        from test_isolation import ScriptedCoordinator
        registry = ScriptedCoordinator(script)
        engine = Engine(self.store, registry, memory=True)
        result = await self.finish(engine, await engine.start(self.spec()))
        self.assertEqual(result["status"], "completed", result["errors"])
        prompts = [r["prompt"] for r in registry.records if r["mode"] == "coordinate"]
        def search_section(prompt):
            return prompt.split("### Search results\n", 1)[1].split("<<<end", 1)[0] if "### Search results\n" in prompt else ""
        self.assertIn("SEARCH-SENTINEL", search_section(prompts[1]))
        self.assertEqual(search_section(prompts[2]), "")
        saved = self.store.action(result["run_id"], "q")
        self.assertTrue(saved["memory_results"])
        self.assertEqual(saved["state"], "completed")
        self.assertNotIn("SEARCH-SENTINEL", json.dumps(self.store.events(result["run_id"])))

    async def test_memory_is_off_for_injected_registries_and_review_mode(self):
        self.assertFalse(Engine(self.store, RecordingRegistry()).memory)
        engine = Engine(self.store, RecordingRegistry(), memory=True)
        spec = self.spec(); spec.mode = "review"
        self.assertIsNone(await engine._ideas("run", spec))


if __name__ == "__main__":
    unittest.main()
