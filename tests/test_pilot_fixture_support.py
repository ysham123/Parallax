"""Acceptance fixtures must be disposable, portable and faithful on PR revisions."""
import tempfile
import argparse
import unittest
from pathlib import Path

import httpx

from pilot_fixture_support import FixtureGitHub, fixture_asset, fixture_options, prepare_fixture_root, loopback_origin


class PilotFixtureSupportTest(unittest.TestCase):
    def test_new_owned_root_and_configurable_state(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = (Path(temp) / "demo").resolve()
            options = fixture_options(["--root", str(expected), "--port", "8767", "--state-name", "review-2"])
            root, project = prepare_fixture_root(options.root)
            self.assertEqual((root, project), (expected, expected / "project"))
            self.assertEqual(options.port, 8767)
            self.assertEqual(options.state_name, "review-2")
            self.assertEqual(prepare_fixture_root(root), (root, project))

    def test_ancestor_alias_is_canonical_but_direct_root_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "canonical"
            target.mkdir()
            alias = Path(temp) / "ancestor-alias"
            alias.symlink_to(target, target_is_directory=True)
            root, project = prepare_fixture_root(alias / "new-fixture")
            self.assertEqual(root, (target / "new-fixture").resolve())
            self.assertEqual(project, root / "project")
            direct = Path(temp) / "direct-fixture"
            direct.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                prepare_fixture_root(direct)

    def test_http_acceptance_origin_is_loopback_only(self):
        for value in ("http://127.0.0.1:8778", "https://[::1]:443/", "http://localhost:8766"):
            self.assertEqual(loopback_origin(value), value.rstrip("/"))
        for value in ("http://example.com:8766", "http://192.168.0.1:8766", "file://127.0.0.1:8766",
                      "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:not-a-port",
                      "http://127.0.0.1", "http://user:pass@127.0.0.1:8766", "http://127.0.0.1:8766/path",
                      "http://127.0.0.1:8766?secret=1", "http://127.0.0.1:8766#fragment"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                loopback_origin(value)

    def test_existing_developer_project_and_project_symlink_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo"
            (root / "project").mkdir(parents=True)
            important = root / "project" / "user.py"
            important.write_text("preserve me")
            with self.assertRaisesRegex(ValueError, "Refusing an existing project"):
                prepare_fixture_root(root)
            self.assertEqual(important.read_text(), "preserve me")
            other = Path(temp) / "linked"
            other.mkdir()
            (other / "project").symlink_to(root / "project", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                prepare_fixture_root(other)

    def test_static_asset_cannot_escape_fixture_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            (root / "assets").mkdir(parents=True)
            asset = root / "assets" / "app.js"
            asset.write_text("fixture")
            secret = Path(temp) / "private.txt"
            secret.write_text("must not serve")
            (root / "assets" / "linked.js").symlink_to(secret)
            self.assertEqual(fixture_asset(root, "/assets/app.js"), asset.resolve())
            for path in ("/assets/../../private.txt", "/assets/linked.js", "/assets/missing.js"):
                self.assertIsNone(fixture_asset(root, path))

    def test_simulated_revision_keeps_pr_and_changes_exact_commit(self):
        remote = FixtureGitHub("b" * 40, "c" * 40)
        def call(method, path, body=None):
            return remote(httpx.Request(method, "https://api.github.com" + path, json=body)).json()
        call("POST", "/repos/fixture/repo/git/refs", {"ref": "refs/heads/parallax/task", "sha": "b" * 40})
        def commit(expected, tree, marker):
            remote.remote["tree"] = tree
            return call("POST", "/graphql", {"variables": {"input": {"expectedHeadOid": expected, "message": {"body": marker}}}})
        first = commit("b" * 40, "d" * 40, "first")["data"]["createCommitOnBranch"]["commit"]["oid"]
        pr = call("POST", "/repos/fixture/repo/pulls", {})
        second = commit(first, "e" * 40, "revision")["data"]["createCommitOnBranch"]["commit"]["oid"]
        updated = call("GET", "/repos/fixture/repo/pulls/1")
        self.assertNotEqual(first, second)
        self.assertEqual(updated["number"], pr["number"])
        self.assertEqual(updated["head"]["sha"], second)
        self.assertEqual(call("GET", "/repos/fixture/repo/git/commits/" + first)["tree"]["sha"], "d" * 40)
        self.assertEqual(call("GET", "/repos/fixture/repo/git/commits/" + second)["tree"]["sha"], "e" * 40)
        self.assertIn("errors", commit(first, "f" * 40, "external head mismatch"))
        self.assertEqual(remote.remote["head"], second)
