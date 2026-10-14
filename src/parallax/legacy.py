#!/usr/bin/env python3
"""Call the signed-in Claude Code CLI from a local Codex task."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path


CONSULT_TOOLS = "Read,Glob,Grep"
EDIT_TOOLS = "Read,Glob,Grep,Edit,Write"
MAX_PROMPT_BYTES = 10_000_000
MAX_TRACKED_FILES = 100_000


def process(command: list[str], *, cwd: Path, timeout: int, input_text: str | None = None,
            env: dict[str, str] | None = None) -> tuple[int, str, str]:
    child = subprocess.Popen(
        command, cwd=cwd, env=env, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        stdout, stderr = child.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
        raise
    return child.returncode, stdout, stderr


def git_root(workspace: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=workspace,
        capture_output=True, text=True, check=False, timeout=10,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def fingerprint(path: Path) -> tuple[int, int, int, str] | None:
    try:
        info = path.lstat()
        link = os.readlink(path) if stat.S_ISLNK(info.st_mode) else ""
        return info.st_mode, info.st_size, info.st_mtime_ns, link
    except FileNotFoundError:
        return None


def git_dirty_paths(workspace: Path, root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-c", "status.relativePaths=false", "status", "--porcelain=v1", "-z",
         "--untracked-files=all", "--", "."],
        cwd=workspace, capture_output=True, check=True, timeout=30,
    )
    fields = result.stdout.split(b"\0")
    paths: set[str] = set()
    i = 0
    while i < len(fields) and fields[i]:
        item = fields[i]
        code = item[:2]
        paths.add(os.fsdecode(item[3:]))
        i += 1
        if b"R" in code or b"C" in code:
            if i < len(fields) and fields[i]:
                paths.add(os.fsdecode(fields[i]))
            i += 1
    return paths


def snapshot(workspace: Path) -> tuple[str, Path, dict[str, tuple[int, int, int, str] | None]]:
    root = git_root(workspace)
    if root is not None:
        paths = git_dirty_paths(workspace, root)
        return "git", root, {name: fingerprint(root / name) for name in paths}

    files: dict[str, tuple[int, int, int, str] | None] = {}
    for parent, dirs, names in os.walk(workspace, followlinks=False):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = Path(parent) / name
            files[str(path.relative_to(workspace))] = fingerprint(path)
            if len(files) > MAX_TRACKED_FILES:
                raise RuntimeError("Workspace contains too many files for non-Git change tracking")
    return "filesystem", workspace, files


def changed_files(before: tuple[str, Path, dict], after: tuple[str, Path, dict],
                  workspace: Path) -> list[str]:
    before_kind, before_root, before_files = before
    after_kind, after_root, after_files = after
    if before_kind != after_kind or before_root != after_root:
        raise RuntimeError("Workspace change-tracking method changed during the Claude run")
    changed = {name for name in before_files.keys() | after_files.keys()
               if before_files.get(name) != after_files.get(name)}
    if before_kind == "git":
        return sorted(str((before_root / name).relative_to(workspace)) for name in changed)
    return sorted(changed)


def fail(message: str, *, mode: str, workspace: Path, elapsed: float = 0,
         session_id: str | None = None, changed: list[str] | None = None,
         exit_code: int | None = None) -> dict:
    return {"ok": False, "mode": mode, "workspace": str(workspace), "answer": None,
            "session_id": session_id, "changed_files": changed or [], "error": message,
            "exit_code": exit_code, "elapsed_seconds": round(elapsed, 2)}


def run(workspace: Path, mode: str, prompt: str, resume: str | None, timeout: int,
        claude_bin: str = "claude") -> dict:
    started = time.monotonic()
    workspace = workspace.expanduser().resolve()
    if not workspace.is_dir():
        return fail("Workspace directory does not exist", mode=mode, workspace=workspace)
    if not prompt.strip():
        return fail("Prompt is empty", mode=mode, workspace=workspace)
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        return fail("Prompt exceeds Claude CLI's 10 MB stdin limit", mode=mode, workspace=workspace)
    if resume:
        try:
            uuid.UUID(resume)
        except ValueError:
            return fail("Session ID must be a UUID", mode=mode, workspace=workspace)

    executable = shutil.which(claude_bin)
    if not executable:
        return fail("Claude Code CLI was not found", mode=mode, workspace=workspace)
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # Use the existing subscription login.
    try:
        auth_code, auth_out, _ = process([executable, "auth", "status"], cwd=workspace,
                                         timeout=10, env=env)
        auth = json.loads(auth_out)
        if auth_code != 0 or not auth.get("loggedIn"):
            return fail("Claude Code is not signed in; run 'claude auth login'", mode=mode,
                        workspace=workspace, exit_code=auth_code)
        before = snapshot(workspace)
        instruction = (
            "Give an independent assessment of the user's request. Inspect relevant files in the "
            "current workspace when useful. Do not change files. State your findings, uncertainty, "
            "and recommended next steps.\n\nRequest:\n"
            if mode == "consult" else
            "Work on the specifically delegated task in the current workspace. Change only files "
            "needed for that task. Preserve unrelated or pre-existing changes. Explain what you "
            "changed and any remaining checks for Codex.\n\nTask:\n"
        )
        command = [executable, "--safe-mode", "--restricted", "--no-chrome", "-p", "--output-format", "json",
                   "--tools", CONSULT_TOOLS if mode == "consult" else EDIT_TOOLS,
                   "--permission-mode", "dontAsk" if mode == "consult" else "acceptEdits",
                   "--permission-prompts", "none"]
        if resume:
            command += ["--resume", resume]
        exit_code, stdout, stderr = process(command, cwd=workspace, timeout=timeout,
                                            input_text=instruction + prompt, env=env)
        after = snapshot(workspace)
        changed = changed_files(before, after, workspace)
        elapsed = time.monotonic() - started
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return fail("Claude returned malformed JSON" + (f": {stderr.strip()[:500]}" if stderr.strip() else ""),
                        mode=mode, workspace=workspace, elapsed=elapsed, changed=changed,
                        exit_code=exit_code)
        answer = payload.get("result")
        session_id = payload.get("session_id")
        if exit_code != 0 or payload.get("is_error") or not isinstance(answer, str):
            detail = answer if isinstance(answer, str) else stderr.strip()
            return fail(f"Claude run failed: {detail[:1000]}", mode=mode, workspace=workspace,
                        elapsed=elapsed, session_id=session_id, changed=changed, exit_code=exit_code)
        if mode == "consult" and changed:
            return fail("Read-only consultation changed workspace files; inspect them before continuing",
                        mode=mode, workspace=workspace, elapsed=elapsed, session_id=session_id,
                        changed=changed, exit_code=exit_code)
        return {"ok": True, "mode": mode, "workspace": str(workspace), "answer": answer,
                "session_id": session_id, "changed_files": changed, "error": None,
                "exit_code": exit_code, "elapsed_seconds": round(elapsed, 2)}
    except subprocess.TimeoutExpired:
        changed = []
        try:
            changed = changed_files(before, snapshot(workspace), workspace)
        except (NameError, OSError, RuntimeError, subprocess.SubprocessError):
            pass
        return fail(f"Claude did not finish within {timeout} seconds", mode=mode,
                    workspace=workspace, elapsed=time.monotonic() - started, changed=changed)
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return fail(f"Bridge error: {exc}", mode=mode, workspace=workspace,
                    elapsed=time.monotonic() - started)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--mode", choices=("consult", "edit"), default="consult")
    parser.add_argument("--prompt-file", type=Path, help="Read the task from this UTF-8 file; otherwise read stdin")
    parser.add_argument("--resume", help="Claude session UUID from a previous bridge result")
    parser.add_argument("--timeout", type=int, help="Seconds before stopping Claude (default: 180 consult, 600 edit)")
    parser.add_argument("--claude-bin", default="claude", help="Claude executable (mainly for testing)")
    args = parser.parse_args()
    if args.timeout is not None and args.timeout < 1:
        parser.error("--timeout must be positive")
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else sys.stdin.read()
    result = run(args.workspace, args.mode, prompt, args.resume,
                 args.timeout or (180 if args.mode == "consult" else 600), args.claude_bin)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
