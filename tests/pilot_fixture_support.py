"""Portable, disposable-only configuration and remote simulator for pilot fixtures."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import httpx


def fixture_options(argv=None):
    parser = argparse.ArgumentParser(description="Loopback pilot demo with fake providers and GitHub")
    parser.add_argument("--root", type=Path, default=Path.home() / "Parallax-adversarial-browser-fixture")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--state-name", default="", help="optional independent relay/worker state suffix")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.state_name and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.state_name):
        parser.error("--state-name must contain only letters, numbers, underscore and hyphen")
    return args


def prepare_fixture_root(path):
    """Never take ownership of an existing developer checkout or follow project symlinks."""
    path = path.expanduser().absolute()
    project = path / "project"
    marker = path / ".pilot-fixture"
    if path.is_symlink() or project.is_symlink() or marker.is_symlink():
        raise ValueError("Fixture root, project and marker must not be symlinks")
    path.mkdir(parents=True, exist_ok=True)
    if project.exists() and not marker.exists():
        # Adopt only the known earlier fixture, retaining its history and candidate state.
        def git(*args):
            return subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True).stdout.strip()
        try:
            legacy = (path == Path.home() / "Parallax-adversarial-browser-fixture"
                      and git("config", "user.email") == "fixture@example.invalid"
                      and not git("remote")
                      and git("log", "--format=%s", "--reverse").splitlines()[0] == "Fixture baseline"
                      and git("ls-tree", "--name-only", "HEAD").splitlines() == ["check.py", "maths.py"])
        except (OSError, subprocess.CalledProcessError, IndexError):
            legacy = False
        if not legacy:
            raise ValueError("Refusing an existing project without the fixture ownership marker; choose a fresh --root")
    marker.write_text("Parallax disposable pilot fixture\n")
    project.mkdir(exist_ok=True)
    return path, project


def fixture_asset(root, request_path):
    """Constrain static fixture requests to real files beneath the built Studio root."""
    root = root.resolve()
    target = (root / request_path.lstrip("/")).resolve()
    return target if target.is_relative_to(root) and target.is_file() else None


class FixtureGitHub:
    """GitHub-shaped state with unique commits, expected heads and same-PR revisions."""
    def __init__(self, base, tree):
        self.base, self.baseline_tree = base, tree
        self.remote = {"head": None, "tree": None, "pr": None}
        self.commits = {base: {"tree": {"sha": tree}, "message": "Fixture baseline"}}

    def __call__(self, request):
        path = request.url.path
        data = json.loads(request.content) if request.content else {}
        remote = self.remote
        if path == "/installation/repositories":
            return httpx.Response(200, json={"repositories": [{"id": 1, "full_name": "fixture/repo", "default_branch": "main"}]})
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "fixture-installation-token"})
        if path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": self.base, "commit": {"tree": {"sha": self.baseline_tree}}})
        if "matching-refs" in path:
            return httpx.Response(200, json=[{"ref": "refs/heads/" + remote["branch"], "object": {"sha": remote["head"]}}] if remote["head"] else [])
        if path.endswith("/git/refs"):
            remote.update(head=data["sha"], branch=data["ref"].removeprefix("refs/heads/"))
            return httpx.Response(201, json={})
        if path == "/graphql":
            value = data["variables"]["input"]
            if value["expectedHeadOid"] != remote["head"]:
                return httpx.Response(200, json={"errors": [{"message": "Expected head changed"}]})
            commit = hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()
            self.commits[commit] = {"tree": {"sha": remote["tree"]}, "message": value["message"]["body"]}
            remote["head"] = commit
            if remote["pr"]:
                remote["pr"]["head"]["sha"] = commit
            return httpx.Response(200, json={"data": {"createCommitOnBranch": {"commit": {"oid": commit}}}})
        if "/git/commits/" in path:
            commit = self.commits.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200 if commit else 404, json=commit or {})
        if path.endswith("/pulls") and request.method == "GET":
            return httpx.Response(200, json=[remote["pr"]] if remote["pr"] else [])
        if path.endswith("/pulls") and request.method == "POST":
            remote["pr"] = {"number": 1, "html_url": "https://github.com/fixture/repo/pull/1", "state": "open", "draft": True, "head": {"ref": remote["branch"], "sha": remote["head"]}}
            return httpx.Response(201, json=remote["pr"])
        if path.endswith("/pulls/1"):
            return httpx.Response(200, json=remote["pr"])
        if path.endswith("/check-runs"):
            return httpx.Response(200, json={"check_runs": [{"id": 1, "name": "Fixture CI", "status": "completed", "conclusion": "success", "html_url": "https://github.com/fixture/repo/actions"}]})
        if path.endswith("/status"):
            return httpx.Response(200, json={"statuses": []})
        if path.endswith("/comments"):
            return httpx.Response(200, json=[{"id": 1, "path": "maths.py", "line": 2, "body": "Keep the docstring concise.", "html_url": "https://github.com/fixture/repo/pull/1"}])
        if path.endswith("/reviews"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})
