"""Private Git workspaces and checked integration into a user's working tree.

The user's index is never used as scratch space.  Snapshot blobs contain the
actual working-file bytes, without clean/smudge filters, and worker commits stay
under private refs.  The engine, rather than this module, owns review and test
gates; it must run those gates again after ``refresh_candidate`` succeeds.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


MARKER = ".parallax-owned"
MARKER_CONTENT = b"parallax-private-worktree-v1\n"
MAX_FILES = 100_000
MAX_FILE_BYTES = 100 * 1024 * 1024


class WorkspaceError(RuntimeError):
    """A workspace cannot safely be prepared or integrated."""


def fingerprint(path: Path) -> str:
    """Hash actual consultation/check inputs, including non-Git review copies."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise WorkspaceError("Fingerprint directory does not exist")
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", *args],
                              capture_output=True, env=env, timeout=30, check=False)
    probe = git("rev-parse", "--show-toplevel")
    details: dict[str, Any] = {}
    if probe.returncode == 0 and Path(os.fsdecode(probe.stdout.strip())).resolve() == root:
        listing = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if listing.returncode:
            raise WorkspaceError("Could not inspect workspace files")
        names = {os.fsdecode(item) for item in listing.stdout.split(b"\0") if item}
        head = git("rev-parse", "--verify", "HEAD")
        if head.returncode == 0:
            tree = git("ls-tree", "-r", "--name-only", "-z", "HEAD")
            names.update(os.fsdecode(item) for item in tree.stdout.split(b"\0") if item)
        details["head"] = head.stdout.decode().strip() if head.returncode == 0 else None
        details["index"] = hashlib.sha256(git("ls-files", "--stage", "-z").stdout).hexdigest()
    else:
        names = set()
        for parent, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name.casefold() != ".git"]
            for name in list(dirs):
                child = Path(parent) / name
                if child.is_symlink():
                    names.add(str(child.relative_to(root)))
                    dirs.remove(name)
            names.update(str((Path(parent) / name).relative_to(root)) for name in files if name.casefold() != ".git")
    names.discard(MARKER)
    if len(names) > MAX_FILES:
        raise WorkspaceError("Workspace exceeds the 100,000-file snapshot limit")
    files = {}
    for name in sorted(names):
        value = WorkspaceManager._fingerprint(root, name)
        if value is not None:
            files[name] = value
    details["files"] = files
    return hashlib.sha256(json.dumps(details, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class WorkspaceManager:
    def __init__(self, workspace: Path, run_dir: Path):
        self.workspace = Path(workspace).expanduser().resolve()
        self.run_dir = Path(run_dir).expanduser().resolve()
        self._metadata: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._ref_prefix = "refs/parallax/" + hashlib.sha256(os.fsencode(self.run_dir)).hexdigest()[:24]
        if self.run_dir.is_relative_to(self.workspace):
            raise WorkspaceError("Private run data must be outside the source workspace")

    @property
    def integration_path(self) -> Path:
        if not self._metadata:
            raise WorkspaceError("Workspace has not been prepared")
        return Path(self._metadata["integration_path"])

    def _git(self, directory: Path, *args: str, input_bytes: bytes | None = None,
             index: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        for name in list(env):
            if name.startswith("GIT_"):
                env.pop(name)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        env.update({"GIT_AUTHOR_NAME": "Parallax", "GIT_AUTHOR_EMAIL": "parallax@localhost",
                    "GIT_COMMITTER_NAME": "Parallax", "GIT_COMMITTER_EMAIL": "parallax@localhost"})
        command = ["git", "-C", str(directory), "-c", "core.hooksPath=" + os.devnull,
                   "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false",
                   "-c", "commit.gpgSign=false", "-c", "merge.renormalize=false", *args]
        result = subprocess.run(command, input=input_bytes, capture_output=True, env=env,
                                timeout=120, check=False)
        if check and result.returncode:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise WorkspaceError(detail or "Git command failed: " + " ".join(args[:2]))
        return result

    def _oid(self, directory: Path, revision: str) -> str | None:
        result = self._git(directory, "rev-parse", "--verify", revision, check=False)
        return result.stdout.decode().strip() if result.returncode == 0 else None

    @staticmethod
    def _safe_name(name: str) -> None:
        parts = PurePosixPath(name).parts
        if not name or name.startswith("/") or "\x00" in name or ".." in parts:
            raise WorkspaceError("Unsafe workspace path: " + repr(name))
        if any(part.casefold() == ".git" for part in parts):
            raise WorkspaceError("Changes to Git metadata are not allowed")

    @staticmethod
    def _safe_parents(root: Path, name: str) -> None:
        WorkspaceManager._safe_name(name)
        parent = root
        for part in PurePosixPath(name).parts[:-1]:
            parent /= part
            if parent.is_symlink():
                raise WorkspaceError("A workspace path traverses a symlink: " + name)

    @staticmethod
    def _fingerprint(root: Path, name: str) -> dict | None:
        WorkspaceManager._safe_parents(root, name)
        path = root / name
        try:
            info = path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        permissions = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            try:
                resolved = path.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise WorkspaceError("Invalid workspace symlink: " + name) from exc
            if not resolved.is_relative_to(root):
                raise WorkspaceError("External symlinks are unsupported: " + name)
            if any(part.casefold() == ".git" for part in resolved.relative_to(root).parts):
                raise WorkspaceError("Symlinks into Git metadata are not allowed: " + name)
            # Symlink permission bits differ between macOS/Linux and do not
            # control access to the target.  Normalize them for durable guards.
            return {"mode": "120000", "permissions": 0o777,
                    "sha256": hashlib.sha256(os.fsencode(target)).hexdigest(), "target": target}
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceError("Only regular files and internal symlinks are supported: " + name)
        if info.st_size > MAX_FILE_BYTES:
            raise WorkspaceError("Workspace file exceeds the 100 MiB snapshot limit: " + name)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise WorkspaceError("Workspace changed while reading: " + name)
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                ended = os.fstat(stream.fileno())
            current = path.lstat()
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            raise WorkspaceError("Workspace changed while reading: " + name) from exc
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_mode)
        if identity(opened) != identity(ended) or identity(ended) != identity(current):
            raise WorkspaceError("Workspace changed while reading: " + name)
        return {"mode": "100755" if info.st_mode & stat.S_IXUSR else "100644",
                "permissions": permissions, "sha256": digest.hexdigest()}

    @staticmethod
    def _content(root: Path, name: str, expected: dict) -> bytes:
        """Read a previously inspected file without following a replaced symlink."""
        WorkspaceManager._safe_parents(root, name)
        path = root / name
        if expected["mode"] == "120000":
            content = os.fsencode(os.readlink(path))
        else:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                    raise WorkspaceError("Workspace changed while reading: " + name)
                content = stream.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise WorkspaceError("Workspace file exceeds the 100 MiB snapshot limit: " + name)
        if hashlib.sha256(content).hexdigest() != expected["sha256"]:
            raise WorkspaceError("Workspace changed while reading: " + name)
        return content

    def _tree(self, commit: str) -> dict[str, tuple[str, str]]:
        result = self._git(self.workspace, "ls-tree", "-r", "-z", "--full-tree", commit)
        entries: dict[str, tuple[str, str]] = {}
        for item in result.stdout.split(b"\0"):
            if not item:
                continue
            header, raw_name = item.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            name = os.fsdecode(raw_name)
            self._safe_name(name)
            if mode == "160000" or kind != "blob":
                raise WorkspaceError("Git submodules are unsupported in autonomous workspaces")
            if name == MARKER:
                raise WorkspaceError(MARKER + " is reserved for private Parallax workspaces")
            entries[name] = (mode, oid)
        return entries

    def _scan(self, root: Path, baseline: str | None = None) -> dict[str, dict]:
        staged = self._git(root, "ls-files", "--stage", "-z").stdout
        for item in staged.split(b"\0"):
            if not item:
                continue
            fields = item.split(b"\t", 1)[0].split()
            if fields[0] == b"160000":
                raise WorkspaceError("Git submodules are unsupported in autonomous workspaces")
            if fields[-1] != b"0":
                raise WorkspaceError("Resolve existing Git merge conflicts before starting a team")
        result = self._git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        names = {os.fsdecode(item) for item in result.stdout.split(b"\0") if item}
        if baseline:
            names.update(self._tree(baseline))
        names.discard(MARKER)
        if len(names) > MAX_FILES:
            raise WorkspaceError("Workspace exceeds the 100,000-file snapshot limit")
        files: dict[str, dict] = {}
        for name in sorted(names):
            fingerprint = self._fingerprint(root, name)
            if fingerprint is not None:
                files[name] = fingerprint
        return files

    def _source_state(self) -> dict:
        head = self._oid(self.workspace, "HEAD")
        branch = self._git(self.workspace, "symbolic-ref", "-q", "HEAD", check=False)
        index = self._git(self.workspace, "ls-files", "--stage", "-z").stdout
        return {"head": head, "branch": branch.stdout.decode().strip() or None,
                "index": hashlib.sha256(index).hexdigest(), "files": self._scan(self.workspace, head)}

    def _commit(self, tree: str, parents: list[str], label: str) -> str:
        command = ["commit-tree", tree]
        for parent in parents:
            command.extend(["-p", parent])
        result = self._git(self.workspace, *command, input_bytes=("Parallax " + label + "\n").encode())
        commit = result.stdout.decode().strip()
        self._git(self.workspace, "update-ref", self._ref_prefix + "/" + label, commit)
        return commit

    def _snapshot(self, root: Path, files: dict[str, dict], parent: str | None, label: str) -> str:
        directory = self.run_dir / "indices"
        directory.mkdir(parents=True, exist_ok=True)
        index = directory / (uuid.uuid4().hex + ".index")
        try:
            self._git(root, "read-tree", "--empty", index=index)
            records = bytearray()
            for name, expected in files.items():
                content = self._content(root, name, expected)
                oid = self._git(root, "hash-object", "-w", "--no-filters", "--stdin",
                                input_bytes=content).stdout.strip()
                records.extend(expected["mode"].encode() + b" " + oid + b"\t" + os.fsencode(name) + b"\0")
            if records:
                self._git(root, "update-index", "-z", "--index-info", input_bytes=bytes(records), index=index)
            tree = self._git(root, "write-tree", index=index).stdout.decode().strip()
            if parent and self._oid(self.workspace, parent + "^{tree}") == tree:
                return parent
            return self._commit(tree, [parent] if parent else [], label)
        finally:
            index.unlink(missing_ok=True)
            Path(str(index) + ".lock").unlink(missing_ok=True)

    def _save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        destination = self.run_dir / "workspace.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._metadata, indent=2, sort_keys=True), encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)

    def load(self) -> bool:
        with self._lock:
            filename = self.run_dir / "workspace.json"
            if not filename.is_file():
                return False
            saved = json.loads(filename.read_text(encoding="utf-8"))
            if saved.get("schema_version") != 1 or saved.get("workspace") != str(self.workspace):
                raise WorkspaceError("Saved run workspace metadata is incompatible")
            if not Path(saved["integration_path"]).resolve().is_relative_to(self.run_dir):
                raise WorkspaceError("Saved integration path escapes the private run directory")
            self._metadata = saved
            self._owned(self.integration_path, saved["integration_gitfile"])
            for worker in saved["workers"].values():
                path = Path(worker["path"])
                if not path.resolve().is_relative_to(self.run_dir / "workers"):
                    raise WorkspaceError("Saved worker path escapes the private run directory")
                self._owned(path, worker["gitfile"])
            if saved.get("apply_transaction", {}).get("state") == "applying":
                self._recover_apply()
            return True

    def _owned(self, path: Path, gitfile: str) -> None:
        if not path.resolve().is_relative_to(self.run_dir) or path.is_symlink():
            raise WorkspaceError("Worker is outside the private run directory")
        marker = path / MARKER
        git = path / ".git"
        if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != MARKER_CONTENT:
            raise WorkspaceError("Private worktree ownership marker was changed")
        if git.is_symlink() or not git.is_file() or hashlib.sha256(git.read_bytes()).hexdigest() != gitfile:
            raise WorkspaceError("Private worktree Git metadata was changed")

    def _materialize(self, path: Path, commit: str, previous: str | None = None) -> None:
        entries = self._tree(commit)
        old = self._tree(previous) if previous else {}
        for name in sorted(old.keys() - entries.keys(), key=lambda item: (-len(PurePosixPath(item).parts), item)):
            self._safe_parents(path, name)
            target = path / name
            if target.is_dir() and not target.is_symlink():
                raise WorkspaceError("Unexpected directory in private worktree: " + name)
            target.unlink(missing_ok=True)
            parent = target.parent
            while parent != path:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        for name, (mode, oid) in entries.items():
            self._safe_parents(path, name)
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            content = self._git(self.workspace, "cat-file", "blob", oid).stdout
            if target.is_dir() and not target.is_symlink():
                try:
                    target.rmdir()
                except OSError as exc:
                    raise WorkspaceError("Cannot replace nonempty private directory: " + name) from exc
            if target.is_symlink() or target.exists():
                target.unlink()
            if mode == "120000":
                link = os.fsdecode(content)
                try:
                    resolved = (target.parent / link).resolve(strict=False)
                except (OSError, RuntimeError) as exc:
                    raise WorkspaceError("Invalid workspace symlink: " + name) from exc
                if not resolved.is_relative_to(path):
                    raise WorkspaceError("External symlinks are unsupported: " + name)
                target.symlink_to(link)
            else:
                target.write_bytes(content)
                target.chmod(0o755 if mode == "100755" else 0o644)
        self._git(path, "read-tree", commit)
        self._git(path, "update-ref", "HEAD", commit)

    def _worktree(self, path: Path, commit: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git(self.workspace, "worktree", "add", "--detach", "--no-checkout", str(path), commit)
        try:
            self._materialize(path, commit)
            (path / MARKER).write_bytes(MARKER_CONTENT)
            return hashlib.sha256((path / ".git").read_bytes()).hexdigest()
        except Exception:
            self._git(self.workspace, "worktree", "remove", "--force", str(path), check=False)
            raise

    def prepare(self) -> dict:
        with self._lock:
            if self._metadata or self.load():
                return dict(self._metadata)
            if not self.workspace.is_dir():
                raise WorkspaceError("Workspace directory does not exist")
            if self.run_dir.is_relative_to(self.workspace):
                raise WorkspaceError("Private run data must be outside the source workspace")
            root = self._git(self.workspace, "rev-parse", "--show-toplevel", check=False)
            if root.returncode:
                raise WorkspaceError("Autonomous editing requires a Git repository")
            if Path(os.fsdecode(root.stdout.strip())).resolve() != self.workspace:
                raise WorkspaceError("Select the Git repository root as the workspace")
            if (self.workspace / MARKER).exists() or (self.workspace / MARKER).is_symlink():
                raise WorkspaceError(MARKER + " is reserved for private Parallax workspaces")
            self.run_dir.mkdir(parents=True, exist_ok=True)
            state = self._source_state()
            snapshot = self._snapshot(self.workspace, state["files"], state["head"], "snapshot")
            if self._source_state() != state:
                raise WorkspaceError("Workspace changed while preparing; retry with a stable working tree")
            integration = self.run_dir / "integration"
            gitfile = self._worktree(integration, snapshot)
            self._metadata = {"schema_version": 1, "workspace": str(self.workspace),
                              "snapshot_commit": snapshot, "patch_base_commit": snapshot,
                              "integration_commit": snapshot, "integration_path": str(integration),
                              "integration_gitfile": gitfile, "source_state": state,
                              "integration_files": self._scan(integration, snapshot), "workers": {},
                              "applied": False, "applied_changed_files": []}
            self._save()
            return dict(self._metadata)

    def create_worker(self, task_id: str, base: str | None = None) -> Path:
        with self._lock:
            # Public task IDs allow 64 characters; engine attempt suffixes need
            # additional room while remaining single safe path components.
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}", task_id):
                raise WorkspaceError("Invalid worker task ID")
            if not self._metadata:
                self.prepare()
            existing = self._metadata["workers"].get(task_id)
            if existing:
                if base and base != existing["base"]:
                    raise WorkspaceError("An existing worker cannot change its baseline")
                path = Path(existing["path"])
                self._owned(path, existing["gitfile"])
                return path
            commit = base or self._metadata["integration_commit"]
            valid = {self._metadata["snapshot_commit"], self._metadata["patch_base_commit"],
                     self._metadata["integration_commit"]}
            valid.update(worker.get("commit_id") for worker in self._metadata["workers"].values())
            if commit not in valid:
                raise WorkspaceError("Worker baseline is not a commit owned by this run")
            path = self.run_dir / "workers" / task_id
            gitfile = self._worktree(path, commit)
            self._metadata["workers"][task_id] = {"path": str(path), "base": commit, "gitfile": gitfile}
            self._save()
            return path

    def _worker_record(self, path: Path) -> tuple[str, dict]:
        resolved = Path(path).resolve()
        for identifier, worker in self._metadata.get("workers", {}).items():
            if resolved == Path(worker["path"]):
                self._owned(resolved, worker["gitfile"])
                return identifier, worker
        raise WorkspaceError("Worker does not belong to this run")

    def _diff_bytes(self, before: str, after: str) -> bytes:
        return self._git(self.workspace, "diff", "--binary", "--full-index", "--no-ext-diff",
                         "--no-textconv", "--no-renames", before, after, "--").stdout

    def _changed(self, before: str, after: str) -> list[str]:
        result = self._git(self.workspace, "diff", "--name-only", "--no-renames", "-z", before, after, "--")
        names = [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]
        for name in names:
            self._safe_name(name)
        return sorted(names)

    def collect(self, worker: Path) -> dict:
        with self._lock:
            try:
                identifier, record = self._worker_record(worker)
                files = self._scan(Path(worker), record["base"])
                commit = self._snapshot(Path(worker), files, record["base"], "workers/" + identifier)
                if self._scan(Path(worker), record["base"]) != files:
                    raise WorkspaceError("Worker changed during collection; stop it before collecting")
                record.update({"commit_id": commit, "collected_files": files})
                self._save()
                patch = self._diff_bytes(record["base"], commit)
                return {"ok": True, "changed_files": self._changed(record["base"], commit),
                        "patch": patch.decode("utf-8", "replace"), "commit_id": commit, "error": None}
            except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                return {"ok": False, "changed_files": [], "patch": "", "commit_id": "", "error": str(exc)}

    def _integration_clean(self) -> None:
        self._owned(self.integration_path, self._metadata["integration_gitfile"])
        if self._scan(self.integration_path, self._metadata["integration_commit"]) != self._metadata["integration_files"]:
            raise WorkspaceError("Integration files changed outside the collected task results; revalidate them")

    def merge(self, worker: Path) -> dict:
        with self._lock:
            candidate: Path | None = None
            try:
                _, record = self._worker_record(worker)
                if not record.get("commit_id"):
                    raise WorkspaceError("Collect and review the worker before merging")
                if self._scan(Path(worker), record["base"]) != record["collected_files"]:
                    raise WorkspaceError("Worker changed after collection; collect and review it again")
                self._integration_clean()
                old = self._metadata["integration_commit"]
                # A repository may configure arbitrary external merge drivers.
                # Runtime merges use Git's built-ins and fail closed for custom drivers.
                drivers = self._git(self.workspace, "config", "--name-only", "--get-regexp",
                                    r"^merge\..*\.driver$", check=False).stdout.decode().splitlines()
                overrides = [argument for name in drivers for argument in ("-c", name + "=false")]
                result = self._git(self.workspace, *overrides, "merge-tree", "--write-tree", old,
                                   record["commit_id"], check=False)
                if result.returncode:
                    detail = result.stdout.decode("utf-8", "replace").split("\n", 1)[-1].strip()
                    raise WorkspaceError("Worker changes conflict with the integration candidate" + (": " + detail[:1000] if detail else ""))
                tree = result.stdout.decode().splitlines()[0]
                if tree == self._oid(self.workspace, old + "^{tree}"):
                    return {"ok": True, "changed_files": [], "error": None}
                commit = self._commit(tree, [old, record["commit_id"]], "integration")
                candidate = self.run_dir / ("integration-" + uuid.uuid4().hex[:12])
                gitfile = self._worktree(candidate, commit)
                self._metadata.update({"integration_commit": commit,
                                       "integration_path": str(candidate), "integration_gitfile": gitfile,
                                       "integration_files": self._scan(candidate, commit)})
                self._save()
                return {"ok": True, "changed_files": self._changed(old, commit), "error": None}
            except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                if candidate is not None:
                    self._git(self.workspace, "worktree", "remove", "--force", str(candidate), check=False)
                return {"ok": False, "changed_files": [], "error": str(exc)}

    def diff(self) -> str:
        with self._lock:
            return self._diff_bytes(self._metadata["patch_base_commit"],
                                    self._metadata["integration_commit"]).decode("utf-8", "replace")

    def fingerprint(self, path: Path) -> str:
        """Hash a registered worktree's actual bytes, modes and Git state."""
        with self._lock:
            root = Path(path).resolve()
            if root == self.workspace:
                details = self._source_state()
            else:
                if root == self.integration_path:
                    self._owned(root, self._metadata["integration_gitfile"])
                    base = self._metadata["integration_commit"]
                else:
                    _, worker = self._worker_record(root)
                    base = worker["base"]
                details = {"head": self._oid(root, "HEAD"), "files": self._scan(root, base),
                           "index": hashlib.sha256(self._git(root, "ls-files", "--stage", "-z").stdout).hexdigest()}
            return hashlib.sha256(json.dumps(details, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def check_destination(self) -> dict:
        with self._lock:
            try:
                self._integration_clean()
                current = self._source_state()
                baseline = self._metadata["source_state"]
                if current["head"] != baseline["head"] or current["branch"] != baseline["branch"]:
                    raise WorkspaceError("Source branch or HEAD changed; integration needs attention")
                changed = self._changed(self._metadata["patch_base_commit"], self._metadata["integration_commit"])
                for name in changed:
                    if current["files"].get(name) != baseline["files"].get(name):
                        raise WorkspaceError("Source file changed during the run: " + name)
                    target = self.workspace / name
                    if target.is_dir() and not target.is_symlink():
                        raise WorkspaceError("Replacing source directories requires manual integration: " + name)
                return {"ok": True, "revalidate": current != baseline, "changed_files": changed, "error": None}
            except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                return {"ok": False, "revalidate": False, "changed_files": [], "error": str(exc)}

    def refresh_candidate(self) -> dict:
        with self._lock:
            destination = self.check_destination()
            if not destination["ok"]:
                return destination
            if not destination["revalidate"]:
                return {"ok": True, "revalidate": False, "error": None}
            candidate: Path | None = None
            try:
                state = self._source_state()
                old_tip = self._metadata["integration_commit"]
                patch = self._diff_bytes(self._metadata["patch_base_commit"], old_tip)
                base = self._snapshot(self.workspace, state["files"], state["head"], "latest/" + uuid.uuid4().hex)
                if self._source_state() != state:
                    raise WorkspaceError("Source changed while refreshing the candidate; retry verification")
                candidate = self.run_dir / ("integration-" + uuid.uuid4().hex[:12])
                gitfile = self._worktree(candidate, base)
                if patch:
                    self._git(candidate, "apply", "--check", "--binary", "--whitespace=nowarn", "-", input_bytes=patch)
                    self._git(candidate, "apply", "--binary", "--whitespace=nowarn", "-", input_bytes=patch)
                files = self._scan(candidate, base)
                commit = self._snapshot(candidate, files, base, "integration")
                self._git(candidate, "read-tree", commit)
                self._git(candidate, "update-ref", "HEAD", commit)
                if self._source_state() != state:
                    raise WorkspaceError("Source changed while refreshing the candidate; retry verification")
                self._metadata.update({"patch_base_commit": base, "integration_commit": commit,
                                       "integration_path": str(candidate), "integration_gitfile": gitfile,
                                       "integration_files": files, "source_state": state})
                self._save()
                return {"ok": True, "revalidate": True, "changed_files": destination["changed_files"], "error": None}
            except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                if candidate is not None:
                    self._git(self.workspace, "worktree", "remove", "--force", str(candidate), check=False)
                return {"ok": False, "revalidate": True, "changed_files": [], "error": str(exc)}

    @staticmethod
    def _read_backup(root: Path, name: str) -> dict | None:
        fingerprint = WorkspaceManager._fingerprint(root, name)
        if fingerprint is None:
            return None
        return {"fingerprint": fingerprint,
                "content": WorkspaceManager._content(root, name, fingerprint)}

    @staticmethod
    def _write_file(root: Path, name: str, content: bytes, mode: str, permissions: int,
                    created_dirs: list[Path]) -> None:
        WorkspaceManager._safe_parents(root, name)
        target = root / name
        missing: list[Path] = []
        parent = target.parent
        while parent != root and not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir()
            created_dirs.append(directory)
        if target in created_dirs and target.is_dir() and not target.is_symlink():
            target.rmdir()
        temporary = target.parent / (".parallax-apply-" + uuid.uuid4().hex)
        try:
            if mode == "120000":
                link = os.fsdecode(content)
                try:
                    resolved = (target.parent / link).resolve(strict=False)
                except (OSError, RuntimeError) as exc:
                    raise WorkspaceError("Invalid workspace symlink: " + name) from exc
                if not resolved.is_relative_to(root):
                    raise WorkspaceError("External symlinks are unsupported: " + name)
                temporary.symlink_to(link)
            else:
                with temporary.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(permissions)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _planned_file(content: bytes, mode: str, permissions: int) -> dict:
        value = {"mode": mode, "permissions": 0o777 if mode == "120000" else permissions,
                 "sha256": hashlib.sha256(content).hexdigest()}
        if mode == "120000":
            value["target"] = os.fsdecode(content)
        return value

    def _recover_apply(self) -> None:
        """Reconcile a process crash between filesystem integration and result save."""
        transaction = self._metadata["apply_transaction"]
        source = transaction["source_state"]
        changed = transaction["changed_files"]
        target_files = transaction["target_files"]
        current = self._source_state()
        untouched = lambda files: {name: value for name, value in files.items() if name not in changed}
        if (all(current["files"].get(name) == target_files.get(name) for name in changed)
                and all(current[key] == source[key] for key in ("head", "branch", "index"))
                and untouched(current["files"]) == untouched(source["files"])):
            transaction["state"] = "committed"
            self._metadata.update({"applied": True, "applied_changed_files": changed, "recovered_apply": True})
            self._metadata["preservation"] = {"staging": True, "head": True, "branch": True, "unrelated_files": True}
            self._save()
            return
        original_tree = self._tree(transaction["base_commit"])
        unrestored: list[str] = []
        created_dirs: list[Path] = []
        for name in reversed(changed):
            try:
                original = source["files"].get(name)
                actual = self._fingerprint(self.workspace, name)
                if actual == original:
                    continue
                if actual != target_files.get(name):
                    unrestored.append(name)
                    continue
                if original is None:
                    (self.workspace / name).unlink(missing_ok=True)
                else:
                    _, oid = original_tree[name]
                    content = self._git(self.workspace, "cat-file", "blob", oid).stdout
                    self._write_file(self.workspace, name, content, original["mode"],
                                     original["permissions"], created_dirs)
            except (OSError, WorkspaceError, subprocess.SubprocessError):
                unrestored.append(name)
        self._metadata["applied"] = False
        transaction["state"] = "rollback_incomplete" if unrestored else "rolled_back"
        self._metadata["recovered_apply"] = True
        if unrestored:
            self._metadata["recovery_error"] = "Interrupted integration has external edits; inspect " + ", ".join(sorted(unrestored))
        self._save()
        if unrestored:
            raise WorkspaceError(self._metadata["recovery_error"])

    def apply(self) -> dict:
        """Apply verified candidate bytes, preserving staging and rolling back failures.

        External editors cannot participate in a filesystem transaction.  Content
        guards run before every write; rollback never overwrites a subsequent
        external edit, and an incomplete rollback is reported explicitly.
        """
        with self._lock:
            if self._metadata.get("applied"):
                return {"ok": True, "changed_files": self._metadata.get("applied_changed_files", []), "error": None,
                        "preservation": self._metadata.get("preservation", {})}
            if self._metadata.get("recovery_error"):
                return {"ok": False, "changed_files": [], "error": self._metadata["recovery_error"]}
            destination = self.check_destination()
            if not destination["ok"]:
                return {"ok": False, "changed_files": [], "error": destination["error"]}
            if destination["revalidate"]:
                return {"ok": False, "changed_files": [], "revalidate": True,
                        "error": "Source changed outside team files; refresh the candidate and rerun checks"}
            changed = destination["changed_files"]
            if not changed:
                return {"ok": True, "changed_files": [], "error": None,
                        "preservation": {"staging": True, "head": True, "branch": True, "unrelated_files": True}}
            backups: dict[str, dict | None] = {}
            written: list[str] = []
            applied: dict[str, dict | None] = {}
            created_dirs: list[Path] = []
            try:
                entries = self._tree(self._metadata["integration_commit"])
                updates: dict[str, tuple[str, bytes]] = {}
                for name in changed:
                    backups[name] = self._read_backup(self.workspace, name)
                    if name in entries:
                        mode, oid = entries[name]
                        updates[name] = (mode, self._git(self.workspace, "cat-file", "blob", oid).stdout)
                if self._source_state() != self._metadata["source_state"]:
                    raise WorkspaceError("Source changed immediately before integration; rerun verification")
                order = sorted(changed, key=lambda name: (name in updates, -len(PurePosixPath(name).parts), name))
                for name in changed:
                    if name not in updates:
                        applied[name] = None
                    else:
                        original = backups[name]
                        expected = original["fingerprint"] if original else None
                        mode, content = updates[name]
                        permissions = expected["permissions"] if expected and expected["mode"] != "120000" else 0o644
                        permissions = permissions | 0o111 if mode == "100755" else permissions & ~0o111
                        applied[name] = self._planned_file(content, mode, permissions)
                self._metadata["apply_transaction"] = {
                    "state": "applying", "changed_files": order, "target_files": applied,
                    "source_state": self._metadata["source_state"], "base_commit": self._metadata["patch_base_commit"]}
                self._save()
                for name in order:
                    original = backups[name]
                    expected = original["fingerprint"] if original else None
                    if self._fingerprint(self.workspace, name) != expected:
                        raise WorkspaceError("Source changed during integration: " + name)
                    written.append(name)
                    if name not in updates:
                        (self.workspace / name).unlink()
                    else:
                        mode, content = updates[name]
                        self._write_file(self.workspace, name, content, mode, applied[name]["permissions"], created_dirs)
                    if self._fingerprint(self.workspace, name) != applied[name]:
                        raise WorkspaceError("Source changed while writing integration: " + name)
                end = self._source_state()
                start = self._metadata["source_state"]
                if any(end[key] != start[key] for key in ("head", "branch", "index")):
                    raise WorkspaceError("Source Git state changed during integration")
                if {name: value for name, value in end["files"].items() if name not in changed} != {
                        name: value for name, value in start["files"].items() if name not in changed}:
                    raise WorkspaceError("Unrelated source files changed during integration; rerun combined checks")
                self._metadata["applied"] = True
                self._metadata["applied_changed_files"] = changed
                self._metadata["apply_transaction"]["state"] = "committed"
                self._metadata["preservation"] = {"staging": True, "head": True, "branch": True, "unrelated_files": True}
                self._save()
                return {"ok": True, "changed_files": changed, "error": None,
                        "preservation": self._metadata["preservation"]}
            except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                unrestored: list[str] = []
                for name in reversed(written):
                    try:
                        original = backups[name]
                        actual = self._fingerprint(self.workspace, name)
                        if actual == (original["fingerprint"] if original else None):
                            continue
                        if actual != applied[name]:
                            unrestored.append(name)
                            continue
                        if original is None:
                            (self.workspace / name).unlink(missing_ok=True)
                        else:
                            value = original["fingerprint"]
                            self._write_file(self.workspace, name, original["content"], value["mode"],
                                             value["permissions"], created_dirs)
                    except (OSError, WorkspaceError):
                        unrestored.append(name)
                for directory in reversed(created_dirs):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                message = str(exc)
                self._metadata["applied"] = False
                if "apply_transaction" in self._metadata:
                    self._metadata["apply_transaction"]["state"] = "rollback_incomplete" if unrestored else "rolled_back"
                if unrestored:
                    message += "; rollback incomplete for " + ", ".join(sorted(unrestored)) + "; inspect these files"
                    self._metadata["recovery_error"] = message
                try:
                    self._save()
                except OSError:
                    message += "; workspace recovery metadata could not be saved"
                return {"ok": False, "changed_files": sorted(unrestored), "error": message}
