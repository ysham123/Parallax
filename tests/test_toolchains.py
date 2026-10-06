"""User-local Node/npm runs with narrow reads and unchanged sandbox boundaries."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parallax.engine import _node_toolchain_reads, _sandbox_check


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="parallax-toolchain-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.prefix = self.home / "hostedtoolcache/node/22/arm64"
        self.package = self.prefix / "lib/node_modules/npm"
        self.package.joinpath("bin").mkdir(parents=True)
        self.package.joinpath("lib").mkdir()
        self.package.joinpath("package.json").write_text('{"name":"npm"}')
        self.npm = self.package / "bin/npm-cli.js"
        self.npm.write_text("#!/usr/bin/env node\n")
        self.npm.chmod(0o755)
        self.node = self.prefix / "bin/node"
        self.node.parent.mkdir(parents=True)
        self.node.write_text("selected-node")
        self.node.chmod(0o755)
        self.aliases = self.home / ".local/bin"
        self.aliases.mkdir(parents=True)
        self.aliases.joinpath("npm").symlink_to(self.npm)
        self.aliases.joinpath("node").symlink_to(self.node)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.canary = self.home / "host-secret.txt"
        self.canary.write_text("HOST_SECRET")

    def which(self, command):
        return {"node": str(self.aliases / "node"), "npm": str(self.aliases / "npm"),
                "bwrap": "/usr/bin/bwrap"}.get(command)

    def test_macos_npm_package_and_exact_node_files_are_readable_only(self):
        actual_exists = Path.exists
        with patch("parallax.engine.sys.platform", "darwin"), patch("parallax.engine.shutil.which", self.which), patch.object(Path, "exists", lambda path: str(path) == "/usr/bin/sandbox-exec" or actual_exists(path)):
            command = _sandbox_check(["npm", "run", "test"], self.workspace)
        profile = command[2]
        self.assertIn(f'(subpath {json.dumps(str(self.package))})', profile)
        self.assertIn(f'(literal {json.dumps(str(self.node))})', profile)
        self.assertNotIn(f'(subpath {json.dumps(str(self.prefix))})', profile)
        self.assertNotIn(f'(subpath {json.dumps(str(self.home))})', profile)
        self.assertNotIn(f'(subpath {json.dumps(str(self.aliases))})', profile)
        writes = profile.split("(allow file-write*", 1)[1].split("(deny file-read-data", 1)[0]
        self.assertNotIn(str(self.package), writes)
        self.assertNotIn(str(self.node), writes)
        self.assertEqual(command[3], str(self.npm))

    def test_linux_exact_path_aliases_survive_home_mask_and_stay_readonly(self):
        with patch("parallax.engine.sys.platform", "linux"), patch("parallax.engine.shutil.which", self.which), patch("parallax.engine.Path.home", return_value=self.home):
            command = _sandbox_check(["npm", "run", "test"], self.workspace)
        home_mask = next(index for index in range(len(command) - 1)
                         if command[index:index + 2] == ["--tmpfs", str(self.home)])
        for path in (self.node, self.npm, self.package, self.aliases / "node", self.aliases / "npm"):
            mount = next(index for index in range(len(command) - 2)
                         if command[index:index + 3] == ["--ro-bind", str(path), str(path)])
            self.assertGreater(mount, home_mask)
            self.assertNotIn(["--bind", str(path), str(path)],
                             [command[index:index + 3] for index in range(len(command) - 2)])
        for broad in (self.home, self.prefix, self.aliases):
            self.assertNotIn(["--ro-bind", str(broad), str(broad)],
                             [command[index:index + 3] for index in range(len(command) - 2)])
        self.assertEqual(command[command.index("--") + 1], str(self.npm))

    def test_npm_package_requires_fixed_entrypoint_and_matching_manifest(self):
        with patch("parallax.engine.shutil.which", self.which):
            self.package.joinpath("package.json").write_text('{"name":"other"}')
            self.assertNotIn(self.package, _node_toolchain_reads(["npm", "test"]))
            self.package.joinpath("package.json").write_text('invalid')
            self.assertNotIn(self.package, _node_toolchain_reads(["npm", "test"]))
            self.package.joinpath("package.json").write_text('{"name":"npm"}')
            self.assertIn(self.package, _node_toolchain_reads(["npm", "test"]))
            self.assertEqual(_node_toolchain_reads([sys.executable, "check.py"]), set())

    def test_node_alone_exposes_files_without_npm_or_toolchain_directory(self):
        with patch("parallax.engine.shutil.which", self.which):
            paths = _node_toolchain_reads(["node", "check.js"])
        self.assertEqual(paths, {self.node, self.aliases / "node"})
        self.assertNotIn(self.package, paths)
        self.assertNotIn(self.prefix, paths)
        self.assertNotIn(self.aliases, paths)

    @unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists() and shutil.which("node"), "requires macOS and Node")
    def test_live_user_local_npm_reads_runtime_but_cannot_read_or_write_host(self):
        # A real copied Node binary and npm-shaped module tree reproduce the
        # hosted-toolcache placement without installing or running dependencies.
        shutil.copyfile(Path(shutil.which("node")).resolve(), self.node)
        self.node.chmod(0o755)
        self.package.joinpath("lib/probe.js").write_text("module.exports = 'RUNTIME_READ_OK';\n")
        self.npm.write_text("#!/usr/bin/env node\n" + "\n".join([
            "const fs = require('node:fs');",
            "const assert = require('node:assert/strict');",
            "assert.equal(require('../lib/probe.js'), 'RUNTIME_READ_OK');",
            f"assert.throws(() => fs.readFileSync({json.dumps(str(self.canary))}, 'utf8'));",
            f"assert.throws(() => fs.writeFileSync({json.dumps(str(self.home / 'forbidden-write.txt'))}, 'bad'));",
            f"assert.throws(() => fs.writeFileSync({json.dumps(str(self.package / 'lib/probe.js'))}, 'bad'));",
            f"fs.writeFileSync({json.dumps(str(self.workspace / 'allowed-write.txt'))}, 'private');",
            "console.log('RUNTIME_AND_CANARIES_PASSED');",
        ]) + "\n")
        with patch("parallax.engine.shutil.which", self.which):
            command = _sandbox_check(["npm", "run", "test"], self.workspace)
        environment = {**os.environ, "PATH": str(self.aliases) + os.pathsep + os.environ.get("PATH", ""), "HOME": str(self.workspace)}
        result = subprocess.run(command, cwd=self.workspace, env=environment,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RUNTIME_AND_CANARIES_PASSED", result.stdout)
        self.assertEqual(self.canary.read_text(), "HOST_SECRET")
        self.assertFalse(self.home.joinpath("forbidden-write.txt").exists())
        self.assertEqual(self.workspace.joinpath("allowed-write.txt").read_text(), "private")


if __name__ == "__main__":
    unittest.main()
