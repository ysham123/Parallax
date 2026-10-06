"""Explicit opt-in configuration for a single-team hosted runtime."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Deployment:
    token: str
    origins: frozenset[str]
    hosts: frozenset[str]
    projects: Path

    @classmethod
    def from_env(cls):
        token = os.environ.get("PARALLAX_ACCESS_TOKEN", "")
        if len(token) < 32 or len(token) > 512 or not token.isascii():
            raise ValueError("PARALLAX_ACCESS_TOKEN must contain 32 to 512 characters")
        origins = set()
        for value in os.environ.get("PARALLAX_STUDIO_ORIGINS", "").split(","):
            value = value.strip().rstrip("/")
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("PARALLAX_STUDIO_ORIGINS must list exact HTTPS origins")
            origins.add(value)
        hosts = {value.strip().lower() for value in os.environ.get("PARALLAX_ALLOWED_HOSTS", "").split(",") if value.strip()}
        if not hosts or any(not value.replace("-", "").replace(".", "").isalnum() for value in hosts):
            raise ValueError("PARALLAX_ALLOWED_HOSTS must list exact hostnames without ports or wildcards")
        projects = Path(os.environ.get("PARALLAX_PROJECTS_ROOT", "/data/projects")).resolve()
        return cls(token, frozenset(origins), frozenset(hosts), projects)

    def check_workspace(self, value: str):
        if not Path(value).expanduser().resolve().is_relative_to(self.projects.resolve()):
            raise ValueError("Hosted workspaces must be inside PARALLAX_PROJECTS_ROOT")
