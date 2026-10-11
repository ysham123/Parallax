"""Security and distribution boundaries of the desktop packaging tools."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_macos
import notarize_macos


class MacDistributionTests(unittest.TestCase):
    def archive(self, root: Path, entries: list[tuple[str, bytes | None, str | None]]) -> Path:
        path = root / "runtime.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data, link in entries:
                entry = tarfile.TarInfo(name)
                entry.mode = 0o755 if name.endswith("python3.13") else 0o644
                if link is not None:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = link
                    archive.addfile(entry)
                else:
                    entry.size = len(data or b"")
                    archive.addfile(entry, io.BytesIO(data or b""))
        return path

    def test_safe_runtime_extraction_preserves_relocatable_python_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.archive(root, [("python/bin/python3.13", b"payload", None), ("python/bin/python3", None, "python3.13")])
            destination = root / "bundle"
            build_macos.safe_extract_runtime(archive, destination)
            self.assertEqual((destination / "python/bin/python3").read_bytes(), b"payload")
            self.assertEqual((destination / "python/bin/python3.13").stat().st_mode & 0o777, 0o755)

    def test_malicious_archive_is_refused_before_any_file_is_written(self):
        for malicious in [("../escaped", b"bad", None), ("/absolute", b"bad", None), ("python/link", None, "../../escaped"), ("python/bin", None, "/tmp/escaped")]:
            with self.subTest(malicious=malicious), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self.archive(root, [("python/safe", b"safe", None), malicious])
                destination = root / "bundle"
                with self.assertRaises(ValueError):
                    build_macos.safe_extract_runtime(archive, destination)
                self.assertFalse((destination / "python/safe").exists())
                self.assertFalse((root / "escaped").exists())

    def test_archive_cannot_write_through_a_link_or_replace_duplicate_member(self):
        for entries in [[("python/link", None, "bin"), ("python/link/credentials", b"bad", None)], [("python/safe", b"one", None), ("python/safe", b"two", None)], [("python/a", None, "b"), ("python/b", None, "a")], [("python/ancestor", b"file", None), ("python/ancestor/nested", b"bad", None)]]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises(ValueError):
                    build_macos.safe_extract_runtime(self.archive(root, entries), root / "bundle")

    def test_setup_guide_is_staged_exactly_and_changed_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            guide = root / "desktop/macos/BetaGuide.html"
            guide.parent.mkdir(parents=True)
            guide.write_text("<!doctype html><title>Parallax Beta setup</title><p>Provider setup is explicit.</p>")
            destination = root / "bundle/BetaGuide.html"
            destination.parent.mkdir()
            source_digest = build_macos.sha256(guide)
            manifest = {"desktop/macos/BetaGuide.html": source_digest}
            with mock.patch.object(build_macos, "ROOT", root):
                build_macos.stage_resource(guide, destination, manifest)
                self.assertEqual(destination.read_bytes(), guide.read_bytes())
                guide.write_text("Modified after the captured source inventory")
                with self.assertRaisesRegex(ValueError, "changed"):
                    build_macos.stage_resource(guide, destination, manifest)
            self.assertFalse(destination.exists())

    def test_setup_guide_cannot_stage_a_symlink_outside_curated_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            private = root / "private-file"
            private.write_text("synthetic private bytes")
            guide = root / "desktop/macos/BetaGuide.html"
            guide.parent.mkdir(parents=True)
            guide.symlink_to(private)
            with mock.patch.object(build_macos, "ROOT", root), self.assertRaisesRegex(ValueError, "curated"):
                build_macos.stage_resource(guide, root / "copied-guide.html", {"desktop/macos/BetaGuide.html": build_macos.sha256(private)})
            self.assertFalse((root / "copied-guide.html").exists())

    def test_inventory_detects_payload_change_and_rejects_escaping_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Parallax.app"
            app.mkdir()
            payload = app / "module.py"
            payload.write_text("initial")
            first = build_macos.inventory(app)
            payload.write_text("modified")
            self.assertNotEqual(first, build_macos.inventory(app))
            (app / "credentials").symlink_to(root / "private")
            with self.assertRaises(ValueError):
                build_macos.inventory(app)

    def test_native_payload_cannot_silently_exceed_the_macos_support_label(self):
        app = Path("/synthetic/Parallax.app")
        native = app / "Contents/Resources/runtime.so"
        def commands(args):
            if "lipo" in args[0]:
                return "arm64"
            return "cmd LC_BUILD_VERSION\ncmdsize 32\nplatform MACOS\nminos 99.0\nsdk 99.0"
        with mock.patch.object(build_macos, "macho_files", return_value=[native]), mock.patch.object(build_macos, "run", side_effect=commands), self.assertRaisesRegex(ValueError, "exceeds"):
            build_macos.validate_macho_compatibility(app)

    def test_cached_runtime_tampering_is_refused_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = "a" * 64
            (root / (expected + ".tar.gz")).write_bytes(b"tampered")
            lock = {"url": "https://github.com/astral-sh/python-build-standalone/releases/download/pinned/runtime.tar.gz", "sha256": expected, "size": 8}
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), self.assertRaises(ValueError):
                build_macos.obtain_runtime(lock, root)

    def test_symlink_download_attack_preserves_unrelated_file_before_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cache = root / "cache"
            cache.mkdir(mode=0o700)
            outside = root / "unrelated-user-file"
            outside.write_bytes(b"original unrelated bytes")
            payload = b"synthetic verified archive"
            digest = __import__("hashlib").sha256(payload).hexdigest()
            (cache / (digest + ".tar.gz")).with_suffix(".download").symlink_to(outside)
            lock = {"url": "https://github.com/astral-sh/python-build-standalone/releases/download/pinned/runtime.tar.gz", "sha256": digest, "size": len(payload)}
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(payload)) as download, self.assertRaisesRegex(ValueError, "symlink"):
                build_macos.obtain_runtime(lock, cache)
            self.assertEqual(outside.read_bytes(), b"original unrelated bytes")
            download.assert_not_called()

    def test_valid_download_uses_private_exclusive_file_and_leaves_no_staging_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary).resolve() / "cache"
            payload = b"synthetic verified archive"
            digest = __import__("hashlib").sha256(payload).hexdigest()
            lock = {"url": "https://github.com/astral-sh/python-build-standalone/releases/download/pinned/runtime.tar.gz", "sha256": digest, "size": len(payload)}
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                archive = build_macos.obtain_runtime(lock, cache)
            self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(cache.iterdir()), [archive])

    def test_public_or_symlinked_cache_is_refused_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            public = root / "public-cache"
            public.mkdir(mode=0o755)
            alias = root / "cache-alias"
            alias.symlink_to(public)
            lock = {"url": "https://github.com/astral-sh/python-build-standalone/releases/download/pinned/runtime.tar.gz", "sha256": "a" * 64, "size": 1}
            for cache in (public, alias):
                with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), self.assertRaises(ValueError):
                    build_macos.obtain_runtime(lock, cache)

    def test_missing_developer_id_identity_refuses_before_staging_or_download(self):
        arguments = argparse.Namespace(adhoc=False, identity=None, team_id=None, output=Path("unused"), cache=Path("unused"))
        with mock.patch.object(build_macos.platform, "system", return_value="Darwin"), mock.patch.object(build_macos.platform, "machine", return_value="arm64"), mock.patch.object(build_macos, "obtain_runtime", side_effect=AssertionError("download forbidden")), self.assertRaisesRegex(ValueError, "--identity"):
            build_macos.build(arguments)

    def test_build_output_cannot_pollute_curated_desktop_sources(self):
        args = argparse.Namespace(adhoc=True, identity=None, team_id=None, output=build_macos.ROOT / "desktop/generated", cache=Path("/private/tmp/synthetic-cache"))
        with mock.patch.object(build_macos.platform, "system", return_value="Darwin"), mock.patch.object(build_macos.platform, "machine", return_value="arm64"), mock.patch.object(build_macos, "obtain_runtime", side_effect=AssertionError("download forbidden")), self.assertRaisesRegex(ValueError, "curated"):
            build_macos.build(args)

    def test_release_signing_refuses_wrong_kind_and_unusable_identity(self):
        with self.assertRaisesRegex(ValueError, "Developer ID Application"):
            build_macos.require_identity("Apple Development: Example (ABCDE12345)", "ABCDE12345")
        with mock.patch.object(build_macos, "run", return_value="0 valid identities found"), self.assertRaisesRegex(ValueError, "not currently usable"):
            build_macos.require_identity("Developer ID Application: Example (ABCDE12345)", "ABCDE12345")

    def test_dedicated_keychain_lookup_preserves_default_search_list(self):
        identity = "Developer ID Application: Example (ABCDE12345)"
        with tempfile.TemporaryDirectory() as temporary:
            keychain = Path(temporary).resolve() / "Dedicated signing.keychain-db"
            keychain.write_bytes(b"synthetic opaque encrypted keychain")
            keychain.chmod(0o400)
            for selected in (None, keychain):
                with mock.patch.object(build_macos, "run", return_value='1) fingerprint "' + identity + '"') as execute, mock.patch.object(Path, "read_bytes", side_effect=AssertionError("Never inspect encrypted Keychain contents")):
                    build_macos.require_identity(identity, "ABCDE12345", selected)
                command = execute.call_args.args[0]
                self.assertEqual(command[:5], ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"])
                self.assertEqual(command[5:], [] if selected is None else [str(keychain)])
                self.assertNotIn("list-keychains", command)
                self.assertNotIn("unlock-keychain", command)

    def test_keychain_alias_missing_file_and_writable_file_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            keychain = root / "signing.keychain-db"
            keychain.write_bytes(b"opaque encrypted bytes")
            keychain.chmod(0o600)
            alias = root / "alias.keychain-db"
            alias.symlink_to(keychain)
            with self.assertRaisesRegex(ValueError, "symlink"):
                build_macos.explicit_keychain(alias)
            with self.assertRaises(OSError):
                build_macos.explicit_keychain(root / "missing.keychain-db")
            keychain.chmod(0o622)
            with self.assertRaisesRegex(ValueError, "write"):
                build_macos.explicit_keychain(keychain)
            with self.assertRaisesRegex(ValueError, "canonical"):
                build_macos.explicit_keychain(Path("relative.keychain-db"))

    def test_explicit_signing_keychain_reaches_all_nested_and_bundle_signatures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            app = root / "Parallax.app"
            interpreter = app / "Contents/Resources/python/bin/python3.13"
            extension = app / "Contents/Resources/python/lib/example.so"
            entitlement = root / "entitlements.plist"
            entitlement.write_bytes(plistlib.dumps({}))
            keychain = root / "Dedicated signing.keychain-db"
            for selected in (None, keychain):
                with mock.patch.object(build_macos, "macho_files", return_value=[interpreter, extension]), mock.patch.object(build_macos, "run") as execute:
                    build_macos.sign_app(app, "Developer ID Application: Example (ABCDE12345)", False, entitlement, selected)
                commands = [call.args[0] for call in execute.call_args_list if "--sign" in call.args[0]]
                self.assertEqual(len(commands), 3)
                for command in commands:
                    self.assertEqual("--keychain" in command, selected is not None)
                    if selected is not None:
                        self.assertEqual(command[command.index("--keychain") + 1], str(keychain))
                    self.assertIn("--timestamp", command)
                    self.assertIn("runtime", command)

    def test_unsafe_signing_exceptions_are_refused_before_codesign(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entitlement = root / "entitlements.plist"
            for key in ("com.apple.security.get-task-allow", "com.apple.security.cs.disable-library-validation", "com.apple.security.cs.allow-unsigned-executable-memory"):
                entitlement.write_bytes(plistlib.dumps({key: True}))
                with mock.patch.object(build_macos, "run", side_effect=AssertionError("sign forbidden")), self.assertRaises(ValueError):
                    build_macos.sign_app(root, "-", True, entitlement)

    def test_local_interpreter_exception_cannot_leak_into_developer_id_signing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Parallax.app"
            interpreter = app / "Contents/Resources/python/bin/python3.13"
            extension = app / "Contents/Resources/python/lib/example.so"
            entitlement = root / "entitlements.plist"
            entitlement.write_bytes(plistlib.dumps({}))
            for adhoc, identity in [(True, "-"), (False, "Developer ID Application: Example (ABCDE12345)")]:
                with mock.patch.object(build_macos, "macho_files", return_value=[interpreter, extension]), mock.patch.object(build_macos, "run") as execute:
                    build_macos.sign_app(app, identity, adhoc, entitlement)
                signing = [call.args[0] for call in execute.call_args_list if "--sign" in call.args[0]]
                interpreter_command = next(command for command in signing if command[-1] == str(interpreter))
                self.assertEqual("runtime" in interpreter_command, not adhoc)
                self.assertTrue(all("runtime" in command for command in signing if command[-1] != str(interpreter)))
                self.assertTrue(all(("--timestamp=none" in command) == adhoc for command in signing))

    def test_adhoc_notarization_is_refused_before_keychain_or_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "build-receipt.json"
            receipt.write_text(json.dumps({"signing": "ad-hoc-local-review"}))
            args = argparse.Namespace(build_receipt=receipt, request_id="db4b94ee-9a83-4c26-aeaa-f474926a403e", identity="irrelevant", team_id="ABCDE12345", keychain_profile="existing-profile")
            with mock.patch.object(notarize_macos, "run", side_effect=AssertionError("upload forbidden")), self.assertRaisesRegex(ValueError, "ad hoc"):
                notarize_macos.notarize(args)

    def test_changed_bundle_inventory_is_refused_before_keychain_or_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / build_macos.APP_NAME
            app.mkdir()
            dmg = root / "candidate.dmg"
            dmg.write_bytes(b"original image")
            original = root / "bundle-inventory.json"
            original.write_text('{"files":[]}')
            receipt = root / "build-receipt.json"
            receipt.write_text(json.dumps({"signing": "developer-id", "team_id": "ABCDE12345", "published": False, "app": str(app), "dmg": str(dmg), "bundle_inventory_sha256": build_macos.sha256(original)}))
            # A substituted same-team app must not become authorized by replacing
            # its inventory beside an otherwise unchanged old build receipt.
            original.write_text('{"files":[{"path":"substituted-runtime"}]}')
            with mock.patch.object(notarize_macos, "require_identity", side_effect=AssertionError("Keychain forbidden")), mock.patch.object(notarize_macos, "run", side_effect=AssertionError("upload forbidden")), self.assertRaisesRegex(ValueError, "inventory"):
                notarize_macos.validate_inputs(receipt, "Developer ID Application: Example (ABCDE12345)", "ABCDE12345")

    def test_desktop_signing_private_keys_cannot_enter_source_artifacts(self):
        from release_files import release_files
        for name in ("desktop/macos/DeveloperID.p12", "desktop/signing.pfx", "desktop/signing.keychain-db", "desktop/signing.keychain"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                key = root / name
                key.parent.mkdir(parents=True)
                key.write_bytes(b"synthetic private signing key")
                with self.assertRaisesRegex(ValueError, "Private runtime or credential"):
                    release_files(root)

    def test_build_environment_drops_credentials_and_python_injection(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic", "PYTHONPATH": "/private", "PIP_INDEX_URL": "https://private.invalid", "DYLD_INSERT_LIBRARIES": "/private/library"}):
            env = build_macos.clean_build_env()
        for variable in ("OPENAI_API_KEY", "PYTHONPATH", "PIP_INDEX_URL", "DYLD_INSERT_LIBRARIES"):
            self.assertNotIn(variable, env)


if __name__ == "__main__":
    unittest.main()
