"""Exercise the actual Swift startup parser without starting a GUI or provider."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Requires macOS Swift toolchain")
class DesktopLauncherTests(unittest.TestCase):
    def test_only_owned_local_ready_records_can_open_the_browser(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="parallax-launcher-protocol-") as directory:
            executable = Path(directory) / "protocol-cases"
            built = subprocess.run(["swiftc", "-parse-as-library", "-D", "PROTOCOL_TEST", "-warnings-as-errors",
                                    str(root / "desktop/macos/Launcher.swift"),
                                    str(root / "tests/desktop_protocol_cases.swift"), "-o", str(executable)],
                                   capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("24 launcher protocol cases passed", result.stdout)
            self.assertNotIn("token=", result.stdout + result.stderr)
