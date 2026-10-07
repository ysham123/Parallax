"""Curated release inputs shared by packaging and offline validation."""
from pathlib import Path
import os

ENTRIES = (
    "src", "scripts", "skills", "studio", "tests", "assets", "docs",
    ".codex-plugin", ".claude-plugin", "claude-code", ".agents", ".github", ".mcp.json", "mcp.json",
    "plugin.json", "pyproject.toml", "uv.lock", "requirements.lock",
    "README.md", "UPGRADE.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "LICENSE", ".gitignore",
    "vercel.json", ".vercelignore", "railway.json", "Dockerfile", ".dockerignore",
)
EXCLUDED_COMPONENTS = {"node_modules", "dist", "__pycache__", ".venv", ".vercel", ".pytest_cache", ".playwright-cli", ".git", "releases", ".DS_Store"}
PRIVATE_COMPONENTS = {"api-sessions", "artifacts", "sessions", "runs", "environments", ".codex", ".claude", ".grok", ".gemini"}
PRIVATE_NAMES = {".parallax-owned", "server.json", "connections.json", "credentials.json", "auth.json", "token_cache.json", "models_cache.json", "jetski-standalone-oauth-token", "worker-connection.json", "runtime.json"}
PRIVATE_SUFFIXES = {".sqlite3", ".sqlite", ".db", ".log", ".pem", ".key"}


def private_input(relative: Path) -> bool:
    name = relative.name.lower()
    return (any(part in PRIVATE_COMPONENTS for part in relative.parts)
            or name in PRIVATE_NAMES or name == ".env" or name.startswith(".env.")
            or relative.suffix.lower() in PRIVATE_SUFFIXES
            or name.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")))


def release_files(root: Path) -> list[Path]:
    root = root.resolve()
    files = []

    def accept(path: Path) -> None:
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError("Release source cannot contain symlinks: " + str(relative))
        if private_input(relative):
            raise ValueError("Private runtime or credential file in release inputs: " + str(relative))
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            files.append(path)

    def failed(error: OSError) -> None:
        raise error

    for name in ENTRIES:
        entry = root / name
        if not entry.exists() and not entry.is_symlink():
            continue
        accept(entry)
        if entry.is_dir():
            for directory, directories, names in os.walk(entry, followlinks=False, onerror=failed):
                directories[:] = [name for name in directories if name not in EXCLUDED_COMPONENTS]
                for name in directories:
                    accept(Path(directory) / name)
                for name in names:
                    if name not in EXCLUDED_COMPONENTS:
                        accept(Path(directory) / name)
    return sorted(set(files), key=lambda path: str(path.relative_to(root)))
