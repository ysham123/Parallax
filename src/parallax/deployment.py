"""Explicit opt-in configuration for the hosted runtime."""
from __future__ import annotations
from dataclasses import dataclass
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

# Values the hosted runtime reads once and then removes from its environment,
# so provider CLIs, project checks, and Git never inherit them.
HOSTED_SECRETS = ("PARALLAX_ACCESS_TOKEN", "PARALLAX_GITHUB_CLIENT_SECRET", "PARALLAX_SUPABASE_PUBLISHABLE_KEY",
                  "PARALLAX_SUPABASE_SECRET_KEY")
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


_EMAIL = re.compile(r"[^@\s]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _emails(name: str) -> frozenset[str]:
    values = set()
    for value in os.environ.get(name, "").split(","):
        value = value.strip().lower()
        if not value:
            continue
        if len(value) > 254 or not _EMAIL.fullmatch(value):
            raise ValueError(f"{name} must list email addresses")
        values.add(value)
    return frozenset(values)


def _api_key(value: str) -> bool:
    return 20 <= len(value) <= 1024 and value.isascii() and value.isprintable() and " " not in value


@dataclass(frozen=True)
class SupabaseProject:
    """Supabase Auth, called only by the runtime. Keys never reach the browser."""
    url: str
    publishable_key: str
    secret_key: str | None = None

    def __repr__(self):
        return f"SupabaseProject(url={self.url!r}, publishable_key='[redacted]', secret_key={'[redacted]' if self.secret_key else None})"


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
    supabase: SupabaseProject | None = None
    owner_emails: frozenset[str] = frozenset()
    allowed_emails: frozenset[str] = frozenset()
    remote_mcp: bool = False
    openai_challenge: str = ""

    def __repr__(self):
        return (f"Deployment(origins={sorted(self.origins)!r}, hosts={sorted(self.hosts)!r}, projects={str(self.projects)!r}, "
                f"public_origin={self.public_origin!r}, github={self.github!r}, supabase={self.supabase!r}, signup={self.signup!r}, "
                f"token='[redacted]')")

    @property
    def github_redirect(self) -> str | None:
        return self.public_origin + "/api/auth/github/callback" if self.github and self.public_origin else None

    @property
    def oauth_redirect(self) -> str | None:
        """Where Supabase returns GitHub and Google sign-ins. Add it to the project's redirect URLs."""
        return self.public_origin + "/api/auth/oauth/callback" if self.supabase and self.public_origin else None

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
        supabase = None
        supabase_url = os.environ.get("PARALLAX_SUPABASE_URL", "").strip().rstrip("/")
        publishable = os.environ.get("PARALLAX_SUPABASE_PUBLISHABLE_KEY", "").strip()
        secret = os.environ.get("PARALLAX_SUPABASE_SECRET_KEY", "").strip()
        if supabase_url or publishable or secret:
            parsed = urlsplit(supabase_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment):
                raise ValueError("PARALLAX_SUPABASE_URL must be the project's HTTPS URL, such as https://abcd.supabase.co")
            if not _api_key(publishable):
                raise ValueError("PARALLAX_SUPABASE_PUBLISHABLE_KEY is missing or invalid")
            if secret and not _api_key(secret):
                raise ValueError("PARALLAX_SUPABASE_SECRET_KEY is invalid")
            if public_origin is None:
                raise ValueError("Supabase sign-in requires PARALLAX_PUBLIC_ORIGIN when several Studio origins are configured")
            supabase = SupabaseProject(supabase_url, publishable, secret or None)
        signup = os.environ.get("PARALLAX_SIGNUP", "open").strip().lower() or "open"
        if signup not in SIGNUP_POLICIES:
            raise ValueError("PARALLAX_SIGNUP must be open, allowlist, or closed")
        raw_limit = os.environ.get("PARALLAX_MAX_ACCOUNTS", "100").strip() or "100"
        if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= 100000:
            raise ValueError("PARALLAX_MAX_ACCOUNTS must be between 1 and 100000")
        mcp = os.environ.get("PARALLAX_REMOTE_MCP", "off").lower()
        if mcp not in {"on", "off"} or (mcp == "on" and (not supabase or not public_origin)):
            raise ValueError("PARALLAX_REMOTE_MCP must be off, or on with Supabase and a public origin configured")
        challenge = os.environ.get("PARALLAX_OPENAI_CHALLENGE", "")
        if challenge and not re.fullmatch(r"[A-Za-z0-9_.=-]{1,1024}", challenge):
            raise ValueError("PARALLAX_OPENAI_CHALLENGE must be the domain verification token")
        return cls(token, frozenset(origins), frozenset(hosts), projects, public_origin, github,
                   _github_ids("PARALLAX_OWNER_GITHUB_IDS"), signup, _github_ids("PARALLAX_ALLOWED_GITHUB_IDS"), int(raw_limit),
                   supabase, _emails("PARALLAX_OWNER_EMAILS"), _emails("PARALLAX_ALLOWED_EMAILS"), mcp == "on", challenge)

    def check_workspace(self, value: str):
        if not Path(value).expanduser().resolve().is_relative_to(self.projects.resolve()):
            raise ValueError("Hosted workspaces must be inside PARALLAX_PROJECTS_ROOT")
