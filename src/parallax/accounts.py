"""Hosted accounts: sign-in, personal workspaces, and server-side sessions.

Only the hosted runtime (``python -m parallax.cloud``) uses this module; the
local loopback Studio keeps its single-user launch-token exchange. People sign
in through Supabase Auth (email and password, GitHub or Google) or, for
self-hosted deployments without Supabase, the built-in GitHub OAuth app. The
runtime makes every call to the identity provider itself. Normal sign-in uses
its token once; remote MCP consent temporarily holds it in memory (mcp_oauth.py).
The browser receives only an opaque session. Every account
receives one personal workspace. Configured operator accounts and the
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
OAUTH_FLOW_PATH = "/api/auth/oauth"
ACCOUNT_SESSION_SECONDS = 7 * 86400
OPERATOR_SESSION_SECONDS = 86400
FLOW_SECONDS = 600
SESSIONS_PER_ACCOUNT = 20
OAUTH_PROVIDERS = ("github", "google")
PASSWORD_MIN, PASSWORD_MAX = 10, 72  # Supabase hashes passwords with bcrypt, which reads at most 72 bytes.
SIGN_IN_ERRORS = ("unavailable", "denied", "expired", "failed", "closed", "not_invited", "capacity", "busy", "disabled",
                  "credentials", "unconfirmed", "weak_password", "invalid_email", "link_expired")
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,256}")
_BINDING = re.compile(r"([A-Za-z0-9_-]{43})\.([0-9]{10})\.([A-Za-z0-9_-]{43})")
_STATE = re.compile(r"[A-Za-z0-9_-]{43}")
_EMAIL = re.compile(r"[^@\s]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_TOKEN_HASH = re.compile(r"[A-Za-z0-9_-]{16,256}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_AVATAR_HOSTS = ("https://avatars.githubusercontent.com/", "https://lh3.googleusercontent.com/")
CONFIRM_TYPES = ("signup", "email", "email_change", "invite")

ACCOUNTS_TABLE = """CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, subject TEXT NOT NULL UNIQUE, provider TEXT,
    github_id INTEGER, email TEXT, login TEXT NOT NULL, name TEXT, avatar TEXT, workspace TEXT, created REAL NOT NULL,
    last_login REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);"""
SCHEMA = ACCOUNTS_TABLE + """
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
    hosted_execution INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, kind TEXT NOT NULL, account TEXT,
    workspace TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, credential TEXT);
