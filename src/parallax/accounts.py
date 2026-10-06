"""Hosted accounts: GitHub sign-in, personal workspaces, and server-side sessions.

Only the hosted runtime (``python -m parallax.cloud``) uses this module; the
local loopback Studio keeps its single-user launch-token exchange. Every GitHub
account receives one personal workspace. Configured operator accounts and the
deployment access key open the operator workspace, which is the only workspace
allowed to use the hosted runtime's own execution engine.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode
import httpx
from .store import allow_rate

OWNER_WORKSPACE = "owner"
SESSION_COOKIE = "parallax_session"
FLOW_COOKIE = "parallax_oauth"
FLOW_COOKIE_PATH = "/api/auth/github"
GITHUB_SESSION_SECONDS = 7 * 86400
OPERATOR_SESSION_SECONDS = 86400
FLOW_SECONDS = 600
SESSIONS_PER_ACCOUNT = 20
SIGN_IN_ERRORS = ("unavailable", "denied", "expired", "failed", "closed", "not_invited", "capacity", "busy", "disabled")
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,256}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, github_id INTEGER NOT NULL UNIQUE,
    login TEXT NOT NULL, name TEXT, avatar TEXT, workspace TEXT, created REAL NOT NULL,
    last_login REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
    hosted_execution INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, kind TEXT NOT NULL, account TEXT,
    workspace TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, credential TEXT);
CREATE INDEX IF NOT EXISTS session_accounts ON sessions(account, created);
CREATE TABLE IF NOT EXISTS auth_flows(state TEXT PRIMARY KEY, binding TEXT NOT NULL,
    verifier TEXT NOT NULL, expires REAL NOT NULL);
"""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SignInRefused(Exception):
    """A sign-in ended without a session. ``code`` is one of SIGN_IN_ERRORS."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if code in SIGN_IN_ERRORS else "failed"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and the one workspace it may act within."""
    kind: str  # "github", "operator" (access key or bearer), or "local"
    workspace: str
    hosted_execution: bool
    workspace_name: str = ""
    account: dict | None = field(default=None, compare=False)
    session: str | None = None  # SHA-256 of the session cookie, when one exists

    def public(self) -> dict:
        return {"ok": True, "mode": "local" if self.kind == "local" else "hosted", "auth": self.kind,
                "account": {key: self.account[key] for key in ("login", "name", "avatar_url")} if self.account else None,
                "workspace": {"id": self.workspace, "name": self.workspace_name,
                              "kind": "operator" if self.workspace == OWNER_WORKSPACE else "personal",
                              "hosted_execution": self.hosted_execution}}


def operator_principal(session: str | None = None) -> Principal:
    return Principal("operator", OWNER_WORKSPACE, True, "Operator workspace", None, session)


