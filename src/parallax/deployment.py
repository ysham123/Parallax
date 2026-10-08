"""Explicit opt-in configuration for the hosted runtime."""
from __future__ import annotations
from dataclasses import dataclass
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

# Values the hosted runtime reads once and then removes from its environment,
# so provider CLIs, project checks, and Git never inherit them.
HOSTED_SECRETS = ("PARALLAX_ACCESS_TOKEN", "PARALLAX_GITHUB_CLIENT_SECRET")
SIGNUP_POLICIES = ("open", "allowlist", "closed")


def _github_ids(name: str) -> frozenset[int]:
    values = set()
    for value in os.environ.get(name, "").split(","):
        value = value.strip()
        if not value:
            continue
        if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
            raise ValueError(f"{name} must list numeric GitHub account IDs")
        values.add(int(value))
    return frozenset(values)


@dataclass(frozen=True)
class GitHubApp:
    client_id: str
    client_secret: str

    def __repr__(self):
        return f"GitHubApp(client_id={self.client_id!r}, client_secret='[redacted]')"


@dataclass(frozen=True)
class Deployment:
    token: str
    origins: frozenset[str]
    hosts: frozenset[str]
    projects: Path
    public_origin: str | None = None
    github: GitHubApp | None = None
    owner_github_ids: frozenset[int] = frozenset()
    signup: str = "open"
    allowed_github_ids: frozenset[int] = frozenset()
    max_accounts: int = 100

    def __repr__(self):
        return (f"Deployment(origins={sorted(self.origins)!r}, hosts={sorted(self.hosts)!r}, projects={str(self.projects)!r}, "
                f"public_origin={self.public_origin!r}, github={self.github!r}, signup={self.signup!r}, token='[redacted]')")

    @property
    def github_redirect(self) -> str | None:
        return self.public_origin + "/api/auth/github/callback" if self.github and self.public_origin else None

    @classmethod
    def from_env(cls):
        token = os.environ.get("PARALLAX_ACCESS_TOKEN", "")
        if len(token) < 32 or len(token) > 512 or not token.isascii():
            raise ValueError("PARALLAX_ACCESS_TOKEN must contain 32 to 512 characters")
        if len(set(token)) < 12:
            # Guessing is throttled, but only a random key makes it hopeless.
            raise ValueError("PARALLAX_ACCESS_TOKEN looks repetitive; generate a random key, for example with openssl rand -base64 36")
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
        public_origin = os.environ.get("PARALLAX_PUBLIC_ORIGIN", "").strip().rstrip("/") or None
        if public_origin is None and len(origins) == 1:
            public_origin = next(iter(origins))
        if public_origin is not None and public_origin not in origins:
            raise ValueError("PARALLAX_PUBLIC_ORIGIN must be one of PARALLAX_STUDIO_ORIGINS")
        client_id = os.environ.get("PARALLAX_GITHUB_CLIENT_ID", "").strip()
        client_secret = os.environ.get("PARALLAX_GITHUB_CLIENT_SECRET", "").strip()
        github = None
        if client_id or client_secret:
            if not re.fullmatch(r"[A-Za-z0-9._-]{8,100}", client_id):
                raise ValueError("PARALLAX_GITHUB_CLIENT_ID is missing or invalid")
            if not 20 <= len(client_secret) <= 256 or not client_secret.isascii() or not client_secret.isprintable() or " " in client_secret:
                raise ValueError("PARALLAX_GITHUB_CLIENT_SECRET is missing or invalid")
            if public_origin is None:
                raise ValueError("GitHub sign-in requires PARALLAX_PUBLIC_ORIGIN when several Studio origins are configured")
            github = GitHubApp(client_id, client_secret)
        signup = os.environ.get("PARALLAX_SIGNUP", "open").strip().lower() or "open"
        if signup not in SIGNUP_POLICIES:
            raise ValueError("PARALLAX_SIGNUP must be open, allowlist, or closed")
        raw_limit = os.environ.get("PARALLAX_MAX_ACCOUNTS", "100").strip() or "100"
        if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= 100000:
            raise ValueError("PARALLAX_MAX_ACCOUNTS must be between 1 and 100000")
        return cls(token, frozenset(origins), frozenset(hosts), projects, public_origin, github,
                   _github_ids("PARALLAX_OWNER_GITHUB_IDS"), signup, _github_ids("PARALLAX_ALLOWED_GITHUB_IDS"), int(raw_limit))

    def check_workspace(self, value: str):
        if not Path(value).expanduser().resolve().is_relative_to(self.projects.resolve()):
            raise ValueError("Hosted workspaces must be inside PARALLAX_PROJECTS_ROOT")
