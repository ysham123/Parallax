"""Convert project declarations to a bounded, wheel-only installation input."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

POLICY = "Python provisioning requires pinned sha256 requirements and wheels only; local/VCS/editable source builds and index overrides are refused. Supply requirements.lock or vetted local wheels."
MAX_WHEEL = 128 * 1024 * 1024
PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+(?:\s*;\s*[A-Za-z0-9_.'\"<>=!(); \t-]+)?")
HASH = re.compile(r"\s+--hash=sha256:([0-9a-fA-F]{64})(?=\s|$)")


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