class Accounts:
    def __init__(self, store, deployment, *, transport: httpx.AsyncBaseTransport | None = None):
        self.store = store
        self.deployment = deployment
        self.transport = transport
        with store.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO workspaces(id,kind,name,hosted_execution,created) VALUES(?,?,?,?,?)",
                       (OWNER_WORKSPACE, "operator", "Operator workspace", 1, time.time()))

    # Sessions -----------------------------------------------------------------
    def create_session(self, kind: str, workspace: str, account: str | None = None) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        lifetime = GITHUB_SESSION_SECONDS if kind == "github" else OPERATOR_SESSION_SECONDS
        now = time.time()
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            if account:
                db.execute("DELETE FROM sessions WHERE hash IN (SELECT hash FROM sessions WHERE account=? ORDER BY created DESC LIMIT -1 OFFSET ?)",
                           (account, SESSIONS_PER_ACCOUNT - 1))
            # Operator sessions record which access key opened them, so rotating the key ends them.
            db.execute("INSERT INTO sessions(hash,kind,account,workspace,created,expires,credential) VALUES(?,?,?,?,?,?,?)",
                       (digest(token), kind, account, workspace, now, now + lifetime, self._credential() if kind == "operator" else None))
        return token, lifetime

    def principal(self, token: str | None) -> Principal | None:
        if not token or len(token) > 128:
            return None
        with self.store.connect() as db:
            row = db.execute("""SELECT s.hash,s.kind,s.account,s.workspace,s.expires,s.credential,w.name AS workspace_name,
                w.hosted_execution,a.github_id,a.login,a.name,a.avatar,a.disabled FROM sessions s
                JOIN workspaces w ON w.id=s.workspace LEFT JOIN accounts a ON a.id=s.account WHERE s.hash=?""",
                             (digest(token),)).fetchone()
        if row is None or row["expires"] < time.time():
            return None
        hosted = bool(row["hosted_execution"]) and row["workspace"] == OWNER_WORKSPACE
        if row["kind"] == "operator":
            valid = row["workspace"] == OWNER_WORKSPACE and hmac.compare_digest(row["credential"] or "", self._credential())
            return operator_principal(row["hash"]) if valid else None
        if row["kind"] != "github" or row["github_id"] is None or row["disabled"]:
            return None
        if row["workspace"] == OWNER_WORKSPACE and row["github_id"] not in self.deployment.owner_github_ids:
            return None  # Removed from the operator list: the session no longer grants that workspace.
        account = {"id": row["account"], "github_id": row["github_id"], "login": row["login"],
                   "name": row["name"], "avatar_url": row["avatar"]}
        return Principal("github", row["workspace"], hosted, row["workspace_name"], account, row["hash"])

    def _credential(self) -> str:
        return hmac.new(b"parallax-operator-session", self.deployment.token.encode(), "sha256").hexdigest()

    def end_session(self, session_hash: str | None):
        if session_hash:
            with self.store.connect() as db:
                db.execute("DELETE FROM sessions WHERE hash=?", (session_hash,))

    def operator_sign_in_allowed(self) -> bool:
        with self.store.connect() as db:
            return allow_rate(db, "operator-sign-in", 20, 60)

    # GitHub OAuth web flow with PKCE and a browser-bound state -------------
    def begin_github(self) -> tuple[str, str]:
        app, redirect = self.deployment.github, self.deployment.github_redirect
        if not app or not redirect:
            raise SignInRefused("unavailable")
        state, binding, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        now = time.time()
        with self.store.connect() as db:
            db.execute("DELETE FROM auth_flows WHERE expires<?", (now,))
            if not allow_rate(db, "github-flow", 600, 600):
                raise SignInRefused("busy")
        with self.store.connect() as db:
            db.execute("INSERT INTO auth_flows(state,binding,verifier,expires) VALUES(?,?,?,?)",
                       (digest(state), digest(binding), verifier, now + FLOW_SECONDS))
        query = urlencode({"client_id": app.client_id, "redirect_uri": redirect, "state": state,
                           "code_challenge": challenge, "code_challenge_method": "S256", "allow_signup": "true"})
        return "https://github.com/login/oauth/authorize?" + query, binding

    async def finish_github(self, *, state: str, code: str, binding: str, error: str | None = None) -> tuple[str, int]:
        if not self.deployment.github or not self.deployment.github_redirect:
            raise SignInRefused("unavailable")
        if not state or not binding or len(state) > 256 or len(binding) > 256:
            raise SignInRefused("expired")
        # A flow is consumed only by the browser that started it, and only once.
        with self.store.connect() as db:
            flow = db.execute("DELETE FROM auth_flows WHERE state=? AND binding=? RETURNING verifier,expires",
                              (digest(state), digest(binding))).fetchone()
        if flow is None or flow["expires"] < time.time():
            raise SignInRefused("expired")
        if error:
            raise SignInRefused("denied")
        if not code or not _CODE.fullmatch(code):
            raise SignInRefused("failed")
        profile = await self._github_profile(code, flow["verifier"])
        account, workspace = self._admit(profile)
        return self.create_session("github", workspace, account)

    async def _github_profile(self, code: str, verifier: str) -> dict:
        app = self.deployment.github
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False, transport=self.transport,
                                         headers={"User-Agent": "Parallax"}) as client:
                response = await client.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"},
                                             data={"client_id": app.client_id, "client_secret": app.client_secret, "code": code,
                                                   "redirect_uri": self.deployment.github_redirect, "code_verifier": verifier})
                body = response.json() if response.status_code == 200 else None
                token = body.get("access_token") if isinstance(body, dict) else None
                if not isinstance(token, str) or not 1 <= len(token) <= 1024:
                    raise SignInRefused("failed")
                response = await client.get("https://api.github.com/user", headers={"Authorization": "Bearer " + token,
                                                                                    "Accept": "application/vnd.github+json"})
                user = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            raise SignInRefused("failed") from None
        # The GitHub token is used once to read the public profile and is never stored.
        if not isinstance(user, dict) or user.get("type") != "User":
            raise SignInRefused("failed")
        identifier, login = user.get("id"), user.get("login")
        if type(identifier) is not int or identifier <= 0 or not isinstance(login, str) or not _LOGIN.fullmatch(login):
            raise SignInRefused("failed")
        name = user.get("name") if isinstance(user.get("name"), str) else None
        avatar = user.get("avatar_url")
        if not isinstance(avatar, str) or not avatar.startswith("https://avatars.githubusercontent.com/") or len(avatar) > 512:
            avatar = None
        return {"id": identifier, "login": login, "name": name[:200] if name else None, "avatar": avatar}

    def _admit(self, profile: dict) -> tuple[str, str]:
        policy, now = self.deployment, time.time()
        operator = profile["id"] in policy.owner_github_ids
        with self.store.connect() as db:
            # The first statement writes, so concurrent sign-ins serialize on SQLite's write lock.
            db.execute("UPDATE accounts SET login=?,name=?,avatar=?,last_login=? WHERE github_id=?",
                       (profile["login"], profile["name"], profile["avatar"], now, profile["id"]))
            row = db.execute("SELECT id,workspace,disabled FROM accounts WHERE github_id=?", (profile["id"],)).fetchone()
            if row is not None and row["disabled"]:
                raise SignInRefused("disabled")
            if row is None:
                if not operator:
                    if policy.signup == "closed":
                        raise SignInRefused("closed")
                    if policy.signup == "allowlist" and profile["id"] not in policy.allowed_github_ids:
                        raise SignInRefused("not_invited")
                    if db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] >= policy.max_accounts:
                        raise SignInRefused("capacity")
                    if not allow_rate(db, "account-created", 30, 3600):
                        raise SignInRefused("busy")
                account, workspace = str(uuid.uuid4()), None
                db.execute("INSERT INTO accounts(id,github_id,login,name,avatar,workspace,created,last_login,disabled) VALUES(?,?,?,?,?,NULL,?,?,0)",
                           (account, profile["id"], profile["login"], profile["name"], profile["avatar"], now, now))
            else:
                account, workspace = row["id"], row["workspace"]
            if operator:
                return account, OWNER_WORKSPACE
            if workspace is None or db.execute("SELECT 1 FROM workspaces WHERE id=? AND kind='personal'", (workspace,)).fetchone() is None:
                workspace = str(uuid.uuid4())
                db.execute("INSERT INTO workspaces(id,kind,name,hosted_execution,created) VALUES(?,?,?,0,?)",
                           (workspace, "personal", profile["login"], now))
                db.execute("UPDATE accounts SET workspace=? WHERE id=?", (workspace, account))
            return account, workspace

    # Account lifecycle -------------------------------------------------------
    def delete_account(self, principal: Principal, hub) -> None:
        if principal.kind != "github" or not principal.account:
            raise PermissionError("Only a GitHub account can delete itself")
        if principal.workspace == OWNER_WORKSPACE:
            raise PermissionError("Operator accounts are managed by the deployment operator")
        hub.purge_workspace(principal.workspace)
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE account=?", (principal.account["id"],))
            db.execute("DELETE FROM workspaces WHERE id=? AND kind='personal'", (principal.workspace,))
            db.execute("DELETE FROM accounts WHERE id=?", (principal.account["id"],))
