"""WSL diagnostics fail closed without running project code or leaking values."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts/check_wsl.py"
spec = importlib.util.spec_from_file_location("wsl_preflight", path)
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


class WSLPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="parallax-wsl-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "source.txt").write_text("UNCHANGED_PROJECT")
        self.bin = self.root / "tools"
        self.bin.mkdir()
        for name in ("git", "bwrap", "socat", "codex", "claude", "agy", "grok"):
            tool = self.bin / name
            tool.write_text("#!/bin/sh\nexit 0\n")
            tool.chmod(0o700)
        self.calls = []
        self.mountinfo = "1 0 0:1 / / rw - ext4 /dev/synthetic rw\n"

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        name = Path(argv[0]).name
        versions = {"git": "2.46.0", "bwrap": "0.11.0", "socat": "1.8.0.1",
                    "codex": "0.162.1", "claude": "2.1.295", "agy": "1.3.3"}
        return preflight.Probe(0, ("tool " + versions[name]).encode())

    def which(self, name, *, path):
        return str(self.bin / name)

    def assess(self, *, sandbox=lambda *args, **kwargs: True, **kwargs):
        values = {"PATH": str(self.bin), "OPENAI_API_KEY": "PRIVATE_ENV_CANARY",
                  "CODEX_HOME": "PRIVATE_HOME_CANARY", "PYTHONPATH": "PRIVATE_INJECTION_CANARY"}
        with patch.dict(os.environ, values, clear=True):
            report = preflight.assess(kwargs.pop("project", self.project), platform_name=kwargs.pop("platform_name", "linux"),
                kernel=kwargs.pop("kernel", "6.6.87.2-microsoft-standard-WSL2"),
                mountinfo=kwargs.pop("mountinfo", self.mountinfo), which=self.which, runner=kwargs.pop("runner", self.runner),
                sandbox=sandbox, **kwargs)
        self.assertEqual((self.project / "source.txt").read_text(), "UNCHANGED_PROJECT")
        self.assertNotIn("PRIVATE_", json.dumps(report))
        self.assertNotIn(str(self.project), json.dumps(report))
        return report

    def test_unavailable_or_native_windows_never_launches_tools(self):
        for platform_name, kernel in (("win32", "Microsoft"), ("darwin", "WSL2 Microsoft"),
                                      ("linux", "5.15.0-generic"), ("linux", "4.4.0-Microsoft")):
            with self.subTest(platform=platform_name, kernel=kernel):
                report = self.assess(platform_name=platform_name, kernel=kernel)
                self.assertFalse(report["ok"])
                self.assertEqual(report["wsl_acceptance"], "unverified")
        self.assertEqual(self.calls, [])

    def test_mocked_capabilities_remain_distinct_from_provider_acceptance(self):
        report = self.assess(providers=("codex", "claude"))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["status"], "capabilities_verified")
        self.assertEqual(report["wsl_acceptance"], "unverified")
        self.assertEqual(report["provider_calls"], 0)
        self.assertIn("model inference", report["scope"])
        self.assertEqual({Path(argv[0]).name for argv, _ in self.calls}, {"git", "bwrap", "socat", "codex", "claude"})
        for argv, options in self.calls:
            self.assertIn(argv[1], ("--version", "-V"))
            self.assertEqual(options["timeout"], 5)
            self.assertNotIn("OPENAI_API_KEY", options["env"])
            self.assertNotIn("CODEX_HOME", options["env"])
            self.assertNotIn("PYTHONPATH", options["env"])
            self.assertFalse(Path(options["env"]["HOME"]).exists())

    def test_windows_custom_mount_and_symlink_alias_are_refused(self):
        windows = self.root / "custom Windows mount"
        windows.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(windows, target_is_directory=True)
        escaped = str(windows).replace(" ", "\\040")
        mounts = self.mountinfo + f"2 1 0:2 / {escaped} rw - 9p C: rw\n"
        for project in (windows, alias):
            with self.subTest(project=project):
                self.assertFalse(self.assess(project=project, mountinfo=mounts)["ok"])
        self.assertEqual(self.calls, [])

    def test_unknown_filesystem_and_missing_project_do_not_pass(self):
        for options in ({"mountinfo": ""}, {"mountinfo": self.mountinfo.replace("ext4", "drvfs")},
                        {"project": self.root / "not-created"}):
            with self.subTest(options=options):
                self.assertFalse(self.assess(**options)["ok"])
        self.assertEqual(self.calls, [])

    def test_stacked_mounts_do_not_hide_shared_filesystem(self):
        mount = str(self.project)
        mounts = self.mountinfo + f"2 1 0:2 / {mount} rw - ext4 /dev/synthetic rw\n3 1 0:3 / {mount} rw - 9p C: rw\n"
        self.assertFalse(self.assess(mountinfo=mounts)["ok"])
        self.assertEqual(self.calls, [])

    def test_temporary_directory_inside_project_is_refused_before_execution(self):
        before = set(self.project.iterdir())
        with patch.object(preflight.tempfile, "gettempdir", return_value=str(self.project)):
            self.assertFalse(self.assess()["ok"])
        self.assertEqual(set(self.project.iterdir()), before)
        self.assertEqual(self.calls, [])

    def test_project_python_runtime_is_refused_before_execution(self):
        runtime = self.project / "runtime"
        runtime.mkdir()
        python = runtime / "python"
        python.write_text("#!/bin/sh\nexit 0\n"); python.chmod(0o700)
        with patch.object(preflight.sys, "executable", str(python)), patch.object(preflight.sys, "base_prefix", str(runtime)):
            self.assertFalse(self.assess()["ok"])
        self.assertEqual(self.calls, [])

    def test_windows_virtualenv_is_refused_even_with_linux_interpreter_alias(self):
        prefix = self.root / "windows-venv"
        prefix.mkdir()
        mounts = self.mountinfo + f"2 1 0:2 / {prefix} rw - 9p C: rw\n"
        with patch.object(preflight.sys, "prefix", str(prefix)):
            self.assertFalse(self.assess(mountinfo=mounts)["ok"])
        self.assertEqual(self.calls, [])

    def test_copied_windows_executable_and_windows_target_alias_are_refused(self):
        codex = self.bin / "codex"
        codex.write_bytes(b"MZ" + b"synthetic-windows-binary")
        self.assertFalse(self.assess()["ok"])
        codex.unlink()
        target = self.bin / "codex.exe"
        target.write_text("#!/bin/sh\nexit 0\n"); target.chmod(0o700)
        codex.symlink_to(target)
        self.assertFalse(self.assess()["ok"])
        self.assertEqual(self.calls, [])

    def test_project_cli_alias_never_executes_project_code(self):
        tool = self.project / "codex"
        tool.write_text("#!/bin/sh\nexit 0\n"); tool.chmod(0o700)
        (self.bin / "codex").unlink()
        (self.bin / "codex").symlink_to(tool)
        self.assertFalse(self.assess()["ok"])
        self.assertEqual(self.calls, [])

    def test_path_filter_uses_canonical_mounts_and_excludes_project(self):
        windows = self.root / "windows"; windows.mkdir()
        alias = self.root / "windows-alias"; alias.symlink_to(windows, target_is_directory=True)
        mounts = preflight.mount_table(self.mountinfo + f"2 1 0:2 / {windows} rw - 9p C: rw\n")
        value = os.pathsep.join((str(alias), ".", "", str(self.project), str(self.bin), str(self.bin)))
        self.assertEqual(preflight.linux_search_path(value, mounts, excluded=(self.project,)), str(self.bin))

    def test_native_grok_unsupported_without_executing_it(self):
        self.assertFalse(self.assess(providers=("grok",))["ok"])
        self.assertEqual(self.calls, [])

    def test_raw_diagnostic_errors_and_output_never_reach_report(self):
        def runner(*args, **kwargs):
            return preflight.Probe(1, b"PRIVATE_STDOUT_CANARY", b"token=PRIVATE_STDERR_CANARY")
        report = self.assess(runner=runner)
        self.assertFalse(report["ok"])
        self.assertTrue(all(tool["version"] is None for tool in report["tools"]))
        self.assertNotIn("STDERR", json.dumps(report))

    def test_namespace_failure_does_not_retry_without_sandbox(self):
        probes = []
        def denied(*args, **kwargs):
            probes.append(args)
            return False
        self.assertFalse(self.assess(sandbox=denied)["ok"])
        self.assertEqual(len(probes), 1)
        self.assertEqual(len(self.calls), 4)

    def test_probe_requires_namespace_evidence_and_positive_negative_canaries(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                arguments = json.loads(argv[-1])
                (Path(arguments["writable"]) / "written.txt").write_text("SYNTHETIC_WRITE")
                evidence = {name: True for name in ("allowed_read", "private_read_denied", "readonly_write_denied",
                    "scratch_write", "user_namespace", "mnt_namespace", "pid_namespace", "net_namespace", "host_loopback_denied")}
                evidence["net_namespace"] = False
                return preflight.Probe(0, json.dumps(evidence).encode())
            with patch.object(preflight.os, "readlink", return_value="synthetic-namespace"):
                self.assertFalse(preflight.sandbox_probe(self.bin / "bwrap", Path(sys.executable), home, env={}, runner=runner))
            command = calls[0]
            for flag in ("--unshare-user", "--unshare-pid", "--unshare-net", "--die-with-parent", "--tmpfs"):
                self.assertIn(flag, command)
            self.assertNotIn("--unshare-user-try", command)
            self.assertNotIn("--ro-bind", command[:3])
            self.assertFalse(any(command[index:index+3] == ["--ro-bind", "/", "/"] for index in range(len(command))))

    @unittest.skipIf(os.name != "posix", "Bounded diagnostic subprocesses are POSIX-only; Windows is refused earlier")
    def test_actual_diagnostics_bound_output_and_clean_inherited_pipe_child(self):
        options = {"env": {"PATH": os.defpath, "HOME": str(self.root)}, "cwd": self.root, "timeout": 1}
        overflow = preflight.bounded_run([sys.executable, "-I", "-c", "print('x'*200000)"], max_output=2048, **{**options, "timeout": 5})
        self.assertEqual(overflow.failure, "output_limit")
        self.assertLessEqual(len(overflow.stdout) + len(overflow.stderr), 2048)
        program = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True)"
        held = preflight.bounded_run([sys.executable, "-I", "-c", program], **options)
        self.assertEqual(held.failure, "timeout")
        child = int(held.stdout.strip())
        ps = next((name for name in ("/bin/ps", "/usr/bin/ps") if Path(name).is_file()), None)
        self.assertIsNotNone(ps)
        state = subprocess.run([ps, "-o", "stat=", "-p", str(child)], capture_output=True, text=True, timeout=2).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)

    @unittest.skipUnless(preflight.is_wsl2(sys.platform, __import__("platform").release()), "Actual WSL2 unavailable on this host")
    def test_actual_wsl2_namespace_canaries(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.defpath, "HOME": directory, "TMPDIR": directory}
            bwrap = __import__("shutil").which("bwrap")
            self.assertIsNotNone(bwrap, "Actual WSL2 acceptance needs installed bubblewrap")
            self.assertTrue(preflight.sandbox_probe(Path(bwrap), Path(sys.executable).resolve(), Path(directory), env=env))


if __name__ == "__main__":
    unittest.main()
