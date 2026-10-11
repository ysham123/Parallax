#!/usr/bin/env python3
"""Experimental WSL2 capability check; no inference, sign-in or configuration changes.

Run inside the intended WSL2 distribution. Project contents are never executed.
Only version diagnostics and synthetic, temporary sandbox canaries are run.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


LINUX_FILESYSTEMS = frozenset({"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "tmpfs", "overlay"})
PROVIDERS = {"codex": "codex", "claude": "claude", "antigravity": "agy", "grok": "grok"}
MAX_OUTPUT = 65536
SCOPE = ("Capabilities and version diagnostics only. Authentication, provider tool enforcement, "
         "model inference, a complete task and Windows/WSL product acceptance remain unverified.")


@dataclass
class Probe:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""
    failure: str | None = None


def _stop_group(process):
    # No poll()/wait() has reaped the session leader yet, so its PID cannot be
    # reused for an unrelated group. Kill descendants before releasing that PID.
    denied = False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Some POSIX hosts refuse signals to an already exited leader.
            # Never substitute a saved PID or another process as a target.
            denied = True
        if sig == signal.SIGTERM:
            time.sleep(.05)
    return not denied


def bounded_run(argv, *, env, cwd, timeout=5, max_output=MAX_OUTPUT):
    """Bound both pipes and clean the created process group, including on EOF."""
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, cwd=cwd, start_new_session=True)
    except (OSError, ValueError):
        return Probe(-1, failure="launch_failed")
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    failure = None
    try:
        for label in output:
            selector.register(getattr(process, label), selectors.EVENT_READ, label)
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "timeout"
                break
            for key, _ in selector.select(min(remaining, .1)):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = max_output - sum(map(len, output.values()))
                output[key.data].extend(chunk[:max(0, room)])
                if len(chunk) > room:
                    failure = "output_limit"
                    break
            if failure:
                break
    except OSError:
        failure = "capture_failed"
    finally:
        selector.close()
        cleanup_ok = _stop_group(process)
        process.stdout.close()
        process.stderr.close()
    try:
        code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return Probe(-1, bytes(output["stdout"]), bytes(output["stderr"]), "termination_failed")
    return Probe(code, bytes(output["stdout"]), bytes(output["stderr"]), failure or (None if cleanup_ok else "cleanup_denied"))


def is_wsl2(platform_name, kernel):
    value = kernel.lower()
    return platform_name.startswith("linux") and "microsoft" in value and "wsl2" in value


def mount_table(content):
    """Parse kernel mountinfo; ignore mount sources, options and private values."""
    if len(content) > 1024 * 1024:
        return []
    result = []
    for line in content.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
            if separator < 6:
                continue
            escaped = fields[4]
            point = re.sub(r"\\(040|011|012|134)", lambda match: chr(int(match[1], 8)), escaped)
            if not point.startswith("/"):
                continue
            result.append((Path(point), fields[separator + 1].lower()))
        except (ValueError, IndexError):
            continue
    return result


def filesystem(path, mounts):
    try:
        resolved = Path(path).resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        return None
    matches = [(point, kind) for point, kind in mounts if resolved == point or resolved.is_relative_to(point)]
    if not matches:
        return None
    depth = max(len(point.parts) for point, _ in matches)
    kinds = {kind for point, kind in matches if len(point.parts) == depth}
    # Stacked/ambiguous mounts must not let an earlier Linux record hide a
    # Windows/shared filesystem at the same canonical mount point.
    return next(iter(kinds)) if len(kinds) == 1 else None


def linux_path(path, mounts):
    return filesystem(path, mounts) in LINUX_FILESYSTEMS


def linux_search_path(value, mounts, *, excluded=()):
    entries = []
    for raw in value.split(os.pathsep):
        path = Path(raw)
        if (raw and path.is_absolute() and path.is_dir() and linux_path(path, mounts)
                and not any(path.resolve() == root or path.resolve().is_relative_to(root) for root in excluded)):
            canonical = str(path.resolve())
            if canonical not in entries:
                entries.append(canonical)
    return os.pathsep.join(entries)


def executable(path, mounts):
    try:
        original = Path(path)
        resolved = original.resolve(strict=True)
        if (original.suffix.lower() in {".exe", ".cmd", ".bat", ".ps1"}
                or resolved.suffix.lower() in {".exe", ".cmd", ".bat", ".ps1"}
                or not resolved.is_file() or not os.access(resolved, os.X_OK) or not linux_path(resolved, mounts)):
            return None
        with resolved.open("rb") as stream:
            if stream.read(2) == b"MZ":
                return None  # A copied/renamed Windows executable is still Windows.
        return resolved
    except (OSError, ValueError, RuntimeError, TypeError):
        return None


def version(probe):
    if probe.returncode or probe.failure:
        return None
    match = re.search(rb"(?<![0-9])[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}(?![0-9])", probe.stdout + b"\n" + probe.stderr)
    return match[0].decode("ascii") if match else None


def sandbox_probe(bwrap, python, home, *, env, runner=bounded_run):
    """Mandatory namespaces and limited mounts, with no project or host HOME grant."""
    allowed, writable = home / "readable", home / "writable"
    allowed.mkdir(); writable.mkdir()
    (allowed / "visible.txt").write_text("SYNTHETIC_VISIBLE")
    hidden = home / "hidden.txt"
    hidden.write_text("SYNTHETIC_PRIVATE")
    namespaces = {name: os.readlink("/proc/self/ns/" + name) for name in ("user", "mnt", "pid", "net")}
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(.05)
        arguments = {"allowed": str(allowed), "writable": str(writable), "hidden": str(hidden),
                     "namespaces": namespaces, "port": listener.getsockname()[1]}
        program = '''import json,os,socket,sys
from pathlib import Path
value=json.loads(sys.argv[1]); result={}
result['allowed_read']=Path(value['allowed'],'visible.txt').read_text()=='SYNTHETIC_VISIBLE'
try: Path(value['hidden']).read_bytes(); result['private_read_denied']=False
except OSError: result['private_read_denied']=True
try: Path(value['allowed'],'forbidden.txt').write_text('blocked'); result['readonly_write_denied']=False
except OSError: result['readonly_write_denied']=True
Path(value['writable'],'written.txt').write_text('SYNTHETIC_WRITE'); result['scratch_write']=True
for name,before in value['namespaces'].items(): result[name+'_namespace']=os.readlink('/proc/self/ns/'+name)!=before
try:
 connection=socket.create_connection(('127.0.0.1',value['port']),timeout=.5); connection.close(); result['host_loopback_denied']=False
except OSError: result['host_loopback_denied']=True
print(json.dumps(result))
'''
        command = [str(bwrap), "--die-with-parent", "--new-session", "--unshare-user",
                   "--unshare-pid", "--unshare-net", "--tmpfs", "/"]
        for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache"):
            if Path(path).exists():
                command += ["--ro-bind", path, path]
        base = Path(sys.base_prefix).resolve()
        if not base.is_relative_to(Path("/usr")):
            command += ["--ro-bind", str(base), str(base)]
        command += ["--proc", "/proc", "--dev", "/dev", "--ro-bind", str(allowed), str(allowed),
                    "--bind", str(writable), str(writable), "--chdir", str(writable),
                    "--", str(python), "-I", "-S", "-B", "-c", program, json.dumps(arguments)]
        outcome = runner(command, env=env, cwd=home, timeout=5)
        try:
            evidence = json.loads(outcome.stdout)
        except (ValueError, UnicodeError):
            evidence = {}
        required = {"allowed_read", "private_read_denied", "readonly_write_denied", "scratch_write",
                    "user_namespace", "mnt_namespace", "pid_namespace", "net_namespace", "host_loopback_denied"}
        passed = outcome.returncode == 0 and not outcome.failure and isinstance(evidence, dict)
        passed = passed and all(evidence.get(name) is True for name in required)
        passed = passed and (writable / "written.txt").is_file() and not (allowed / "forbidden.txt").exists()
        try:
            connection, _ = listener.accept(); connection.close(); passed = False
        except socket.timeout:
            pass
        return bool(passed)
    finally:
        listener.close()


def assess(project, providers=("codex",), *, platform_name=None, kernel=None, mountinfo=None,
           which=shutil.which, runner=bounded_run, sandbox=sandbox_probe):
    platform_name = platform_name or sys.platform
    kernel = platform.release() if kernel is None else kernel
    checks, tools = [], []
    def check(name, ok, guidance):
        checks.append({"check": name, "ok": bool(ok), "guidance": None if ok else guidance})
    result = {"ok": False, "status": "unavailable", "wsl_acceptance": "unverified", "checks": checks,
              "tools": tools, "provider_calls": 0, "scope": SCOPE}
    if not is_wsl2(platform_name, kernel):
        result["status"] = "unsupported" if platform_name == "win32" else "unavailable"
        check("Identified WSL2 Linux kernel", False,
              "Run inside a WSL2 distribution with its standard Microsoft WSL2 kernel. Native Windows is unsupported; confirm version2 with wsl --list --verbose in PowerShell.")
        return result
    check("Identified WSL2 Linux kernel", True, "")
    if mountinfo is None:
        try:
            with Path("/proc/self/mountinfo").open() as stream:
                mountinfo = stream.read(1024 * 1024 + 1)
        except OSError:
            mountinfo = ""
    mounts = mount_table(mountinfo)
    try:
        location = Path(project).expanduser().resolve(strict=True)
        project_ok = location.is_dir() and linux_path(location, mounts)
    except (OSError, ValueError, RuntimeError):
        project_ok = False
    check("Project on Linux filesystem", project_ok,
          "Keep the repository inside the Linux distribution, such as ~/projects; Windows/shared mounts and their symlink aliases are refused.")
    python = executable(sys.executable, mounts)
    base = Path(sys.base_prefix).resolve()
    prefix = Path(sys.prefix).resolve()
    broad_roots = {Path("/"), Path("/home"), Path("/root"), Path.home().resolve()}
    project_runtime = project_ok and (base.is_relative_to(location) or prefix.is_relative_to(location)
                                      or (python and python.is_relative_to(location)))
    python_ok = bool(python and sys.version_info >= (3, 10) and linux_path(base, mounts)
                     and linux_path(prefix, mounts) and base not in broad_roots and not project_runtime)
    check("Linux Python3.10+ runtime", python_ok, "Use Linux Python3.10+ installed inside this distribution.")
    search_path = linux_search_path(os.environ.get("PATH", os.defpath), mounts,
                                    excluded=(location,) if project_ok else ())
    selected = {}
    requirements = {"git": ("git", "--version"), "bubblewrap": ("bwrap", "--version"), "socat": ("socat", "-V")}
    requirements.update({name: (PROVIDERS[name], "--version") for name in dict.fromkeys(providers)})
    for label, (binary, flag) in requirements.items():
        path = which(binary, path=search_path)
        safe = executable(path, mounts) if path else None
        if safe and project_ok and (safe == location or safe.is_relative_to(location)):
            safe = None
        if label == "grok":
            safe = None  # Existing product policy refuses native Grok execution.
        selected[label] = (safe, flag)
        tools.append({"tool": label, "available_linux": bool(safe), "version": None,
                      "scope": "version only; not sign-in, quota or model readiness"})
        check(label + " Linux executable", safe,
              "Install the Linux CLI in the distribution. Native Grok is unsupported; use a supported provider or configured API adapter.")
    if not all(item["ok"] for item in checks):
        return result  # Never execute a Windows tool or probe a refused project.
    try:
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        if (not linux_path(temporary_root, mounts) or temporary_root == location
                or temporary_root.is_relative_to(location)):
            check("Private Linux probe directory", False, "Use a Linux temporary directory outside the project, without changing sandbox security.")
            return result
        with tempfile.TemporaryDirectory(prefix="parallax-wsl-preflight-", dir=temporary_root) as directory:
            home = Path(directory).resolve()
            if not linux_path(home, mounts):
                check("Private Linux probe directory", False, "Configure a Linux temporary directory, without changing sandbox security.")
                return result
            env = {"PATH": search_path, "HOME": str(home), "TMPDIR": str(home), "CI": "true", "LANG": "C.UTF-8",
                   "XDG_CONFIG_HOME": str(home), "XDG_CACHE_HOME": str(home), "XDG_DATA_HOME": str(home)}
            for tool in tools:
                path, flag = selected[tool["tool"]]
                diagnostic = runner([str(path), flag], env=env, cwd=home, timeout=5)
                tool["version"] = version(diagnostic)
                good = bool(tool["version"])
                if tool["tool"] == "git" and good:
                    good = tuple(map(int, tool["version"].split(".")[:2])) >= (2, 38)
                check(tool["tool"] + " bounded version diagnostic", good,
                      "Check this Linux CLI installation/version locally. Raw stdout, stderr, credentials and paths are not reported.")
            if all(item["ok"] for item in checks):
                check("Enforced user/mount/PID/network namespace and filesystem canaries",
                      sandbox(selected["bubblewrap"][0], python, home, env=env, runner=runner),
                      "Working unprivileged bubblewrap namespaces are required. Do not disable isolation or bypass namespace failures.")
    except (OSError, ValueError, RuntimeError, KeyError):
        check("Bounded capability probes completed", False, "Inspect local Linux installation and namespace availability; supplied values are not rendered.")
    result["ok"] = all(item["ok"] for item in checks)
    result["status"] = "capabilities_verified" if result["ok"] else "unavailable"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--provider", action="append", choices=sorted(PROVIDERS), help="Linux native CLI to diagnose; repeat for independent providers. Default: codex.")
    options = parser.parse_args()
    result = assess(options.project, options.provider or ("codex",))
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
