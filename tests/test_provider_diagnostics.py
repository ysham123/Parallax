"""Failed native launches preserve diagnostics without exporting stderr."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from parallax.engine import Engine
from parallax.models import Participant, RunResult, RunSpec
from parallax.receipt import build_receipt, get_receipt, save_receipt
from parallax.store import Store


class DiagnosticRegistry:
    def __init__(self, outcome, events=()):
        self.outcome = outcome
        self.events = events

    async def run(self, provider, **kwargs):
        for event in self.events:
            await kwargs["on_event"](event)
        return dict(self.outcome)


class ProviderDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.run_id = str(uuid4())
        self.participant = Participant(provider="codex")
        self.spec = RunSpec(workspace=str(self.project), prompt="Inspect the isolated fixture", integrate=False)
        result = RunResult(run_id=self.run_id, status="planning", spec=self.spec).model_dump()
        directory = self.store.home / "runs" / self.run_id
        directory.mkdir(parents=True)
        result["artifacts"] = {"directory": str(directory), "runtime_seconds": 4.838, "coordinator_turns": 1}
        self.store.save(result)

    async def invoke(self, outcome, *, events=(), quiet=False):
        engine = Engine(self.store, DiagnosticRegistry(outcome, events), memory=False)
        engine.cancel_flags[self.run_id] = asyncio.Event()
        returned = await engine._provider(self.run_id, self.participant, self.project, "Inspect", mode="coordinate", task_id="coordinator", quiet=quiet)
        return returned, self.store.get(self.run_id)

    def failed(self, diagnostics=None):
        value = {"ok": False, "session_id": None, "exit_code": 1,
                 "error": {"code": "provider_error", "message": "Provider returned no valid terminal event"}}
        if diagnostics is not None:
            value["diagnostics"] = diagnostics
        return value

    async def test_pre_terminal_config_failure_survives_restart_and_receipt_export(self):
        diagnostic = "Error loading config.toml: unknown configuration field `tools.view_image` in -c/--config override\n"
        returned, result = await self.invoke(self.failed(diagnostic), events=[{"type": "parallax.process_finished", "exit_code": 1}])
        self.assertFalse(returned["ok"])
        reopened = Store(self.store.home)
        saved = reopened.get(self.run_id)
        failures = [item for item in saved["errors"] if item["code"] == "provider_failure"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["diagnostics"], diagnostic)
        self.assertEqual(failures[0]["exit_code"], 1)
        self.assertEqual(saved["sessions"][-1]["session_id"], None)
        self.assertEqual(saved["artifacts"]["runtime_seconds"], 4.838)
        self.assertEqual(saved["artifacts"]["coordinator_turns"], 1)
        journal = [event for event in reopened.events(self.run_id) if event["kind"] == "provider_failure"]
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]["data"]["diagnostics"], diagnostic)
        save_receipt(result)
        reopened.save(result)
        receipt = get_receipt(reopened, self.run_id)
        self.assertEqual(receipt["provider_failures"][0]["diagnostics_sha256"], hashlib.sha256(diagnostic.encode()).hexdigest())
        self.assertEqual(receipt["provider_failures"][0]["provider_error_code"], "provider_error")
        self.assertNotIn("tools.view_image", json.dumps(receipt))
        self.assertNotIn("diagnostics", receipt["provider_failures"][0])

    async def test_persistence_re_sanitizes_and_bounds_diagnostics(self):
        diagnostic = f"stderr at {self.project}: token=example-test-value api_key=example-api-value\n" + "x" * 10000
        _, result = await self.invoke(self.failed(diagnostic))
        failure = result["errors"][0]
        self.assertLessEqual(len(failure["diagnostics"]), 2000)
        self.assertNotIn("example-test-value", failure["diagnostics"])
        self.assertNotIn("example-api-value", failure["diagnostics"])
        self.assertIn("[redacted]", failure["diagnostics"])
        receipt = build_receipt(result)
        self.assertNotIn(str(self.project), json.dumps(receipt))
        self.assertNotIn("stderr at", json.dumps(receipt))
        self.assertEqual(receipt["provider_failures"][0]["diagnostics_sha256"], hashlib.sha256(failure["diagnostics"].encode()).hexdigest())

    async def test_existing_native_failure_event_is_not_re_emitted(self):
        _, result = await self.invoke(self.failed("Configuration rejected"), events=[{"type": "error", "message": "Configuration rejected"}])
        events = self.store.events(self.run_id)
        self.assertEqual(len([event for event in events if event["kind"] == "provider" and event["data"].get("type") == "error"]), 1)
        self.assertFalse(any(event["kind"] == "provider_failure" for event in events))
        self.assertEqual(len([event for event in events if event["kind"] == "provider_diagnostics"]), 1)
        self.assertEqual(len(result["errors"]), 1)

    async def test_quiet_failure_still_preserves_bounded_diagnostics(self):
        _, result = await self.invoke(self.failed("Configuration rejected"), events=[{"type": "error", "message": "Configuration rejected"}], quiet=True)
        self.assertEqual(result["errors"][0]["diagnostics"], "Configuration rejected")
        events = self.store.events(self.run_id)
        self.assertFalse(any(event["kind"] == "provider" for event in events))
        self.assertEqual(len([event for event in events if event["kind"] == "provider_failure"]), 1)

    async def test_failure_without_stderr_preserves_exit_and_error_code(self):
        _, result = await self.invoke(self.failed())
        failure = result["errors"][0]
        self.assertNotIn("diagnostics", failure)
        receipt = build_receipt(result)
        self.assertEqual(receipt["provider_failures"][0]["exit_code"], 1)
        self.assertNotIn("diagnostics_sha256", receipt["provider_failures"][0])

    async def test_successful_warning_does_not_create_a_failure(self):
        _, result = await self.invoke({"ok": True, "session_id": "fixture", "exit_code": 0, "diagnostics": "Benign warning"})
        self.assertEqual(result["errors"], [])
        self.assertEqual(build_receipt(result)["provider_failures"], [])
        self.assertFalse(any(event["kind"] in {"provider_failure", "provider_diagnostics"} for event in self.store.events(self.run_id)))
