"""Real isolated desktop subprocesses; no provider inference or user state."""
import asyncio
import http.client
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4
import venv

from parallax import __version__
from parallax.desktop import CONTROL_LIMIT, IDENTITY, LOCK, READY_LIMIT
from parallax.store import Store


class DesktopRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = tempfile.TemporaryDirectory(prefix="parallax-desktop-test-python-")
        environment = Path(cls.installation.name).resolve() / "runtime"
        venv.EnvBuilder(with_pip=False).create(environment)
        cls.python = environment / "bin" / "python"
        library = environment / "lib" / ("python" + str(sys.version_info.major) + "." + str(sys.version_info.minor)) / "site-packages"
        # A disposable installed-module harness makes exact -I -B -m argv work;
        # it neither changes the shared interpreter nor claims bundled-runtime QA.
        (library / "desktop-test.pth").write_text(str(Path(__file__).resolve().parents[1] / "src") + "\n"
            + sysconfig.get_paths()["purelib"] + "\n")

    @classmethod
    def tearDownClass(cls):
        cls.installation.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="parallax-desktop-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "selected project"
        self.project.mkdir()
        (self.project / "source.txt").write_text("Developer's original work\n")
        self.state = self.root / "desktop-state"
        self.home = self.root / "home"
        self.home.mkdir()
        self.cli_state = self.home / "unrelated-cli"
        self.cli_state.mkdir(mode=0o700)
        (self.cli_state / "server.json").write_text('{"url":"http://127.0.0.1:1","token":"unrelated-secret"}')
        self.environment = {"PATH": os.defpath, "HOME": str(self.home), "LANG": "en_US.UTF-8",
            "PARALLAX_HOME": str(self.cli_state), "PARALLAX_MEMORY": "off", "PYTHONPATH": "/nonexistent-ignored-with-I"}
        self.children = []
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()

    def launch(self, *, state=None, project=None, extra=(), script=None):
        invocation = [str(self.python), "-I", "-B"]
        invocation += ["-c", script] if script else ["-m", "parallax.desktop"]
        invocation += ["--workspace", str(project or self.project), "--state-directory", str(state or self.state), *extra]
        child = subprocess.Popen(invocation, cwd=self.root, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=True)
        self.children.append(child)
        return child

    def ready(self, child):
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=20), "Desktop did not emit readiness")
        line = child.stdout.readline(READY_LIMIT + 1)
        if not line:
            child.wait(timeout=5)
            self.fail("Desktop failed before readiness: " + child.stderr.read(1000))
        self.assertLessEqual(len(line.encode()), READY_LIMIT)
        result = json.loads(line)
        self.assertEqual(set(result), {"event", "url", "version", "pid"})
        self.assertEqual((result["event"], result["version"], result["pid"]), ("ready", __version__, child.pid))
        parsed = urlsplit(result["url"])
        self.assertEqual((parsed.scheme, parsed.hostname, parsed.path), ("http", "127.0.0.1", "/"))
        self.assertEqual(parse_qs(parsed.query)["workspace"], [str(self.project)])
        self.assertEqual(len(parse_qs(parsed.query)["token"][0]), 43)
        return result

    def request(self, ready, method, target, body=None, headers=None):
        parsed = urlsplit(ready["url"])
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            payload = None if body is None else json.dumps(body)
            supplied = dict(headers or {})
            if body is not None:
                supplied["Content-Type"] = "application/json"
            connection.request(method, target, body=payload, headers=supplied)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def token(self, ready):
        return parse_qs(urlsplit(ready["url"]).query)["token"][0]

    def stop(self, child, command='{"command":"stop"}\n'):
        child.stdin.write(command)
        child.stdin.flush()
        child.wait(timeout=15)  # Stdin remains open: no blocked reader thread may keep it alive.
        output, errors = child.stdout.read(), child.stderr.read()
        self.assertEqual(output, "")
        return child.returncode, errors

    def wait_for_file(self, path, child, timeout=5):
        deadline = time.monotonic() + timeout
        while not path.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), "Synthetic lifespan did not reach its boundary")

    @staticmethod
    def unchanged_file(path):
        content = path.read_bytes()
        details = path.stat()
        # Reading the fixture itself may change atime; every write-related
        # field and file identity must remain unchanged after refusal.
        return content, (details.st_ino, details.st_mode, details.st_uid, details.st_gid,
            details.st_nlink, details.st_size, details.st_mtime_ns, details.st_ctime_ns)

    def test_ready_is_authenticated_loopback_only_and_project_scoped(self):
        child = self.launch()
        ready = self.ready(child)
        self.assertEqual(self.request(ready, "GET", "/api/health")[0], 200)
        self.assertEqual(self.request(ready, "GET", "/api/context")[0], 401)
        parsed = urlsplit(ready["url"])
        status, headers, _ = self.request(ready, "GET", "/?" + parsed.query)
        self.assertEqual(status, 303)
        self.assertNotIn("token", headers["location"])
        self.assertIn("HttpOnly", headers["set-cookie"])
        cookie = headers["set-cookie"].split(";", 1)[0]
        status, _, body = self.request(ready, "GET", "/api/context", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["workspace"], str(self.project))
        self.assertIs(json.loads(body)["desktop_runtime"], True)
        authorization = {"Authorization": "Bearer " + self.token(ready)}
        response = self.request(ready, "PUT", "/api/connections/desktop-env", {
            "provider": "codex", "api_key_env": "SYNTHETIC_API_KEY"}, authorization)
        self.assertEqual(response[0], 400)
        self.assertIn("macOS Keychain", response[2])
        other = self.root / "other-project"
        other.mkdir()
        self.assertEqual(self.request(ready, "PUT", "/api/profiles/foreign", {"workspace": str(other), "prompt": "Refuse"}, authorization)[0], 400)
        self.assertEqual(self.request(ready, "GET", "/api/memory?" + urlencode({"workspace": str(other)}), headers=authorization)[0], 403)
        self.assertEqual(self.request(ready, "GET", "/api/context", headers={**authorization, "x-parallax-authority": '{"version":"2.0","role":"owner","projects":[]}'} )[0], 403)
        self.assertEqual(self.request(ready, "GET", "/api/context", headers={**authorization, "Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.stop(child), (0, ""))
        self.assertEqual((self.project / "source.txt").read_text(), "Developer's original work\n")

    def test_private_state_and_unrelated_cli_are_not_adopted(self):
        original = (self.cli_state / "server.json").read_bytes()
        child = self.launch()
        self.ready(child)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        for name in (IDENTITY, LOCK, "state.sqlite3"):
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.state / "server.json").exists())
        self.assertEqual((self.cli_state / "server.json").read_bytes(), original)
        self.assertEqual(self.stop(child), (0, ""))

    def test_second_instance_refuses_without_adopting_or_exposing_endpoint(self):
        first = self.launch()
        ready = self.ready(first)
        second = self.launch()
        output, errors = second.communicate(timeout=10)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(output, "")
        self.assertIn("Another desktop runtime", errors)
        self.assertNotIn(self.token(ready), errors)
        self.assertNotIn(str(self.state), errors)
        self.assertIsNone(first.poll())
        self.assertEqual(self.request(ready, "GET", "/api/health")[0], 200)
        self.assertEqual(self.stop(first), (0, ""))

    def test_eof_shutdown_releases_owner_and_restart_keeps_session_and_records(self):
        first = self.launch()
        ready = self.ready(first)
        parsed = urlsplit(ready["url"])
        _, headers, _ = self.request(ready, "GET", "/?" + parsed.query)
        cookie = headers["set-cookie"].split(";", 1)[0]
        # Seed a durable record directly; saving a profile through HTTP would
        # discover real provider CLIs, which this lifecycle fixture excludes.
        store = Store(self.state)
        try:
            store.put_profile("saved", {"workspace": str(self.project), "prompt": "Saved only"})
        finally:
            store.close()
        first.stdin.close()
        first.stdin = None
        output, errors = first.communicate(timeout=15)
        self.assertEqual((first.returncode, output, errors), (0, "", ""))
        second = self.launch()
        restarted = self.ready(second)
        self.assertEqual(self.token(restarted), self.token(ready))
        self.assertEqual(self.request(restarted, "GET", "/api/context", headers={"Cookie": cookie})[0], 200)
        status, _, body = self.request(restarted, "GET", "/api/profiles", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]["name"], "saved")
        self.assertEqual(self.stop(second), (0, ""))

    def test_signals_do_not_require_parent_to_close_stdin(self):
        for kind in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=kind):
                child = self.launch()
                self.ready(child)
                child.send_signal(kind)
                child.wait(timeout=15)
                self.assertEqual((child.returncode, child.stdout.read(), child.stderr.read()), (0, "", ""))

    def test_lock_and_identity_symlinks_or_public_state_are_refused(self):
        outside = self.root / "protected-outside-file"
        outside.write_text("Unchanged synthetic secret")
        outside.chmod(0o600)
        self.state.mkdir(mode=0o700)
        (self.state / LOCK).symlink_to(outside)
        child = self.launch()
        output, errors = child.communicate(timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertEqual(output, "")
        self.assertNotIn("synthetic secret", errors)
        self.assertEqual(outside.read_text(), "Unchanged synthetic secret")
        (self.state / LOCK).unlink()
        self.state.rmdir()
        valid = self.launch()
        ready = self.ready(valid)
        self.assertEqual(self.stop(valid), (0, ""))
        identity = self.state / IDENTITY
        before = identity.read_bytes()
        identity.chmod(0o644)
        public = self.launch()
        output, errors = public.communicate(timeout=10)
        self.assertEqual((public.returncode, output), (2, ""))
        self.assertNotIn(self.token(ready), errors)
        self.assertEqual(identity.read_bytes(), before)
        identity.unlink()
        identity.symlink_to(outside)
        linked = self.launch()
        output, errors = linked.communicate(timeout=10)
        self.assertNotEqual(linked.returncode, 0)
        self.assertEqual(output, "")
        self.assertNotIn(str(outside), errors)
        self.assertEqual(outside.read_text(), "Unchanged synthetic secret")

    def test_unknown_and_oversized_control_stop_safely(self):
        oversized_stop = '{"command":"stop"}' + " " * (CONTROL_LIMIT - len('{"command":"stop"}')) + "\n"
        for command in ('{"command":"start","workspace":"/unapproved"}\n', "x" * 2048 + "\n", oversized_stop):
            with self.subTest(size=len(command)):
                child = self.launch()
                ready = self.ready(child)
                status, errors = self.stop(child, command)
                self.assertEqual(status, 2)
                self.assertIn("Unrecognized desktop control", errors)
                self.assertNotIn(self.token(ready), errors)

    def test_unsafe_roots_symlinks_and_unrelated_state_are_rejected_silently(self):
        unrelated = self.root / "unrelated-state"
        unrelated.mkdir(mode=0o700)
        (unrelated / "state.sqlite3").write_text("Do not adopt me")
        link = self.root / "state-link"
        link.symlink_to(unrelated, target_is_directory=True)
        project_link = self.root / "project-link"
        project_link.symlink_to(self.project, target_is_directory=True)
        cases = [(self.project / "state", self.project), (self.project, self.project),
            (self.root, self.project), (unrelated, self.project), (link, self.project), (self.state, project_link),
            (self.cli_state, self.project), (self.state, Path("relative-project"))]
        for state, project in cases:
            with self.subTest(state=state.name, project=project.name):
                child = self.launch(state=state, project=project)
                output, errors = child.communicate(timeout=10)
                self.assertIn(child.returncode, (1, 2))
                self.assertEqual(output, "")
                self.assertNotIn(str(state), errors)
                self.assertNotIn(str(project), errors)
                self.assertNotIn("Traceback", errors)
        self.assertEqual(set(path.name for path in unrelated.iterdir()), {"state.sqlite3"})

    def test_state_cannot_be_rebound_to_an_external_project(self):
        first = self.launch()
        ready = self.ready(first)
        self.assertEqual(self.stop(first), (0, ""))
        before = (self.state / IDENTITY).read_bytes()
        other = self.root / "external-project"
        other.mkdir()
        child = self.launch(project=other)
        output, errors = child.communicate(timeout=10)
        self.assertEqual((child.returncode, output), (2, ""))
        self.assertIn("belongs to another project", errors)
        self.assertNotIn(self.token(ready), errors)
        self.assertEqual((self.state / IDENTITY).read_bytes(), before)

    def test_linked_databases_sidecars_and_saved_directories_preserve_outside_state(self):
        valid = self.launch()
        ready = self.ready(valid)
        self.assertEqual(self.stop(valid), (0, ""))
        names = [database + suffix for database in ("state.sqlite3", "workflows.sqlite3")
            for suffix in ("", "-wal", "-shm", "-journal")]
        for index, name in enumerate(names + ["hardlink", "runs", "runs/saved/environments"]):
            with self.subTest(entry=name):
                state = self.root / ("linked-state-" + str(index))
                shutil.copytree(self.state, state)
                directory = name in {"runs", "runs/saved/environments"}
                outside = self.root / ("untouched-target-" + str(index))
                if directory:
                    outside.mkdir(mode=0o700)
                    target = outside / "preserved.txt"
                    target.write_bytes(b"Unrelated evidence must survive refusal\n")
                    entry = state / name
                    entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    entry.symlink_to(outside, target_is_directory=True)
                else:
                    target = outside
                    target.write_bytes(b"")  # Reproduces the empty SQLite escape found by QA.
                    target.chmod(0o600)
                    entry = state / ("state.sqlite3" if name == "hardlink" else name)
                    if entry.exists():
                        entry.unlink()
                    if name == "hardlink":
                        os.link(target, entry)
                    else:
                        entry.symlink_to(target)
                before = self.unchanged_file(target)
                identity = (state / IDENTITY).read_bytes()
                child = self.launch(state=state)
                output, errors = child.communicate(timeout=10)
                self.assertEqual((child.returncode, output), (2, ""))
                self.assertNotIn(str(target), errors)
                self.assertNotIn(self.token(ready), errors)
                self.assertEqual(self.unchanged_file(target), before)
                self.assertEqual((state / IDENTITY).read_bytes(), identity)
                self.assertTrue(entry.is_symlink() if name != "hardlink" else entry.exists())

    def test_saved_candidate_links_and_current_venv_restart_but_obsolete_aliases_fail_closed(self):
        first = self.launch()
        ready = self.ready(first)
        self.assertEqual(self.stop(first), (0, ""))
        runs = self.state / "runs"
        runs.mkdir(mode=0o700, exist_ok=True)
        saved = runs / "saved"
        saved.mkdir(mode=0o700)
        candidate = saved / "candidate"
        candidate.mkdir(mode=0o700)
        source = candidate / "source.txt"
        source.write_text("Saved candidate evidence\n")
        source.chmod(0o644)  # Candidate modes may be public inside the private state root.
        (candidate / "internal-file").symlink_to("source.txt")
        (saved / "internal-directory").symlink_to(candidate, target_is_directory=True)
        binary = saved / "environments" / "digest" / "venv" / "bin"
        binary.mkdir(parents=True, mode=0o700)
        python = binary / "python"
        python.symlink_to(self.python.resolve())
        second = self.launch()
        restarted = self.ready(second)
        self.assertEqual(self.token(restarted), self.token(ready))
        self.assertEqual(self.stop(second), (0, ""))
        before = self.unchanged_file(self.state / "state.sqlite3")
        obsolete = self.root / "old-app-python"
        obsolete.write_text("Obsolete synthetic interpreter, never executed\n")
        for missing in (False, True):
            with self.subTest(dangling=missing):
                python.unlink()
                python.symlink_to(obsolete if not missing else self.root / "missing-old-app-python")
                old_bytes = self.unchanged_file(obsolete)
                child = self.launch()
                output, errors = child.communicate(timeout=10)
                self.assertEqual((child.returncode, output), (2, ""))
                self.assertNotIn(self.token(ready), errors)
                self.assertEqual(self.unchanged_file(self.state / "state.sqlite3"), before)
                self.assertEqual(self.unchanged_file(obsolete), old_bytes)
                self.assertEqual(source.read_text(), "Saved candidate evidence\n")
                self.assertTrue(python.is_symlink())

    def test_startup_failure_never_emits_ready_or_raw_exception(self):
        script = '''from contextlib import asynccontextmanager
import parallax.desktop as desktop
import parallax.server as server
original = server.create_app
def failed_app(*args, **kwargs):
    app = original(*args, **kwargs)
    @asynccontextmanager
    async def failure(app):
        raise RuntimeError("synthetic-secret http://127.0.0.1/?token=do-not-log")
        yield
    app.router.lifespan_context = failure
    return app
server.create_app = failed_app
raise SystemExit(desktop.main())
'''
        child = self.launch(script=script)
        # Keep stdin open: communicate() would request EOF shutdown before
        # this synthetic startup failure, changing the condition under test.
        child.wait(timeout=10)
        output, errors = child.stdout.read(), child.stderr.read()
        self.assertEqual((child.returncode, output), (1, ""))
        self.assertIn("could not start", errors)
        self.assertNotIn("synthetic-secret", errors)
        self.assertNotIn("do-not-log", errors)
        self.assertNotIn("Traceback", errors)

    def test_stop_and_eof_before_readiness_bound_hung_startup(self):
        script = '''import asyncio
from contextlib import asynccontextmanager
import parallax.desktop as desktop
import parallax.server as server
original = server.create_app
def hung_app(*args, **kwargs):
    app = original(*args, **kwargs)
    @asynccontextmanager
    async def startup(app):
        (app.state.engine.store.home / "lifespan-started").write_text("Saved startup boundary")
        await asyncio.Event().wait()
        yield
    app.router.lifespan_context = startup
    return app
server.create_app = hung_app
raise SystemExit(desktop.main())
'''
        for command in ("stop", "eof"):
            with self.subTest(control=command):
                state = self.root / ("hung-startup-" + command)
                child = self.launch(state=state, script=script)
                marker = state / "lifespan-started"
                self.wait_for_file(marker, child)
                before = self.unchanged_file(marker)
                started = time.monotonic()
                if command == "stop":
                    status, errors = self.stop(child)
                    output = ""
                else:
                    child.stdin.close()
                    child.stdin = None
                    output, errors = child.communicate(timeout=10)
                    status = child.returncode
                self.assertLess(time.monotonic() - started, 9.8)
                self.assertEqual((status, output), (1, ""))
                self.assertNotIn("Traceback", errors)
                self.assertEqual(self.unchanged_file(marker), before)

    def test_hung_shutdown_is_bounded_without_exposing_launch_capability(self):
        script = '''import asyncio
from contextlib import asynccontextmanager
import parallax.desktop as desktop
import parallax.server as server
original = server.create_app
def hung_app(*args, **kwargs):
    app = original(*args, **kwargs)
    lifecycle = app.router.lifespan_context
    @asynccontextmanager
    async def shutdown(app):
        async with lifecycle(app):
            yield
            await asyncio.Event().wait()
    app.router.lifespan_context = shutdown
    return app
server.create_app = hung_app
raise SystemExit(desktop.main())
'''
        child = self.launch(script=script)
        ready = self.ready(child)
        started = time.monotonic()
        status, errors = self.stop(child)
        self.assertLess(time.monotonic() - started, 9.8)
        self.assertEqual(status, 1)
        self.assertIn("stopped unexpectedly", errors)
        self.assertNotIn(self.token(ready), errors)
        self.assertNotIn("Traceback", errors)

    def test_shutdown_interrupts_actual_engine_job_and_preserves_consumed_budget(self):
        script = '''import os
import sys
import parallax.desktop as desktop
from parallax.providers import _capture
class SlowRegistry:
    async def discover(self): return []
    def validate(self, participant): return {"model": "synthetic", "effort": None}
    async def run(self, provider, **kwargs):
        await _capture([sys.executable, "-I", "-B", "-c", "import time; time.sleep(120)"],
            cwd=kwargs["workspace"], env={"PATH": os.defpath}, timeout=120,
            cancel_event=kwargs["cancel_event"], on_event=kwargs["on_event"])
original = desktop.run_server
async def test_server(*args, **kwargs):
    return await original(*args, **kwargs, registry=SlowRegistry())
desktop.run_server = test_server
raise SystemExit(desktop.main())
'''
        for command in ("stop", "eof"):
            with self.subTest(control=command):
                state = self.root / ("active-worker-" + command)
                child = self.launch(state=state, script=script)
                ready = self.ready(child)
                authorization = {"Authorization": "Bearer " + self.token(ready)}
                status, _, body = self.request(ready, "POST", "/api/runs", {"workspace": str(self.project), "prompt": "Synthetic bounded review",
                    "mode": "review", "integrate": False, "team": [{"provider": "claude"}]}, authorization)
                self.assertEqual(status, 200, body)
                identifier = json.loads(body)["run_id"]
                store = Store(state)
                try:
                    started = []
                    deadline = time.monotonic() + 5
                    while not started and time.monotonic() < deadline:
                        started = [event["data"] for event in store.events(identifier)
                            if event["data"].get("type") == "parallax.process_started"]
                        if not started:
                            time.sleep(0.02)
                    self.assertEqual(len(started), 1, "Synthetic owned child did not start")
                    time.sleep(0.25)
                    if command == "stop":
                        self.assertEqual(self.stop(child), (0, ""))
                    else:
                        child.stdin.close()
                        child.stdin = None
                        output, errors = child.communicate(timeout=15)
                        self.assertEqual((child.returncode, output, errors), (0, "", ""))
                    for event in started:
                        with self.assertRaises(ProcessLookupError):
                            os.kill(event["pid"], 0)
                    result = store.get(identifier)
                    self.assertEqual(result["status"], "interrupted")
                    consumed = result["artifacts"]["runtime_seconds"]
                    self.assertGreaterEqual(consumed, 0.2)
                    with store.connect() as db:
                        budget = db.execute("SELECT used,active FROM execution_budget WHERE run_id=?", (identifier,)).fetchone()
                        self.assertEqual(budget["active"], 0)
                        self.assertGreaterEqual(budget["used"], 0.2)
                finally:
                    store.close()
                restarted = self.launch(state=state)
                new_ready = self.ready(restarted)
                status, _, body = self.request(new_ready, "GET", "/api/runs/" + identifier,
                    headers={"Authorization": "Bearer " + self.token(new_ready)})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], "interrupted")
                self.assertGreaterEqual(json.loads(body)["artifacts"]["runtime_seconds"], consumed)
                self.assertEqual(self.stop(restarted), (0, ""))
                self.assertEqual((self.project / "source.txt").read_text(), "Developer's original work\n")


class DesktopEnvironmentIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_python_upgrade_uses_new_private_cache_without_resetting_saved_evidence_or_budget(self):
        from parallax import engine as engine_module
        from parallax.engine import Engine
        from parallax.models import CheckSpec
        from parallax.providers import Captured
        with tempfile.TemporaryDirectory(prefix="parallax-desktop-python-identity-") as temporary:
            root = Path(temporary).resolve()
            project = root / "project"
            project.mkdir()
            manifest = project / "requirements.txt"
            manifest.write_text("fixture==1.0 --hash=sha256:" + "a" * 64 + "\n")
            source = manifest.read_bytes()
            store = Store(root / "state")
            try:
                engine = Engine(store, registry=object(), memory=False)
                identifier = str(uuid4())
                directory = store.home / "runs" / identifier
                directory.mkdir(parents=True)
                saved = {"run_id": identifier, "spec": {"workspace": str(project)}, "status": "interrupted",
                    "tasks": [{"id": "saved", "status": "completed", "result": {"evidence": "Keep this"}}],
                    "artifacts": {"directory": str(directory), "runtime_seconds": 23.5, "candidate_digest": "saved-digest"}}
                store.save(saved)
                evidence = store.event(identifier, "review", {"decision": "Saved independent review"})
                engine.cancel_flags[identifier] = asyncio.Event()
                engine.budget.begin(identifier, 23.5, 300)
                engine.budget.end(identifier, 23.5)
                calls = []

                async def provision(run_id, argv, workspace, env, timeout, **kwargs):
                    calls.append(argv)
                    if argv[1:3] == ["-m", "venv"]:
                        binary = Path(argv[3]) / "bin" / "python"
                        binary.parent.mkdir(parents=True)
                        binary.write_text("Synthetic cache interpreter; never executed\n")
                    return Captured(0, "", "", [])

                engine._command = provision
                current = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro, "final", 0)
                changed_version = (*current[:2], current[2] + 1, "final", 0)
                executable = str(root / "installed-app" / "python3")
                identities = [(executable, current, "synthetic-cache-tag"),
                    (executable, changed_version, "synthetic-cache-tag"),
                    (executable, current, "synthetic-other-cache-tag"),
                    (str(root / "another-app" / "python3"), current, "synthetic-cache-tag")]
                binaries = []
                preserved = []
                for executable, version, tag in identities:
                    with patch.object(engine_module, "sys", SimpleNamespace(executable=executable,
                            version_info=version, implementation=SimpleNamespace(cache_tag=tag))):
                        _, binary = await engine._ensure_environment(identifier, project,
                            [CheckSpec(name="tests", argv=["python", "-m", "unittest"])])
                        count = len(calls)
                        _, same = await engine._ensure_environment(identifier, project,
                            [CheckSpec(name="tests", argv=["python", "-m", "unittest"])])
                        self.assertEqual(same, binary)
                        self.assertEqual(len(calls), count, "Unchanged runtime should reuse its provisioned cache")
                    binaries.append(binary)
                    record = binary.parent.parent.parent / "retained-evidence.txt"
                    record.write_text("Preserve older cache evidence\n")
                    preserved.append(record)
                self.assertEqual(len(set(binaries)), len(identities),
                    "Interpreter path, version and cache tag must independently invalidate Python caches")
                self.assertEqual(len(calls), 3 * len(identities))
                self.assertEqual(store.get(identifier), saved)
                self.assertEqual(store.events(identifier)[0], evidence)
                self.assertTrue(all(path.read_text() == "Preserve older cache evidence\n" for path in preserved))
                self.assertEqual(manifest.read_bytes(), source)
                with store.connect() as db:
                    budget = db.execute("SELECT used,active FROM execution_budget WHERE run_id=?", (identifier,)).fetchone()
                    self.assertEqual((budget["used"], budget["active"]), (23.5, 0))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
