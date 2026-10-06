import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parallax.workspaces import MARKER, WorkspaceError, WorkspaceManager, fingerprint


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "source"
        self.workspace.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.write("main.txt", "original\n")
        self.write("other.txt", "other\n")
        self.write(".gitignore", "ignored/\n*.cache\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.manager = WorkspaceManager(self.workspace, self.root / "run")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", "-C", str(cwd or self.workspace), *args], capture_output=True,
                              check=check).stdout

    def write(self, name, text, root=None):
        path = (root or self.workspace) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def worker(self, name="one"):
        self.manager.prepare()
        return self.manager.create_worker(name)

    def merge(self, worker):
        collected = self.manager.collect(worker)
        self.assertTrue(collected["ok"], collected["error"])
        merged = self.manager.merge(worker)
        self.assertTrue(merged["ok"], merged["error"])
        return collected

    def test_dirty_snapshot_preserves_index_and_existing_user_content(self):
        self.write("main.txt", "staged\n")
        self.git("add", "main.txt")
        self.write("main.txt", "staged and unstaged\n")
        self.write("new.txt", "user untracked\n")
        self.write("ignored/secret.txt", "ignored\n")
        head = self.git("rev-parse", "HEAD")
        index = (self.workspace / ".git/index").read_bytes()
        worker = self.worker()
        self.assertEqual((worker / "main.txt").read_text(), "staged and unstaged\n")
        self.assertEqual((worker / "new.txt").read_text(), "user untracked\n")
        self.assertFalse((worker / "ignored/secret.txt").exists())
        self.assertTrue((worker / MARKER).is_file())
        self.write("main.txt", "staged and unstaged\nagent addition\n", worker)
        self.write("created.txt", "agent new\n", worker)
        collected = self.merge(worker)
        self.assertEqual(collected["changed_files"], ["created.txt", "main.txt"])
        self.assertNotIn(MARKER, collected["patch"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "staged and unstaged\n")
        result = self.manager.apply()
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "staged and unstaged\nagent addition\n")
        self.assertEqual((self.workspace / "new.txt").read_text(), "user untracked\n")
        self.assertEqual((self.workspace / "ignored/secret.txt").read_text(), "ignored\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual((self.workspace / ".git/index").read_bytes(), index)
        self.assertFalse((self.workspace / MARKER).exists())

    def test_parallel_workers_merge_and_dependency_worker_sees_integration(self):
        first = self.worker("first")
        second = self.manager.create_worker("second")
        self.write("main.txt", "first result\n", first)
        self.write("other.txt", "second result\n", second)
        self.merge(first)
        self.merge(second)
        dependent = self.manager.create_worker("dependent")
        self.assertEqual((dependent / "main.txt").read_text(), "first result\n")
        self.assertEqual((dependent / "other.txt").read_text(), "second result\n")
        self.assertTrue(self.manager.apply()["ok"])

    def test_conflicting_workers_do_not_change_integration(self):
        first = self.worker("first")
        second = self.manager.create_worker("second")
        self.write("main.txt", "first result\n", first)
        self.write("main.txt", "conflicting result\n", second)
        self.merge(first)
        self.assertTrue(self.manager.collect(second)["ok"])
        result = self.manager.merge(second)
        self.assertFalse(result["ok"])
        self.assertIn("conflict", result["error"])
        self.assertEqual((self.manager.integration_path / "main.txt").read_text(), "first result\n")
        self.assertEqual((self.workspace / "main.txt").read_text(), "original\n")

    def test_rename_delete_binary_and_executable_changes(self):
        worker = self.worker()
        (worker / "main.txt").rename(worker / "renamed.txt")
        (worker / "other.txt").unlink()
        (worker / "binary.dat").write_bytes(b"\x00\xff\x01")
        executable = self.write("launch.sh", "#!/bin/sh\ntrue\n", worker)
        executable.chmod(0o755)
        collected = self.merge(worker)
        self.assertEqual(collected["changed_files"], ["binary.dat", "launch.sh", "main.txt", "other.txt", "renamed.txt"])
        result = self.manager.apply()
        self.assertTrue(result["ok"], result["error"])
        self.assertFalse((self.workspace / "main.txt").exists())
        self.assertFalse((self.workspace / "other.txt").exists())
        self.assertEqual((self.workspace / "renamed.txt").read_text(), "original\n")
        self.assertEqual((self.workspace / "binary.dat").read_bytes(), b"\x00\xff\x01")
        self.assertTrue((self.workspace / "launch.sh").stat().st_mode & stat.S_IXUSR)

    def test_touched_user_edit_blocks_apply_even_same_size_and_timestamp(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        source = self.workspace / "main.txt"
        info = source.stat()
        source.write_text("useredit\n")
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = self.manager.apply()
        self.assertFalse(result["ok"])
        self.assertIn("main.txt", result["error"])
        self.assertEqual(source.read_text(), "useredit\n")

    def test_unrelated_user_edit_requires_fresh_candidate_and_revalidation(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        self.write("other.txt", "new unrelated user edit\n")
        self.write("later.txt", "new user file\n")
        initial = self.manager.check_destination()
        self.assertTrue(initial["ok"])
        self.assertTrue(initial["revalidate"])
        self.assertFalse(self.manager.apply()["ok"])
        fresh = self.manager.refresh_candidate()
        self.assertTrue(fresh["ok"], fresh["error"])
        self.assertTrue(fresh["revalidate"])
        self.assertEqual((self.manager.integration_path / "other.txt").read_text(), "new unrelated user edit\n")
        self.assertEqual((self.manager.integration_path / "later.txt").read_text(), "new user file\n")
        self.assertNotIn("later.txt", self.manager.diff())
        self.assertFalse(self.manager.check_destination()["revalidate"])
        result = self.manager.apply()
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["changed_files"], ["main.txt"])
        self.assertEqual((self.workspace / "other.txt").read_text(), "new unrelated user edit\n")

    def test_original_index_updates_are_preserved_after_revalidation(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        self.write("other.txt", "user staged later\n")
        self.git("add", "other.txt")
        index = (self.workspace / ".git/index").read_bytes()
        self.assertTrue(self.manager.refresh_candidate()["ok"])
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual((self.workspace / ".git/index").read_bytes(), index)

    def test_tracked_ignored_files_are_tracked(self):
        self.write("ignored/tracked.txt", "tracked original\n")
        self.git("add", "-f", "ignored/tracked.txt")
        self.git("commit", "-qm", "track ignored file")
        worker = self.worker()
        self.write("ignored/tracked.txt", "tracked agent\n", worker)
        collected = self.merge(worker)
        self.assertEqual(collected["changed_files"], ["ignored/tracked.txt"])
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual((self.workspace / "ignored/tracked.txt").read_text(), "tracked agent\n")

    def test_snapshot_preserves_raw_bytes_despite_git_attributes(self):
        self.write(".gitattributes", "*.txt text eol=crlf\n")
        source = self.workspace / "main.txt"
        source.write_bytes(b"raw\r\nbytes\r\n")
        worker = self.worker()
        self.assertEqual((worker / "main.txt").read_bytes(), b"raw\r\nbytes\r\n")
        (worker / "main.txt").write_bytes(b"changed\r\nbytes\r\n")
        self.merge(worker)
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual(source.read_bytes(), b"changed\r\nbytes\r\n")

    def test_worker_changes_after_collection_need_another_review(self):
        worker = self.worker()
        self.write("main.txt", "reviewed change\n", worker)
        self.assertTrue(self.manager.collect(worker)["ok"])
        self.write("main.txt", "unreviewed change\n", worker)
        result = self.manager.merge(worker)
        self.assertFalse(result["ok"])
        self.assertIn("after collection", result["error"])

    def test_external_symlinks_and_git_metadata_changes_are_rejected(self):
        worker = self.worker()
        (worker / "leak").symlink_to(self.root / "outside")
        result = self.manager.collect(worker)
        self.assertFalse(result["ok"])
        self.assertIn("External symlinks", result["error"])
        (worker / "leak").unlink()
        (worker / ".git").write_text("gitdir: /other\n")
        result = self.manager.collect(worker)
        self.assertFalse(result["ok"])
        self.assertIn("Git metadata", result["error"])

    def test_internal_symlinks_can_be_integrated(self):
        worker = self.worker()
        (worker / "link").symlink_to("main.txt")
        self.merge(worker)
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual(os.readlink(self.workspace / "link"), "main.txt")

    def test_run_reload_preserves_worker_and_integration(self):
        worker = self.worker()
        self.write("main.txt", "resumable result\n", worker)
        self.merge(worker)
        restored = WorkspaceManager(self.workspace, self.root / "run")
        self.assertTrue(restored.load())
        self.assertEqual(restored.create_worker("one"), worker)
        self.assertEqual(restored.diff(), self.manager.diff())
        self.assertTrue(restored.apply()["ok"])

    def test_apply_failure_rolls_back_previously_written_files(self):
        worker = self.worker()
        self.write("main.txt", "first agent file\n", worker)
        self.write("other.txt", "second agent file\n", worker)
        self.merge(worker)
        original = self.manager._write_file
        def fail_second(root, name, *args):
            if name == "other.txt":
                raise OSError("injected write failure")
            return original(root, name, *args)
        with patch.object(self.manager, "_write_file", side_effect=fail_second):
            result = self.manager.apply()
        self.assertFalse(result["ok"])
        self.assertEqual(result["changed_files"], [])
        self.assertEqual((self.workspace / "main.txt").read_text(), "original\n")
        self.assertEqual((self.workspace / "other.txt").read_text(), "other\n")

    def test_source_branch_change_blocks_integration(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        self.git("checkout", "-qb", "elsewhere")
        result = self.manager.apply()
        self.assertFalse(result["ok"])
        self.assertIn("branch", result["error"])

    def test_existing_submodules_and_non_git_workspaces_fail_clearly(self):
        head = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "160000," + head + ",nested")
        with self.assertRaisesRegex(WorkspaceError, "submodules"):
            self.manager.prepare()
        empty = self.root / "not-git"
        empty.mkdir()
        with self.assertRaisesRegex(WorkspaceError, "requires a Git repository"):
            WorkspaceManager(empty, self.root / "other-run").prepare()

    def test_no_source_hooks_run_during_snapshot_or_checkout(self):
        hooks = self.workspace / ".git/hooks"
        hook = hooks / "post-checkout"
        hook.write_text("#!/bin/sh\nprintf bad > '" + str(self.root / "hook-ran") + "'\n")
        hook.chmod(0o755)
        self.worker()
        self.assertFalse((self.root / "hook-ran").exists())

    def test_snapshot_does_not_execute_clean_or_smudge_filters(self):
        self.write(".gitattributes", "*.txt filter=private-filter\n")
        command = "printf ran > '" + str(self.root / "filter-ran") + "'; cat"
        self.git("config", "filter.private-filter.clean", command)
        self.git("config", "filter.private-filter.smudge", command)
        worker = self.worker()
        self.assertEqual((worker / "main.txt").read_text(), "original\n")
        self.assertFalse((self.root / "filter-ran").exists())

    def test_permissions_are_preserved_for_existing_private_file(self):
        (self.workspace / "main.txt").chmod(0o600)
        worker = self.worker()
        self.write("main.txt", "private update\n", worker)
        self.merge(worker)
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual(stat.S_IMODE((self.workspace / "main.txt").stat().st_mode), 0o600)

    def test_unreviewed_integration_changes_cannot_be_applied(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        self.write("main.txt", "unreviewed result\n", self.manager.integration_path)
        result = self.manager.apply()
        self.assertFalse(result["ok"])
        self.assertIn("outside", result["error"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "original\n")

    def test_partial_integration_crash_is_rolled_back_on_reload(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.write("other.txt", "another agent result\n", worker)
        self.merge(worker)
        original = self.manager._write_file
        def crash_after_write(root, name, *args):
            original(root, name, *args)
            raise KeyboardInterrupt()
        with patch.object(self.manager, "_write_file", side_effect=crash_after_write):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply()
        self.assertEqual((self.workspace / "main.txt").read_text(), "agent result\n")
        restored = WorkspaceManager(self.workspace, self.root / "run")
        self.assertTrue(restored.load())
        self.assertFalse(restored.prepare()["applied"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "original\n")
        self.assertEqual((self.workspace / "other.txt").read_text(), "other\n")

    def test_complete_integration_crash_is_recognized_without_replay(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        original = self.manager._save
        def crash_before_success_save():
            if self.manager._metadata.get("applied"):
                raise KeyboardInterrupt()
            original()
        with patch.object(self.manager, "_save", side_effect=crash_before_success_save):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply()
        restored = WorkspaceManager(self.workspace, self.root / "run")
        self.assertTrue(restored.load())
        self.assertTrue(restored.prepare()["applied"])
        self.assertTrue(restored.apply()["ok"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "agent result\n")

    def test_crash_recovery_preserves_external_edits_and_reports_conflict(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.write("other.txt", "another agent result\n", worker)
        self.merge(worker)
        original = self.manager._write_file
        def crash_after_write(root, name, *args):
            original(root, name, *args)
            raise KeyboardInterrupt()
        with patch.object(self.manager, "_write_file", side_effect=crash_after_write):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.apply()
        self.write("main.txt", "user edit after crash\n")
        restored = WorkspaceManager(self.workspace, self.root / "run")
        with self.assertRaisesRegex(WorkspaceError, "external edits"):
            restored.load()
        self.assertEqual((self.workspace / "main.txt").read_text(), "user edit after crash\n")

    def test_apply_after_success_is_idempotent(self):
        worker = self.worker()
        self.write("main.txt", "agent result\n", worker)
        self.merge(worker)
        self.assertTrue(self.manager.apply()["ok"])
        self.write("main.txt", "user later edit\n")
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual((self.workspace / "main.txt").read_text(), "user later edit\n")

    def test_arbitrary_file_names_are_preserved(self):
        worker = self.worker()
        name = "space and \"quote\"\nand Unicode é.txt"
        self.write(name, "arbitrary file name\n", worker)
        collected = self.merge(worker)
        self.assertEqual(collected["changed_files"], [name])
        self.assertTrue(self.manager.apply()["ok"])
        self.assertEqual((self.workspace / name).read_text(), "arbitrary file name\n")

    def test_unborn_repository_preserves_unborn_head_and_index(self):
        empty = self.root / "unborn"
        empty.mkdir()
        self.git("init", "-q", cwd=empty)
        self.write("new.txt", "initial content\n", empty)
        manager = WorkspaceManager(empty, self.root / "unborn-run")
        manager.prepare()
        worker = manager.create_worker("first")
        self.write("new.txt", "agent content\n", worker)
        self.assertTrue(manager.collect(worker)["ok"])
        self.assertTrue(manager.merge(worker)["ok"])
        self.assertTrue(manager.apply()["ok"])
        self.assertFalse((empty / ".git/index").exists())
        self.assertEqual(self.git("rev-parse", "--verify", "HEAD", cwd=empty, check=False), b"")

    def test_fingerprint_detects_actual_worker_changes_and_excludes_marker_cache(self):
        worker = self.worker()
        before = self.manager.fingerprint(worker)
        self.assertEqual(before, self.manager.fingerprint(worker))
        self.write("ignored/cache.txt", "runtime cache\n", worker)
        self.assertEqual(before, self.manager.fingerprint(worker))
        self.write("main.txt", "changed content\n", worker)
        self.assertNotEqual(before, self.manager.fingerprint(worker))
        self.assertNotEqual(fingerprint(worker), fingerprint(self.workspace))

    def test_fingerprint_handles_non_git_review_copy(self):
        directory = self.root / "review-copy"
        directory.mkdir()
        self.write("main.txt", "review content\n", directory)
        before = fingerprint(directory)
        self.write(MARKER, "runtime marker\n", directory)
        self.assertEqual(before, fingerprint(directory))
        self.write("main.txt", "changed review content\n", directory)
        self.assertNotEqual(before, fingerprint(directory))


if __name__ == "__main__":
    unittest.main()
