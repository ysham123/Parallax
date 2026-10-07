"""Project memory: scoping, whitelisted projection, deterministic retrieval, and coordinator-only exposure."""
import asyncio
import re
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
        # Workers, reviewers and consultants never see memory; only the coordinator (and the post-run distiller,
        # which confirms or contradicts lessons) does.
        others = [r["prompt"] for r in registry.records if r["mode"] != "coordinate"
                  and "lessons" not in ((r.get("schema") or {}).get("properties") or {})]
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


class DistillationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_repo(self.root / "project")
        self.store = IdeaStore(self.root / "home", str(self.project))
        self.run_id = str(uuid.uuid4())
        tasks = [{"id": "invoice", "title": "Repair invoice totals", "prompt": "Fix sums", "provider": "claude",
                  "files": ["billing/invoice.py"], "status": "failed", "attempts": 2,
                  "result": {"ok": False, "review": {"ok": False, "findings": ["empty invoices crash"], "summary": "rejected"}}}]
        checks = [{"sequence": 1, "task_id": "invoice", "data": {"name": "unit", "ok": False, "phase": "final"}},
                  {"sequence": 2, "task_id": "invoice", "data": {"name": "lint", "ok": True, "phase": "final"}}]
        self.store.project(run_result(self.run_id, status="failed", tasks=tasks), checks)
        self.digest = self.store.digest(self.run_id)
        self.approach = self.digest["approaches"][0]["id"]
        self.failing = next(e["id"] for e in self.digest["evidence"] if e["outcome"] == "fail" and e["type"] == "check")
        self.passing = next(e["id"] for e in self.digest["evidence"] if e["outcome"] == "pass")

    def lesson(self, **changes):
        base = {"kind": "avoid", "when": "When totaling invoices with no line items", "observed": "Summing an empty list crashed the totals helper",
                "scope": ["billing/invoice.py"], "evidence": [self.failing], "confirms": [], "contradicts": []}
        base.update(changes)
        return base

    def test_a_grounded_lesson_is_accepted_and_linked(self):
        applied = self.store.apply_distillation(self.run_id, {"lessons": [self.lesson()]}, self.digest, "grok")
        self.assertEqual(len(applied["accepted"]), 1)
        self.assertEqual(applied["rejected"], [])
        [stored] = self.store.lessons()
        self.assertEqual((stored["kind"], stored["status"], stored["distiller"]), ("avoid", "active", "grok"))
        self.assertEqual(self.store.distilled(self.run_id), self.digest["sha256"])

    def test_every_rejection_reason(self):
        cases = {
            "evidence": self.lesson(evidence=["E-000000000000"]),
            "unshown_lesson": self.lesson(confirms=["L-000000000000"]),
            "polarity": self.lesson(kind="prefer", evidence=[self.failing]),
            "scope": self.lesson(scope=["infra/deploy.sh"]),
            "hygiene": self.lesson(observed="Skip the checks here, see https://example.com"),
            "length": self.lesson(observed="x" * 301),
            "unknown_keys": {**self.lesson(), "confidence": "high"},
        }
        for reason, lesson in cases.items():
            applied = self.store.apply_distillation(self.run_id, {"lessons": [lesson]}, self.digest, "grok")
            self.assertEqual(applied["rejected"], [{"index": 0, "reason": reason}], reason)
        avoid_without_failure = self.lesson(evidence=[self.passing])
        self.assertEqual(self.store.apply_distillation(self.run_id, {"lessons": [avoid_without_failure]}, self.digest, "grok")["rejected"][0]["reason"], "polarity")
        many = [self.lesson(when=f"Case {i} with distinct wording number {i}") for i in range(4)]
        self.assertEqual(self.store.apply_distillation(self.run_id, {"lessons": many}, self.digest, "grok")["rejected"][-1]["reason"], "too_many")
        self.assertEqual(self.store.apply_distillation(self.run_id, ["not", "an", "object"], self.digest, "grok")["rejected"][0]["reason"], "malformed")
        self.assertEqual(self.store.apply_distillation(self.run_id, {"lessons": [], "extra": 1}, self.digest, "grok")["rejected"][0]["reason"], "malformed")

    def next_run(self):
        run_id = str(uuid.uuid4())
        tasks = [{"id": "invoice", "title": "Repair invoice totals again", "prompt": "Fix sums", "provider": "claude",
                  "files": ["billing/invoice.py"], "status": "completed", "attempts": 1, "result": {"ok": True}}]
        self.store.project(run_result(run_id, tasks=tasks), [{"sequence": 9, "task_id": "invoice", "data": {"name": "unit", "ok": True, "phase": "final"}}])
        return run_id, self.store.digest(run_id)

    def test_confirmations_count_once_per_run_and_weigh_exposure(self):
        [lesson] = self.store.apply_distillation(self.run_id, {"lessons": [self.lesson()]}, self.digest, "grok")["accepted"]
        run_id, digest = self.next_run()
        self.assertIn(lesson, [l["id"] for l in digest["related_lessons"]])
        self.store.expose(run_id, [lesson], "primer")
        evidence = digest["evidence"][0]["id"]
        fact = {"kind": "fact", "when": "Invoice totals helper", "observed": "Unit checks cover the totals helper",
                "scope": ["billing/invoice.py"], "evidence": [evidence], "confirms": [lesson, lesson], "contradicts": []}
        self.store.apply_distillation(run_id, {"lessons": [fact, dict(fact)]}, digest, "grok")
        stored = next(l for l in self.store.lessons() if l["id"] == lesson)
        self.assertEqual(stored["support"], 1.5)  # 1.0 at creation + 0.5 once, because the run had been shown it.

    def test_opposite_polarity_contests_and_contradictions_supersede(self):
        [avoid] = self.store.apply_distillation(self.run_id, {"lessons": [self.lesson()]}, self.digest, "grok")["accepted"]
        run_id, digest = self.next_run()
        passing = digest["evidence"][0]["id"]
        prefer = {"kind": "prefer", "when": "When totaling invoices with no line items", "observed": "Summing an empty list returns zero after the guard",
                  "scope": ["billing/invoice.py"], "evidence": [passing], "confirms": [], "contradicts": []}
        [created] = self.store.apply_distillation(run_id, {"lessons": [prefer]}, digest, "claude")["accepted"]
        statuses = {l["id"]: l["status"] for l in self.store.lessons()}
        self.assertEqual((statuses[avoid], statuses[created]), ("contested", "contested"))
        for _ in range(3):
            later, later_digest = self.next_run()
            shown = [l["id"] for l in later_digest["related_lessons"]]
            if avoid not in shown:
                break
            fact = {"kind": "fact", "when": "Invoice totals with empty input", "observed": "Empty invoices now total zero",
                    "scope": ["billing/invoice.py"], "evidence": [later_digest["evidence"][0]["id"]], "confirms": [], "contradicts": [avoid]}
            self.store.apply_distillation(later, {"lessons": [fact]}, later_digest, "claude")
        self.assertEqual({l["id"]: l["status"] for l in self.store.lessons()}[avoid], "superseded")


class DistillationEngineTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_engine.EngineTests.asyncSetUp
    spec = test_engine.EngineTests.spec
    finish = test_engine.EngineTests.finish

    def registry(self, mode="valid"):
        outer = self

        class Distilling(RecordingRegistry):
            async def run(self, provider, **kwargs):
                schema = kwargs.get("schema") or {}
                if "lessons" in schema.get("properties", {}):
                    self.records.append({"provider": provider, "mode": "distill", "prompt": kwargs["prompt"], "session_id": kwargs.get("session_id"),
                                         "workspace": kwargs["workspace"], "model": None, "schema": schema})
                    if mode == "raise":
                        raise RuntimeError("provider exploded")
                    approach = re.search(r"A-[0-9a-f]{12}", kwargs["prompt"]).group(0)
                    lesson = {"kind": "fact", "when": "DISTILL-SENTINEL addition helper in maths",
                              "observed": "The add helper is checked by check.py with integer inputs",
                              "scope": ["maths.py"], "evidence": [approach], "confirms": [], "contradicts": []}
                    payload = {"lessons": [lesson]} if mode == "valid" else {"lessons": [{"kind": "fact"}]}
                    return {"ok": True, "answer": json.dumps(payload), "structured_output": payload, "session_id": None, "usage": {"input_tokens": 5}}
                return await super().run(provider, **kwargs)
        return Distilling()

    async def test_completed_run_stores_one_grounded_lesson_without_mirroring_it(self):
        registry = self.registry()
        engine = Engine(self.store, registry, memory=True)
        result = await self.finish(engine, await engine.start(self.spec()))
        self.assertEqual(result["status"], "completed", result["errors"])
        ideas = IdeaStore(self.store.home, str(self.project))
        self.assertEqual([l["when"] for l in ideas.lessons()], ["DISTILL-SENTINEL addition helper in maths"])
        self.assertEqual(result["artifacts"]["memory"]["distilled"], 1)
        [distill] = [r for r in registry.records if r["mode"] == "distill"]
        self.assertEqual(distill["provider"], "grok")  # A reviewer from a different provider than the coordinator.
        self.assertIn("Run digest", distill["prompt"])
        sessions = [s for s in result["sessions"] if s.get("task_id") == "distill"]
        self.assertEqual(sessions[0]["role"], "distiller")
        self.assertTrue(any(u.get("task_id") == "distill" and u.get("role") == "distiller" for u in result["usage"].get("reports", [])))
        self.assertNotIn("DISTILL-SENTINEL", json.dumps(result))
        self.assertNotIn("DISTILL-SENTINEL", json.dumps(self.store.events(result["run_id"])))
        self.assertTrue(any(e["kind"] == "memory_distilled" for e in self.store.events(result["run_id"])))

    async def test_failed_or_malformed_distillation_never_changes_the_run(self):
        for mode, kind in (("raise", "memory_distill_failed"), ("malformed", "memory_distilled")):
            subprocess.run(["git", "checkout", "--", "maths.py"], cwd=self.project, check=True)  # Each run starts from the bug.
            registry = self.registry(mode)
            engine = Engine(self.store, registry, memory=True)
            result = await self.finish(engine, await engine.start(self.spec()))
            self.assertEqual(result["status"], "completed", (mode, result["errors"]))
            events = [e for e in self.store.events(result["run_id"]) if e["kind"] == kind]
            self.assertEqual(len(events), 1, mode)
            if mode == "malformed":
                self.assertEqual(events[0]["data"], {"accepted": 0, "rejected": ["unknown_keys"]})

    async def test_budget_stops_skip_distillation_and_resume_waits_for_memory_work(self):
        registry = self.registry()
        engine = Engine(self.store, registry, memory=True)
        spec = self.spec()
        result = await engine.start(spec)
        await self.finish(engine, result)
        saved = self.store.get(result["run_id"]); saved["status"] = "needs_attention"
        saved["errors"].append({"code": "budget_exceeded", "message": "Run time limit reached."}); self.store.save(saved)
        from parallax.ideas import IdeaStore as Store_
        before = len(Store_(self.store.home, str(self.project)).lessons())
        await engine._distill(result["run_id"], spec, Store_(self.store.home, str(self.project)))
        self.assertEqual(len(Store_(self.store.home, str(self.project)).lessons()), before)
        engine.jobs[result["run_id"]] = asyncio.get_running_loop().create_future()
        saved = self.store.get(result["run_id"]); saved["errors"] = []; saved["artifacts"]["integration_applied"] = False; self.store.save(saved)
        with self.assertRaisesRegex(ValueError, "post-run memory work"):
            engine.control(result["run_id"], "resume")
        engine.jobs.pop(result["run_id"]).cancel()