CREATE INDEX IF NOT EXISTS session_accounts ON sessions(account, created);
"""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normal_email(value) -> str:
    """A lowercase, plausibly deliverable address, or a refusal. Supabase does the authoritative check."""
    email = value.strip().lower() if isinstance(value, str) else ""
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise SignInRefused("invalid_email")
    return email


class SignInRefused(Exception):
    """A sign-in ended without a session. ``code`` is one of SIGN_IN_ERRORS."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if code in SIGN_IN_ERRORS else "failed"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and the one workspace it may act within."""
    kind: str  # "account" (a person's sign-in), "operator" (access key or bearer), or "local"
    workspace: str
    hosted_execution: bool
    workspace_name: str = ""
    account: dict | None = field(default=None, compare=False)
    session: str | None = None  # SHA-256 of the session cookie, when one exists

    def public(self) -> dict:
        return {"ok": True, "mode": "local" if self.kind == "local" else "hosted", "auth": self.kind,
                "account": {key: self.account.get(key) for key in ("login", "name", "avatar_url", "email", "provider")} if self.account else None,
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
        self._providers: tuple[float, list[str]] | None = None
        with store.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
            if columns and "subject" not in columns:
                # Accounts from the GitHub-only build carry over under a provider-neutral subject.
                db.executescript("ALTER TABLE accounts RENAME TO accounts_github_only;" + ACCOUNTS_TABLE + """
                    INSERT INTO accounts(id,subject,provider,github_id,email,login,name,avatar,workspace,created,last_login,disabled)
                    SELECT id,'github:'||github_id,'github',github_id,NULL,login,name,avatar,workspace,created,last_login,disabled
                    FROM accounts_github_only;
                    DROP TABLE accounts_github_only;""")
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO workspaces(id,kind,name,hosted_execution,created) VALUES(?,?,?,?,?)",
                       (OWNER_WORKSPACE, "operator", "Operator workspace", 1, time.time()))

    # Sessions -----------------------------------------------------------------
    def create_session(self, kind: str, workspace: str, account: str | None = None) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        lifetime = OPERATOR_SESSION_SECONDS if kind == "operator" else ACCOUNT_SESSION_SECONDS
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
                w.hosted_execution,a.subject,a.provider,a.github_id,a.email,a.login,a.name,a.avatar,a.disabled FROM sessions s
                JOIN workspaces w ON w.id=s.workspace LEFT JOIN accounts a ON a.id=s.account WHERE s.hash=?""",
                             (digest(token),)).fetchone()
        if row is None or row["expires"] < time.time():
            return None
        hosted = bool(row["hosted_execution"]) and row["workspace"] == OWNER_WORKSPACE
        if row["kind"] == "operator":
            valid = row["workspace"] == OWNER_WORKSPACE and hmac.compare_digest(row["credential"] or "", self._credential())
            return operator_principal(row["hash"]) if valid else None
        # "github" is the session kind written by the GitHub-only build.
        if row["kind"] not in ("account", "github") or row["subject"] is None or row["disabled"]:
            return None
        if row["workspace"] == OWNER_WORKSPACE and not self._is_owner(row["email"], row["github_id"]):
            return None  # Removed from the operator list: the session no longer grants that workspace.
        account = {"id": row["account"], "subject": row["subject"], "provider": row["provider"], "github_id": row["github_id"],
                   "email": row["email"], "login": row["login"], "name": row["name"], "avatar_url": row["avatar"]}
        return Principal("account", row["workspace"], hosted, row["workspace_name"], account, row["hash"])

    def _is_owner(self, email: str | None, github_id: int | None) -> bool:
        return bool(email and email in self.deployment.owner_emails) or bool(github_id and github_id in self.deployment.owner_github_ids)

    def _credential(self) -> str:
        return hmac.new(b"parallax-operator-session", self.deployment.token.encode(), "sha256").hexdigest()

    def end_session(self, session_hash: str | None):
        if session_hash:
            with self.store.connect() as db:
                db.execute("DELETE FROM sessions WHERE hash=?", (session_hash,))

    def operator_failure(self) -> bool:
        """Record a rejected access key. Returns False once failures exceed the limit.

        Only failures are counted, so other clients' guesses never lock out a valid key.
        """
        with self.store.connect() as db:
            return allow_rate(db, "operator-sign-in-failure", 20, 60)

    # Stateless OAuth flows ------------------------------------------------------
    # Pending flows hold no server state: the flow cookie carries a nonce and expiry sealed with a key derived
    # from the access key, and the state and PKCE verifier are recomputed from it. Anonymous traffic therefore
    # cannot fill storage or displace anyone's sign-in, and the cookie itself reveals neither value.
    def _flow_value(self, purpose: str, nonce: str, expires: int) -> str:
        key = hmac.new(self.deployment.token.encode(), b"parallax-oauth-flow-v1", hashlib.sha256).digest()
        mac = hmac.new(key, f"{purpose}|{nonce}|{expires}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()

    def _new_flow(self) -> tuple[str, int, str, str]:
        nonce, expires = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode(), int(time.time()) + FLOW_SECONDS
        verifier = self._flow_value("verifier", nonce, expires)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return nonce, expires, challenge, f"{nonce}.{expires}.{self._flow_value('binding', nonce, expires)}"

    def _open_flow(self, binding: str) -> tuple[str, int]:
        """The nonce and expiry of a flow this browser started and that has not expired, or a refusal."""
        sealed = _BINDING.fullmatch(binding or "")
        if not sealed:
            raise SignInRefused("expired")
        nonce, expires, tag = sealed.group(1), int(sealed.group(2)), sealed.group(3)
        if not hmac.compare_digest(tag, self._flow_value("binding", nonce, expires)) or not time.time() <= expires <= time.time() + FLOW_SECONDS:
            raise SignInRefused("expired")
        return nonce, expires

    # Built-in GitHub OAuth app (self-hosted deployments without Supabase) -----
    def begin_github(self) -> tuple[str, str]:
        app, redirect = self.deployment.github, self.deployment.github_redirect
        if not app or not redirect:
            raise SignInRefused("unavailable")
        nonce, expires, challenge, binding = self._new_flow()
        query = urlencode({"client_id": app.client_id, "redirect_uri": redirect, "state": self._flow_value("state", nonce, expires),
                           "code_challenge": challenge, "code_challenge_method": "S256", "allow_signup": "true"})
        return "https://github.com/login/oauth/authorize?" + query, binding

    async def finish_github(self, *, state: str, code: str, binding: str, error: str | None = None) -> tuple[str, int]:
        if not self.deployment.github or not self.deployment.github_redirect:
            raise SignInRefused("unavailable")
        # A flow completes only in the browser that started it (its cookie), for its own state, before it expires.
        nonce, expires = self._open_flow(binding)
        if not _STATE.fullmatch(state or "") or not hmac.compare_digest(state, self._flow_value("state", nonce, expires)):
            raise SignInRefused("expired")
        if error:
            raise SignInRefused("denied")
        if not code or not _CODE.fullmatch(code):
            raise SignInRefused("failed")
        profile = await self._github_profile(code, self._flow_value("verifier", nonce, expires))
        account, workspace = self._admit(profile)
        return self.create_session("account", workspace, account)

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
        return {"subject": f"github:{identifier}", "provider": "github", "github_id": identifier, "email": None,
                "login": login, "name": name[:200] if name else None, "avatar": _avatar(user.get("avatar_url"))}

    # Supabase Auth -------------------------------------------------------------
    async def _supabase(self, method: str, path: str, *, body: dict | None = None, query: dict | None = None,
                        jwt: str | None = None, admin: bool = False) -> tuple[int, dict]:
        project = self.deployment.supabase
        if project is None:
            raise SignInRefused("unavailable")
        key = project.secret_key if admin else project.publishable_key
        if not key:
            raise SignInRefused("unavailable")
        headers = {"apikey": key, "X-Supabase-Api-Version": "2024-01-01", "Accept": "application/json"}
        # Legacy anon and service-role keys are JWTs and also travel as the bearer; new sb_ keys do not.
        bearer = jwt or (key if key.count(".") == 2 else None)
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False, transport=self.transport,
                                         headers={"User-Agent": "Parallax"}) as client:
                response = await client.request(method, f"{project.url}/auth/v1{path}", params=query, json=body, headers=headers)
                data = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise SignInRefused("failed") from None
        return response.status_code, data if isinstance(data, dict) else {}

    @staticmethod
    def _supabase_refusal(data: dict, default: str = "failed") -> SignInRefused:
        code = str(data.get("error_code") or data.get("code") or data.get("error") or "")
        if code in ("email_not_confirmed",):
            return SignInRefused("unconfirmed")
        if code in ("invalid_credentials", "invalid_grant"):
            return SignInRefused("credentials")
        if code in ("weak_password",):
            return SignInRefused("weak_password")
        if code in ("email_address_invalid", "validation_failed"):
            return SignInRefused("invalid_email")
        if code.startswith("over_") or code == "429":
            return SignInRefused("busy")
        if code in ("otp_expired", "flow_state_expired", "flow_state_not_found", "bad_code_verifier"):
            return SignInRefused("link_expired")
        if code in ("signup_disabled", "email_provider_disabled", "provider_disabled"):
            return SignInRefused("unavailable")
        if code in ("user_banned",):
            return SignInRefused("disabled")
        return SignInRefused(default)

    async def providers(self) -> list[str]:
        """Sign-in methods the Supabase project has turned on, read from its public settings and cached briefly."""
        if self.deployment.supabase is None:
            return ["github"] if self.deployment.github_redirect else []
        if self._providers and self._providers[0] > time.time():
            return self._providers[1]
        try:
            status, settings = await self._supabase("GET", "/settings")
        except SignInRefused:
            status, settings = 0, {}
        external = settings.get("external") if status == 200 and isinstance(settings.get("external"), dict) else None
        found = [name for name in ("email", *OAUTH_PROVIDERS) if external and external.get(name) is True] if external else ["email"]
        self._providers = (time.time() + (300 if external else 30), found)
        return found

    def _new_account_allowed(self, db, email: str | None, github_id: int | None) -> None:
        policy = self.deployment
        if policy.signup == "closed":
            raise SignInRefused("closed")
        if policy.signup == "allowlist" and not ((email and email in policy.allowed_emails)
                                                 or (github_id and github_id in policy.allowed_github_ids)):
            raise SignInRefused("not_invited")
        if db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] >= policy.max_accounts:
            raise SignInRefused("capacity")

    async def sign_up(self, email, password, name=None) -> None:
        """Ask Supabase to create the user and send a confirmation link. The reply never reveals whether the email exists."""
        email = normal_email(email)
        if not isinstance(password, str) or not PASSWORD_MIN <= len(password.encode()) <= PASSWORD_MAX:
            raise SignInRefused("weak_password")
        with self.store.connect() as db:
            # The policy answer never depends on whether the email already has an account; existing accounts log in.
            if not self._is_owner(email, None):
                self._new_account_allowed(db, email, None)
            if not allow_rate(db, "signup:" + digest(email), 5, 3600) or not allow_rate(db, "signup", 120, 3600):
                raise SignInRefused("busy")
        data = {"name": name.strip()[:200]} if isinstance(name, str) and name.strip() else {}
        status, reply = await self._supabase("POST", "/signup", body={"email": email, "password": password, "data": data},
                                             query={"redirect_to": self.deployment.public_origin})
        if status >= 400 and str(reply.get("error_code")) not in ("user_already_exists", "email_exists"):
            raise self._supabase_refusal(reply)

    async def confirm(self, token_hash, kind) -> tuple[str, int]:
        """The emailed confirmation link: verify it with Supabase, then sign the person in on whatever device opened it."""
        if kind not in CONFIRM_TYPES or not isinstance(token_hash, str) or not _TOKEN_HASH.fullmatch(token_hash):
            raise SignInRefused("link_expired")
        status, session = await self._supabase("POST", "/verify", body={"type": kind, "token_hash": token_hash})
        if status >= 400:
            raise self._supabase_refusal(session, "link_expired")
        return await self._sign_in(session)

    async def log_in(self, email, password) -> tuple[str, int]:
        return await self._sign_in(await self.password_exchange(email, password))

    async def password_exchange(self, email, password) -> dict:
        """Exchange credentials without retaining the provider session. The caller must revoke it."""
        email = normal_email(email)
        if not isinstance(password, str) or not 1 <= len(password) <= 1024:
            raise SignInRefused("credentials")
        bucket = "login-failure:" + digest(email)
        with self.store.connect() as db:
            failures = db.execute("SELECT COUNT(*) FROM rate_events WHERE bucket=? AND created>?", (bucket, time.time() - 900)).fetchone()[0]
        if failures >= 10:
            raise SignInRefused("busy")
        status, session = await self._supabase("POST", "/token", body={"email": email, "password": password},
                                               query={"grant_type": "password"})
        if status >= 400:
            refusal = self._supabase_refusal(session, "credentials")
            if refusal.code == "credentials":
                with self.store.connect() as db:
                    allow_rate(db, bucket, 1000, 900)  # Only failed attempts are recorded; the limit lifts after 15 minutes.
            raise refusal
        return session

    async def forgot_password(self, email) -> None:
        """Send a reset link if the account exists. The reply is the same either way."""
        email = normal_email(email)
        with self.store.connect() as db:
            if not allow_rate(db, "recover:" + digest(email), 3, 3600) or not allow_rate(db, "recover", 120, 3600):
                raise SignInRefused("busy")
        status, reply = await self._supabase("POST", "/recover", body={"email": email},
                                             query={"redirect_to": self.deployment.public_origin + "/reset"})
        if status >= 400 and self._supabase_refusal(reply).code == "busy":
            raise SignInRefused("busy")

    async def reset_password(self, token_hash, password) -> tuple[str, int]:
        if not isinstance(token_hash, str) or not _TOKEN_HASH.fullmatch(token_hash):
            raise SignInRefused("link_expired")
        if not isinstance(password, str) or not PASSWORD_MIN <= len(password.encode()) <= PASSWORD_MAX:
            raise SignInRefused("weak_password")
        status, session = await self._supabase("POST", "/verify", body={"type": "recovery", "token_hash": token_hash})
        if status >= 400:
            raise self._supabase_refusal(session, "link_expired")
        token = session.get("access_token")
        if not isinstance(token, str) or not token:
            raise SignInRefused("link_expired")
        status, reply = await self._supabase("PUT", "/user", body={"password": password}, jwt=token)
        if status >= 400:
            raise self._supabase_refusal(reply, "weak_password")
        return await self._sign_in(session)

    def begin_oauth(self, provider: str, *, redirect: str | None = None) -> tuple[str, str]:
        if self.deployment.supabase is None or not self.deployment.oauth_redirect:
            raise SignInRefused("unavailable")
        if provider not in OAUTH_PROVIDERS:
            raise SignInRefused("unavailable")
        _, _, challenge, binding = self._new_flow()
        query = urlencode({"provider": provider, "redirect_to": redirect or self.deployment.oauth_redirect,
                           "code_challenge": challenge, "code_challenge_method": "s256"})
        return f"{self.deployment.supabase.url}/auth/v1/authorize?{query}", binding

    async def finish_oauth(self, *, code: str, binding: str, error: str | None = None) -> tuple[str, int]:
        return await self._sign_in(await self.oauth_exchange(code=code, binding=binding, error=error))

    async def oauth_exchange(self, *, code: str, binding: str, error: str | None = None) -> dict:
        if self.deployment.supabase is None:
            raise SignInRefused("unavailable")
        # Supabase issued the code against this browser's challenge; another browser's verifier cannot redeem it.
        nonce, expires = self._open_flow(binding)
        if error:
            raise SignInRefused("denied")
        if not code or not _CODE.fullmatch(code):
            raise SignInRefused("failed")
        status, session = await self._supabase("POST", "/token", query={"grant_type": "pkce"},
                                               body={"auth_code": code, "code_verifier": self._flow_value("verifier", nonce, expires)})
        if status >= 400:
            raise self._supabase_refusal(session, "expired")
        return session

    async def provider_identity(self, session: dict) -> tuple[str, dict]:
        token = session.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            raise SignInRefused("failed")
        status, user = await self._supabase("GET", "/user", jwt=token)
        if status != 200:
            raise SignInRefused("failed")
        return token, self._supabase_profile(user)

    async def revoke_provider_session(self, token: str):
        try:
            await self._supabase("POST", "/logout", query={"scope": "local"}, jwt=token)
        except SignInRefused:
            pass

    async def _sign_in(self, session: dict) -> tuple[str, int]:
        """Read the user with the Supabase token, revoke it, and open a Parallax session."""
        token = session.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            raise SignInRefused("failed")
        try:
            status, user = await self._supabase("GET", "/user", jwt=token)
            if status != 200:
                raise SignInRefused("failed")
            profile = self._supabase_profile(user)
        finally:
            try:
                await self._supabase("POST", "/logout", query={"scope": "local"}, jwt=token)
            except SignInRefused:
                pass  # The token expires on its own; Parallax never stored it.
        account, workspace = self._admit(profile)
        return self.create_session("account", workspace, account)

    @staticmethod
    def _supabase_profile(user: dict) -> dict:
        identifier = user.get("id")
        if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
            raise SignInRefused("failed")
        email = user.get("email")
        if not isinstance(email, str) or not email:
            raise SignInRefused("failed")
        email = normal_email(email)
        if not (user.get("email_confirmed_at") or user.get("confirmed_at")):
            raise SignInRefused("unconfirmed")
        if user.get("banned_until"):
            raise SignInRefused("disabled")
        meta = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
        app = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
        github_id = None
        for identity in user.get("identities") or []:
            data = identity.get("identity_data") if isinstance(identity, dict) and isinstance(identity.get("identity_data"), dict) else {}
            if isinstance(identity, dict) and identity.get("provider") == "github":
                candidate = str(data.get("provider_id") or data.get("sub") or identity.get("id") or "")
                github_id = int(candidate) if candidate.isdigit() and 0 < len(candidate) <= 20 else None
        handle = meta.get("user_name") or meta.get("preferred_username")
        login = handle if isinstance(handle, str) and _LOGIN.fullmatch(handle) else email.split("@", 1)[0][:39]
        name = next((meta[key] for key in ("full_name", "name") if isinstance(meta.get(key), str) and meta[key].strip()), None)
        return {"subject": f"supabase:{identifier}", "provider": str(app.get("provider") or "email")[:20], "github_id": github_id,
                "email": email, "login": login or "member", "name": name.strip()[:200] if name else None,
                "avatar": _avatar(meta.get("avatar_url") or meta.get("picture"))}

    def _admit(self, profile: dict) -> tuple[str, str]:
        now = time.time()
        operator = self._is_owner(profile.get("email"), profile.get("github_id"))
        with self.store.connect() as db:
            # The first statement writes, so concurrent sign-ins serialize on SQLite's write lock.
            db.execute("UPDATE accounts SET login=?,name=?,avatar=?,email=COALESCE(?,email),github_id=COALESCE(?,github_id),last_login=? WHERE subject=?",
                       (profile["login"], profile["name"], profile["avatar"], profile.get("email"), profile.get("github_id"), now,
                        profile["subject"]))
            row = db.execute("SELECT id,workspace,disabled FROM accounts WHERE subject=?", (profile["subject"],)).fetchone()
            if row is not None and row["disabled"]:
                raise SignInRefused("disabled")
            if row is None:
                if not operator:
                    self._new_account_allowed(db, profile.get("email"), profile.get("github_id"))
                    if not allow_rate(db, "account-created", 30, 3600):
                        raise SignInRefused("busy")
                account, workspace = str(uuid.uuid4()), None
                db.execute("""INSERT INTO accounts(id,subject,provider,github_id,email,login,name,avatar,workspace,created,last_login,disabled)
                              VALUES(?,?,?,?,?,?,?,?,NULL,?,?,0)""",
                           (account, profile["subject"], profile.get("provider"), profile.get("github_id"), profile.get("email"),
                            profile["login"], profile["name"], profile["avatar"], now, now))
            else:
                account, workspace = row["id"], row["workspace"]
            if operator:
                return account, OWNER_WORKSPACE
            if workspace is None or db.execute("SELECT 1 FROM workspaces WHERE id=? AND kind='personal'", (workspace,)).fetchone() is None:
                workspace = str(uuid.uuid4())
                db.execute("INSERT INTO workspaces(id,kind,name,hosted_execution,created) VALUES(?,?,?,0,?)",
                           (workspace, "personal", profile["name"] or profile["login"], now))
                db.execute("UPDATE accounts SET workspace=? WHERE id=?", (workspace, account))
            return account, workspace

    # Account lifecycle -------------------------------------------------------
    async def delete_account(self, principal: Principal, hub, confirm: str = "") -> None:
        if principal.kind != "account" or not principal.account:
            raise PermissionError("Only a signed-in account can delete itself")
        expected = {value.casefold() for value in (principal.account.get("login"), principal.account.get("email")) if value}
        if confirm.strip().casefold() not in expected:
            raise PermissionError("The confirmation does not match the signed-in account. Reload and try again.")
        if principal.workspace == OWNER_WORKSPACE:
            raise PermissionError("Operator accounts are managed by the deployment operator")
        hub.purge_workspace(principal.workspace)
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE account=?", (principal.account["id"],))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_grants'").fetchone():
                db.execute("DELETE FROM mcp_grants WHERE account=?", (principal.account["id"],))
            db.execute("DELETE FROM rate_events WHERE bucket=?", ("mcp-consent:" + principal.account["id"],))
            db.execute("DELETE FROM workspaces WHERE id=? AND kind='personal'", (principal.workspace,))
            db.execute("DELETE FROM accounts WHERE id=?", (principal.account["id"],))
        subject = principal.account.get("subject") or ""
        project = self.deployment.supabase
        if subject.startswith("supabase:") and project and project.secret_key:
            # Remove the identity too, so the email can sign up again from scratch.
            try:
                await self._supabase("DELETE", f"/admin/users/{subject.split(':', 1)[1]}", admin=True)
            except SignInRefused:
                pass  # Parallax data is already gone; the operator can remove the identity in Supabase.


def _avatar(value) -> str | None:
    return value if isinstance(value, str) and len(value) <= 512 and value.startswith(_AVATAR_HOSTS) else None
