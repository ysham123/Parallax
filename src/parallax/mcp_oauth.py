"""Short-lived OAuth consent sessions and explicit, revocable Parallax grants.

The Supabase access token stays in memory for at most five minutes. The browser
receives only opaque cookies, and refresh tokens are never retained. A restart
requires signing in again. Durable grants contain client IDs, not credentials.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit
from fastapi import HTTPException
from .accounts import Principal, SignInRefused, digest, _UUID, OWNER_WORKSPACE
from .store import allow_rate

CONSENT_COOKIE = "parallax_consent"
CONSENT_FLOW_COOKIE = "parallax_consent_flow"
CONSENT_PATH = "/api/oauth"
CONSENT_SECONDS = 300


def authorization_id(value: str) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise HTTPException(400, "Invalid authorization request")
    return value


def redirect_url(value) -> str:
    """Only Supabase supplies this URL. Allow HTTPS or native clients' loopback callbacks."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise HTTPException(502, "Invalid authorization response")
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}))):
        raise HTTPException(502, "Invalid authorization response")
    return value


class Consent:
    def __init__(self, accounts):
        self.accounts = accounts
        self.pending: dict[str, dict] = {}
        self.lock = asyncio.Lock()
        with accounts.store.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS mcp_grants(
                account TEXT NOT NULL, client TEXT NOT NULL, name TEXT NOT NULL,
                created REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, revoked_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(account,client));""")

    def seal_flow(self, binding: str, identifier: str) -> str:
        payload = binding + "|" + authorization_id(identifier)
        tag = hmac.new(self.accounts.deployment.token.encode(), ("mcp-consent|" + payload).encode(), hashlib.sha256).hexdigest()
        return payload + "|" + tag

    def open_flow(self, value: str) -> tuple[str, str]:
        if len(value) > 512:
            raise SignInRefused("expired")
        parts = value.split("|")
        if len(parts) != 3 or not _UUID.fullmatch(parts[1]):
            raise SignInRefused("expired")
        if not hmac.compare_digest(value, self.seal_flow(parts[0], parts[1])):
            raise SignInRefused("expired")
        self.accounts._open_flow(parts[0])
        return parts[0], parts[1]

    async def sweep(self):
        expired = [self.pending.pop(key) for key, value in list(self.pending.items()) if value["expires"] <= time.time()]
        for value in expired:
            await self.accounts.revoke_provider_session(value["token"])

    async def abandon(self, session_hash: str | None):
        values = [self.pending.pop(key) for key, value in list(self.pending.items()) if value["session"] == session_hash]
        await asyncio.gather(*(self.accounts.revoke_provider_session(value["token"]) for value in values))

    async def close(self):
        values, self.pending = list(self.pending.values()), {}
        await asyncio.gather(*(self.accounts.revoke_provider_session(value["token"]) for value in values))

    async def janitor(self):
        while True:
            await asyncio.sleep(15)
            await self.sweep()

    async def sign_in(self, identifier: str, provider_session: dict) -> tuple[str, int, str]:
        authorization_id(identifier)
        token = provider_session.get("access_token", "")
        retained = False
        try:
            token, profile = await self.accounts.provider_identity(provider_session)
            await self.sweep()
            if len(self.pending) >= 256:
                raise SignInRefused("busy")
            account, workspace = self.accounts._admit(profile)
            if workspace == OWNER_WORKSPACE:
                raise HTTPException(403, "Remote tools require a personal account. Operator workspaces cannot be connected.")
            with self.accounts.store.connect() as db:
                if not allow_rate(db, "mcp-consent:" + account, 10, 300):
                    raise SignInRefused("busy")
                revoked = [row[0] for row in db.execute("SELECT client FROM mcp_grants WHERE account=? AND revoked=1", (account,))]
            # Clear upstream consent for locally revoked clients, so reconnecting displays access again.
            for client in revoked:
                status, _ = await self.accounts._supabase("DELETE", "/user/oauth/grants", jwt=token, query={"client_id":client})
                if status >= 400 and status != 404:
                    raise SignInRefused("failed")
            session, lifetime = self.accounts.create_session("account", workspace, account)
            nonce = secrets.token_urlsafe(32)
            self.pending[digest(nonce)] = {"token": token, "authorization": identifier, "session": digest(session),
                "account": account, "subject": profile["subject"], "expires": time.time() + CONSENT_SECONDS}
            retained = True
            return session, lifetime, nonce
        finally:
            if not retained and isinstance(token, str) and token:
                await self.accounts.revoke_provider_session(token)

    def _pending(self, nonce, principal, identifier):
        value = self.pending.get(digest(nonce or ""))
        if (not value or value["expires"] <= time.time() or not principal or not principal.session
                or principal.session != value["session"] or not principal.account
                or principal.account["id"] != value["account"] or identifier != value["authorization"]):
            raise HTTPException(401, "Sign in again to confirm this connection")
        return value

    async def details(self, nonce: str, principal: Principal, identifier: str) -> dict:
        async with self.lock:
            value = self._pending(nonce, principal, identifier)
            status, data = await self.accounts._supabase("GET", "/oauth/authorizations/" + value["authorization"], jwt=value["token"])
            if status != 200:
                raise HTTPException(400, "This authorization request expired. Restart the connection from your app.")
            # Supabase can reuse an existing consent. Local revocation still blocks all MCP calls.
            if "redirect_url" in data:
                destination = redirect_url(data["redirect_url"])
                self.pending.pop(digest(nonce), None)
                await self.accounts.revoke_provider_session(value["token"])
                return {"redirect_url": destination}
            client, user = data.get("client"), data.get("user")
            if (not isinstance(client, dict) or not _UUID.fullmatch(str(client.get("id", "")))
                    or not isinstance(user, dict) or "supabase:" + str(user.get("id")) != value["subject"]
                    or data.get("authorization_id") != value["authorization"]):
                raise HTTPException(502, "Invalid authorization response")
            value["client"] = client["id"]
            value["name"] = str(client.get("name") or "Unnamed client")[:200]
            value["redirect"] = redirect_url(data.get("redirect_uri"))
            return {"client": {"id": client["id"], "name": value["name"]},
                    "redirect_uri": value["redirect"], "scope": str(data.get("scope", ""))[:1000]}

    async def decide(self, nonce: str, principal: Principal, identifier: str, approve: bool) -> dict:
        # A consent nonce can decide only once, even if two requests race.
        async with self.lock:
            value = self._pending(nonce, principal, identifier)
            if "client" not in value:
                raise HTTPException(409, "Read the requested access before deciding")
            self.pending.pop(digest(nonce))
            try:
                status, data = await self.accounts._supabase("POST", "/oauth/authorizations/" + value["authorization"] + "/consent",
                    jwt=value["token"], body={"action": "approve" if approve else "deny"})
                if status != 200:
                    raise HTTPException(400, "Authorization failed. Restart the connection from your app.")
                destination = redirect_url(data.get("redirect_url"))
                base, target = urlsplit(value["redirect"]), urlsplit(destination)
                if (base.scheme, base.netloc, base.path) != (target.scheme, target.netloc, target.path):
                    raise HTTPException(502, "Authorization callback changed")
                if approve:
                    with self.accounts.store.connect() as db:
                        db.execute("""INSERT INTO mcp_grants(account,client,name,created,revoked) VALUES(?,?,?,?,0)
                            ON CONFLICT(account,client) DO UPDATE SET name=excluded.name,created=excluded.created,revoked=0""",
                            (value["account"], value["client"], value["name"], int(time.time())))
                return {"redirect_url": destination}
            finally:
                await self.accounts.revoke_provider_session(value["token"])

    def grants(self, principal: Principal) -> list[dict]:
        if not principal.account:
            raise HTTPException(403, "Sign in with your Parallax account")
        with self.accounts.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT client,name,created FROM mcp_grants WHERE account=? AND revoked=0",
                                                   (principal.account["id"],))]

    def revoke(self, principal: Principal, client: str):
        authorization_id(client)
        if not principal.account:
            raise HTTPException(403, "Sign in with your Parallax account")
        with self.accounts.store.connect() as db:
            db.execute("UPDATE mcp_grants SET revoked=1,revoked_at=? WHERE account=? AND client=?", (int(time.time()), principal.account["id"], client))
        return {"ok": True}

    def principal(self, subject: str, client: str, issued: int) -> Principal | None:
        # A token cannot create an account, choose a workspace, elevate to the operator, or restore a deleted grant.
        with self.accounts.store.connect() as db:
            row = db.execute("""SELECT a.id,a.workspace,w.name FROM accounts a JOIN workspaces w ON w.id=a.workspace
                JOIN mcp_grants g ON g.account=a.id WHERE a.subject=? AND a.disabled=0 AND g.client=?
                AND g.revoked=0 AND g.created<=? AND g.revoked_at<? AND w.kind='personal'""", ("supabase:" + subject, client, issued, issued)).fetchone()
        return Principal("mcp", row["workspace"], False, row["name"], {"id": row["id"]}) if row else None
