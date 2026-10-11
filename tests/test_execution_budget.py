import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from parallax.budget import ExecutionBudget
from parallax.engine import Engine
from parallax.models import RunSpec, RunResult
from parallax.store import Store
from test_engine import FakeRegistry


class ExecutionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.store = Store(self.root / "state")
        self.run_id = str(uuid4())
        self.record = RunResult(run_id=self.run_id, status="running",
                               spec=RunSpec(workspace=str(self.root), prompt="bounded", mode="review")).model_dump()
        self.record["artifacts"]["runtime_seconds"] = 2.0
        self.store.save(self.record)

    def tearDown(self):
        self.store.close(); self.directory.cleanup()

    def test_recovery_is_monotonic_and_idempotent(self):
        with patch("parallax.budget.boot_identity", return_value="same-boot"):
            budget = ExecutionBudget(self.store)
            with patch("parallax.budget.time.monotonic", return_value=100):
                budget.begin(self.run_id, 2, 60)
            # Simulate a stale run artifact save while a provider was awaited.
            self.record["artifacts"]["runtime_seconds"] = 0
            with patch("parallax.budget.time.monotonic", return_value=110):
                self.assertTrue(budget.recover(self.record))
            self.assertEqual(self.record["artifacts"]["runtime_seconds"], 12)
            with patch("parallax.budget.time.monotonic", return_value=150):
                self.assertFalse(budget.recover(self.record))
            with patch("parallax.budget.time.monotonic", return_value=151):
                _, used = budget.begin(self.run_id, 0, 60)
            self.assertEqual(used, 12)

    def test_reboot_or_unknown_clock_consumes_remaining_allowance(self):
        with patch("parallax.budget.boot_identity", return_value="old"):
            ExecutionBudget(self.store).begin(self.run_id, 2, 60)
        with patch("parallax.budget.boot_identity", return_value="new"):
            self.assertTrue(ExecutionBudget(self.store).recover(self.record))
        self.assertEqual(self.record["artifacts"]["runtime_seconds"], 60)

    def test_graceful_end_does_not_charge_offline_wait(self):
        with patch("parallax.budget.boot_identity", return_value="boot"):
            budget = ExecutionBudget(self.store)
            budget.begin(self.run_id, 2, 60)
            budget.end(self.run_id, 3)
            with patch("parallax.budget.time.monotonic", return_value=10**9):
                budget.recover(self.record)
        self.assertEqual(self.record["artifacts"]["runtime_seconds"], 3)

    def test_actual_sigkill_provider_interval_is_not_refunded(self):
        project = self.root / "project"; project.mkdir()
        (project / "source.py").write_text("value=1\n")
        for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                     ("config", "user.email", "fixture@example.invalid"), ("add", "."), ("commit", "-qm", "baseline")):
            subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
        script = '''import asyncio,json,sys
from pathlib import Path
from parallax.store import Store
from parallax.engine import Engine
from parallax.models import RunSpec,Participant
from test_engine import FakeRegistry
class Waiting(FakeRegistry):
 async def run(self,provider,**kw):
  print(json.dumps({"id":identifier}),flush=True)
  await asyncio.sleep(30)
async def main():
 global identifier
 engine=Engine(Store(Path(sys.argv[1])),Waiting(),memory=False)
 result=await engine.start(RunSpec(workspace=sys.argv[2],prompt="bounded review",mode="review",team=[Participant(provider="claude")]))
 identifier=result["run_id"]
 await engine.jobs[identifier]
asyncio.run(main())
'''
        state = self.root / "killed-state"
        child = subprocess.Popen([sys.executable, "-c", script, str(state), str(project)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            marker = json.loads(child.stdout.readline())
            time.sleep(.25)
            child.kill(); child.wait(timeout=5)
            store = Store(state)
            try:
                engine = Engine(store, FakeRegistry(), memory=False)
                engine.recover()
                value = store.get(marker["id"])
                self.assertGreaterEqual(value["artifacts"]["runtime_seconds"], .25)
                self.assertEqual(value["status"], "interrupted")
                charged = value["artifacts"]["runtime_seconds"]
                engine.recover()
                self.assertEqual(store.get(marker["id"])["artifacts"]["runtime_seconds"], charged)
            finally: store.close()
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.stdout.close(); child.stderr.close()
