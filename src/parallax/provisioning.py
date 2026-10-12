"""Convert project declarations to a bounded, wheel-only installation input."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

POLICY = "Python provisioning requires pinned sha256 requirements and wheels only; local/VCS/editable source builds and index overrides are refused. Supply requirements.lock or vetted local wheels."
MAX_WHEEL = 128 * 1024 * 1024
PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+(?:\s*;\s*[A-Za-z0-9_.'\"<>=!(); \t-]+)?")
HASH = re.compile(r"\s+--hash=sha256:([0-9a-fA-F]{64})(?=\s|$)")

YARN_POLICY = "Yarn provisioning requires Classic 1.22.x, a Yarn v1 lock and bounded regular workspace manifests. Berry, pnpm, external paths and nested workspaces are unsupported."


def yarn_classic_tool(executable=None):
    """Select one installed Classic package, never its parent tool directory."""
    value = executable or shutil.which("yarn")
    if not value:
        raise ValueError("Install Yarn Classic 1.22.x on the worker before checks")
    launch = Path(value).absolute()
    resolved = launch.resolve()
    package = resolved.parent.parent
    manifest = package / "package.json"
    library = package / "lib" / "cli.js"
    if resolved.name != "yarn.js" or resolved.parent.name != "bin" or not resolved.is_file():
        raise ValueError(YARN_POLICY)
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1_000_000:
        raise ValueError(YARN_POLICY)
    try:
        metadata = json.loads(manifest.read_text())
    except (OSError, ValueError):
        raise ValueError(YARN_POLICY)
    version = metadata.get("version", "") if isinstance(metadata, dict) else ""
    if not isinstance(metadata, dict) or metadata.get("name") != "yarn" or not re.fullmatch(r"1\.22\.[0-9]+", version):
        raise ValueError(YARN_POLICY)
    if library.is_symlink() or not library.is_file() or library.stat().st_size > 16 * 1024 * 1024:
        raise ValueError(YARN_POLICY)
    digest = hashlib.sha256(manifest.read_bytes() + resolved.read_bytes() + library.read_bytes()).hexdigest()
    return {"launch": launch, "package": package, "version": version, "sha256": digest}


def yarn_classic_inputs(workspace):
    """Fingerprint the complete admitted monorepo input without running code."""
    root = Path(workspace).resolve()
    def package(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError(YARN_POLICY)
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            raise ValueError(YARN_POLICY)
        if not isinstance(value, dict):
            raise ValueError(YARN_POLICY)
        manager = value.get("packageManager")
        if manager is not None and (not isinstance(manager, str) or not re.fullmatch(r"yarn@1\.22\.[0-9]+", manager)):
            raise ValueError(YARN_POLICY)
        for field in ("dependencies", "devDependencies", "optionalDependencies", "resolutions"):
            dependencies = value.get(field, {})
            if not isinstance(dependencies, dict):
                raise ValueError(YARN_POLICY)
            for spec in dependencies.values():
                if not isinstance(spec, str) or re.match(r"(?:file:|link:|git(?:\+|:)|ssh:|github:|\.{1,2}/|/)", spec):
                    raise ValueError(YARN_POLICY)
        return value
    lock = root / "yarn.lock"
    if lock.is_symlink() or not lock.is_file() or lock.stat().st_size > 1_000_000:
        raise ValueError(YARN_POLICY)
    content = lock.read_text()
    if "# yarn lockfile v1" not in content.splitlines()[:12] or re.search(r"^__metadata:", content, re.M):
        raise ValueError(YARN_POLICY)
    if any(not re.fullmatch(r'  resolved "https://[^\s"]+"', line) for line in content.splitlines() if line.startswith("  resolved ")):
        raise ValueError(YARN_POLICY)
    if any((root / name).exists() or (root / name).is_symlink() for name in (".yarnrc.yml", "pnpm-lock.yaml")):
        raise ValueError(YARN_POLICY)
    metadata = package(root / "package.json")
    members = metadata.get("workspaces", [])
    if isinstance(members, dict):
        if set(members) - {"packages", "nohoist"}:
            raise ValueError(YARN_POLICY)
        members = members.get("packages", [])
    if not isinstance(members, list) or len(members) > 64 or members and metadata.get("private") is not True:
        raise ValueError(YARN_POLICY)
    paths = {root / "package.json", lock}
    names = set()
    for pattern in members:
        if not isinstance(pattern, str) or not pattern or len(pattern) > 200 or "\\" in pattern or "\x00" in pattern:
            raise ValueError(YARN_POLICY)
        relative = Path(pattern)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) > 8 or pattern.startswith("!") or "**" in pattern:
            raise ValueError(YARN_POLICY)
        for count, directory in enumerate(root.glob(pattern)):
            if count > 512:
                raise ValueError(YARN_POLICY)
            if not directory.is_dir():
                continue
            child = directory.relative_to(root)
            cursor = root
            for part in child.parts:
                cursor = cursor / part
                if cursor.is_symlink() or part in {"node_modules", ".git", ".yarn", ".venv"}:
                    raise ValueError(YARN_POLICY)
            if directory == root or not directory.resolve().is_relative_to(root):
                raise ValueError(YARN_POLICY)
            manifest = directory / "package.json"
            if not manifest.exists() and not manifest.is_symlink():
                continue
            value = package(manifest)
            if value.get("workspaces") or not isinstance(value.get("name"), str) or value["name"] in names:
                raise ValueError(YARN_POLICY)
            names.add(value["name"])
            paths.add(manifest)
            if len(paths) > 130:
                raise ValueError(YARN_POLICY)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def locked_python_input(workspace, manifest, dependencies, stage=None):
    """Return sanitized lock content; no project input is passed to pip directly."""
    workspace = workspace.resolve()
    if manifest:
        content = manifest.read_text()
    else:
        content = "\n".join(dependencies)
    lines, pending = [], ""
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        continued = raw.endswith("\\")
        pending += raw[:-1] + " " if continued else raw
        if not continued:
            lines.append(pending.strip()); pending = ""
    if pending or len(lines) > 1000:
        raise ValueError(POLICY)
    normalized, wheels = [], set()
    for line in lines:
        if line == "--no-index":
            normalized.append(line); continue
        hashes = HASH.findall(line)
        requirement = HASH.sub("", line).strip()
        if "--" in requirement or "${" in requirement or len(line) > 20000:
            raise ValueError(POLICY)
        if PIN.fullmatch(requirement):
            if not hashes:
                raise ValueError(POLICY)
            normalized.append(requirement + " " + " ".join("--hash=sha256:" + h.lower() for h in hashes))
            continue
        # Vendored wheels are copied into the repository-free stage and pinned
        # to their actual bytes. Never admit a directory or source distribution.
        relative = Path(requirement)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".whl":
            raise ValueError(POLICY)
        source = workspace / relative
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(workspace) or source.stat().st_size > MAX_WHEEL:
            raise ValueError(POLICY)
        destination = stage / relative.name if stage else None
        if relative.name in wheels or (destination and destination.is_symlink()):
            raise ValueError("Duplicate vendored wheel filename; " + POLICY)
        wheels.add(relative.name)
        digest = hashlib.sha256()
        writer = destination.open("wb") if destination else None
        try:
            with source.open("rb") as reader:
                size=0
                while chunk := reader.read(1024 * 1024):
                    size+=len(chunk)
                    if size>MAX_WHEEL: raise ValueError(POLICY)
                    digest.update(chunk)
                    if writer: writer.write(chunk)
        finally:
            if writer: writer.close()
        actual = digest.hexdigest()
        if hashes and actual not in [h.lower() for h in hashes]:
            raise ValueError("Vendored wheel hash mismatch; " + POLICY)
        normalized.append(str(destination) if destination else relative.name)
        normalized[-1] += " --hash=sha256:" + actual
    return "\n".join(normalized) + "\n"
