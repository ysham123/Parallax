import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "claude_bridge.py"
SPEC = importlib.util.spec_from_file_location("claude_bridge", SCRIPT)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)
SESSION = "12345678-1234-4123-8123-123456789abc"


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.fake = self.root / "claude"
        self.fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys, time\n"
            "if sys.argv[1:] == ['auth', 'status']:\n"
            "    print(json.dumps({'loggedIn': os.getenv('FAKE_AUTH_FAIL') != '1'}))\n"
            "    sys.exit(0)\n"
            "args_file = os.getenv('FAKE_ARGS_FILE')\n"
            "if args_file: pathlib.Path(args_file).write_text(json.dumps(sys.argv[1:]))\n"
            "sys.stdin.read()\n"
            "if os.getenv('FAKE_SLEEP'): time.sleep(float(os.getenv('FAKE_SLEEP')))\n"
            "if os.getenv('FAKE_WRITE_FILE'):\n"
            "    pathlib.Path(os.getenv('FAKE_WRITE_FILE')).write_text(os.getenv('FAKE_WRITE_VALUE', 'new'))\n"
            "if os.getenv('FAKE_MALFORMED'): print('not json')\n"
            "else: print(json.dumps({'result': 'Claude answer', 'session_id': '" + SESSION + "', 'is_error': False}))\n"
        )
        self.fake.chmod(0o755)

    def run_bridge(self, mode="consult", resume=None, timeout=5, **environment):
        with patch.dict(os.environ, environment, clear=False):
            return bridge.run(self.workspace, mode, "Assess this project", resume, timeout, str(self.fake))

    def test_read_only_consultation_and_follow_up(self):
        args_file = self.root / "args.json"
        result = self.run_bridge(FAKE_ARGS_FILE=str(args_file))
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "Claude answer")
        self.assertEqual(result["session_id"], SESSION)
        self.assertEqual(result["changed_files"], [])
        args = json.loads(args_file.read_text())
        self.assertEqual(args[args.index("--tools") + 1], bridge.CONSULT_TOOLS)
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("--restricted", args)

        follow_up = self.run_bridge(resume=SESSION, FAKE_ARGS_FILE=str(args_file))
        self.assertTrue(follow_up["ok"])
        args = json.loads(args_file.read_text())
        self.assertEqual(args[args.index("--resume") + 1], SESSION)

    def test_edit_reports_changes_and_preserves_existing_dirty_file(self):
        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        existing = self.workspace / "existing.txt"
        existing.write_text("original")
        subprocess.run(["git", "add", "existing.txt"], cwd=self.workspace, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-qm", "initial"], cwd=self.workspace, check=True)
        existing.write_text("pre-existing change")
        new_file = self.workspace / "new.txt"
        args_file = self.root / "args.json"
        result = self.run_bridge(mode="edit", FAKE_WRITE_FILE=str(new_file),
                                 FAKE_ARGS_FILE=str(args_file))
        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_files"], ["new.txt"])
        self.assertEqual(existing.read_text(), "pre-existing change")
        args = json.loads(args_file.read_text())
        self.assertEqual(args[args.index("--tools") + 1], bridge.EDIT_TOOLS)
        self.assertEqual(args[args.index("--permission-mode") + 1], "acceptEdits")

        result = self.run_bridge(mode="edit", FAKE_WRITE_FILE=str(existing),
                                 FAKE_WRITE_VALUE="Claude modified it")
        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_files"], ["existing.txt"])

    def test_read_only_write_is_reported_as_failure(self):
        path = self.workspace / "unexpected.txt"
        result = self.run_bridge(FAKE_WRITE_FILE=str(path))
        self.assertFalse(result["ok"])
        self.assertEqual(result["changed_files"], ["unexpected.txt"])

    def test_authentication_failure(self):
        result = self.run_bridge(FAKE_AUTH_FAIL="1")
        self.assertFalse(result["ok"])
        self.assertIn("not signed in", result["error"])

    def test_malformed_result(self):
        result = self.run_bridge(FAKE_MALFORMED="1")
        self.assertFalse(result["ok"])
        self.assertIn("malformed JSON", result["error"])

    def test_timeout(self):
        result = self.run_bridge(timeout=1, FAKE_SLEEP="3")
        self.assertFalse(result["ok"])
        self.assertIn("within 1 seconds", result["error"])


if __name__ == "__main__":
    unittest.main()
