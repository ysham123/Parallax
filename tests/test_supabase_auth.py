"""Supabase sign-in for hosted Studio: email and password, password reset, GitHub and Google.

Supabase Auth is replaced by an httpx MockTransport that enforces the parts of its
protocol Parallax relies on: confirmation, single-use email links, PKCE, token
revocation and admin deletion. No network access or real project is used.
"""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
import httpx
from fastapi.testclient import TestClient
from parallax.accounts import Accounts, SESSION_COOKIE
from parallax.deployment import HOSTED_SECRETS, Deployment, SupabaseProject
from parallax.server import create_app
from parallax.store import Store

ORIGIN = "https://studio.example.com"
RUNTIME = "https://runtime.example.com"
KEY = "operator-access-key-with-at-least-32-characters"
PROJECT = "https://proj.supabase.co"
PUBLISHABLE = "sb_publishable_test_key_0123456789abcdef"
SECRET_KEY = "sb_secret_test_key_0123456789abcdefghij"


class FakeSupabase:
    """The Supabase Auth endpoints Parallax calls, with their refusals."""

    def __init__(self):
        self.users, self.tokens, self.links, self.codes = {}, {}, {}, {}
        self.revoked, self.deleted, self.mail, self.calls = set(), [], [], []
        self.external = {"email": True, "github": True, "google": True}
        self.settings_fail = False

    # Helpers the tests use to play the person and the provider.
    def link(self, email, kind):
        return next(token for token, (user, link_kind) in reversed(list(self.links.items()))
                    if self.users[user]["email"] == email and link_kind == kind)

    def authorize(self, url, *, email="octo@example.com", provider="github", github_id=4242, confirmed=True):
        query = parse_qs(urlsplit(url).query)
        assert query["code_challenge_method"] == ["s256"], query
        user = next((uid for uid, u in self.users.items() if u["email"] == email), None) or self._create(email, None, confirmed=confirmed)
        record = self.users[user]
        record["app_metadata"] = {"provider": provider, "providers": [provider]}
        record["user_metadata"] = {"user_name": "octocat", "full_name": "Octo Cat",
                                   "avatar_url": "https://avatars.githubusercontent.com/u/4242"} if provider == "github" else {
            "full_name": "Goo Gle", "avatar_url": "https://lh3.googleusercontent.com/a/x"}
        record["identities"] = [{"provider": provider, "identity_data": {"provider_id": str(github_id) if provider == "github" else "g-1"}}]
        code = uuid.uuid4().hex
        self.codes[code] = (user, query["code_challenge"][0])
        return query["redirect_to"][0] + "?" + urlencode({"code": code})

    def _create(self, email, password, confirmed=False, name=None):
        user = str(uuid.uuid4())
        self.users[user] = {"email": email, "password": password, "confirmed": confirmed,
                            "user_metadata": {"name": name} if name else {}, "app_metadata": {"provider": "email"}, "identities": []}
        return user

    def _session(self, user):
        token = "eyJ" + uuid.uuid4().hex + "." + uuid.uuid4().hex + "." + uuid.uuid4().hex
        self.tokens[token] = user
        return {"access_token": token, "refresh_token": uuid.uuid4().hex, "expires_in": 3600, "token_type": "bearer", "user": self._user(user)}

    def _user(self, user):
        record = self.users[user]
        return {"id": user, "email": record["email"], "email_confirmed_at": "2026-10-08T00:00:00Z" if record["confirmed"] else None,
                "user_metadata": record["user_metadata"], "app_metadata": record["app_metadata"], "identities": record["identities"]}

    def __call__(self, request):
        url = urlsplit(str(request.url))
        if f"{url.scheme}://{url.netloc}" != PROJECT or not url.path.startswith("/auth/v1/"):
            return httpx.Response(404)
        path, query = url.path[len("/auth/v1"):], parse_qs(url.query)
        body = json.loads(request.content) if request.content else {}
        admin = path.startswith("/admin/")
        if request.headers.get("apikey") != (SECRET_KEY if admin else PUBLISHABLE):
            return httpx.Response(401, json={"error_code": "no_authorization"})
        self.calls.append((request.method, path))
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        fail = lambda status, code: httpx.Response(status, json={"code": status, "error_code": code, "msg": code})
        if path == "/settings":
            return httpx.Response(500) if self.settings_fail else httpx.Response(200, json={"external": self.external})
        if path == "/signup":
            if len(body.get("password") or "") < 10:
                return fail(422, "weak_password")
            existing = next((uid for uid, u in self.users.items() if u["email"] == body["email"]), None)
            user = existing or self._create(body["email"], body["password"], name=(body.get("data") or {}).get("name"))
            if not existing:
                token = uuid.uuid4().hex
                self.links[token] = (user, "email")
                self.mail.append(("confirm", body["email"], query.get("redirect_to", [""])[0]))
            return httpx.Response(200, json={"id": str(uuid.uuid4()), "email": body["email"]})  # Obfuscated for existing emails.
        if path == "/verify":
            entry = self.links.pop(body.get("token_hash"), None)
            wanted = {"recovery"} if body.get("type") == "recovery" else {"email", "signup"}
            if entry is None or entry[1] not in wanted or body.get("type") not in wanted | {"email"}:
                return fail(403, "otp_expired")
            if entry[1] == "email":
                self.users[entry[0]]["confirmed"] = True
            return httpx.Response(200, json=self._session(entry[0]))
        if path == "/token" and query.get("grant_type") == ["password"]:
            user = next((uid for uid, u in self.users.items() if u["email"] == body.get("email")), None)
            if user is None or self.users[user]["password"] != body.get("password"):
                return fail(400, "invalid_credentials")
            if not self.users[user]["confirmed"]:
                return fail(400, "email_not_confirmed")
            return httpx.Response(200, json=self._session(user))
        if path == "/token" and query.get("grant_type") == ["pkce"]:
            entry = self.codes.pop(body.get("auth_code"), None)
            if entry is None:
                return fail(404, "flow_state_not_found")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(body.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
            if challenge != entry[1]:
                return fail(400, "bad_code_verifier")
            return httpx.Response(200, json=self._session(entry[0]))
        if path == "/user":
            user = self.tokens.get(bearer) if bearer not in self.revoked else None
            if user is None or user not in self.users:
                return fail(401, "bad_jwt")
            if request.method == "PUT":
                if len(body.get("password") or "") < 10:
                    return fail(422, "weak_password")
                self.users[user]["password"] = body["password"]
            return httpx.Response(200, json=self._user(user))
        if path == "/logout":
            self.revoked.add(bearer)
            return httpx.Response(204)
        if path == "/recover":
            user = next((uid for uid, u in self.users.items() if u["email"] == body.get("email")), None)
            if user:
                self.links[uuid.uuid4().hex] = (user, "recovery")
                self.mail.append(("recover", body["email"], query.get("redirect_to", [""])[0]))
            return httpx.Response(200, json={})
        if admin and request.method == "DELETE":
            user = path.rsplit("/", 1)[1]
            self.users.pop(user, None)
            self.deleted.append(user)
            return httpx.Response(200, json={})
        return httpx.Response(404)


class SupabaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"; self.projects.mkdir()
        self.store = Store(self.root / "state")
        self.supabase = FakeSupabase()
        self.app = self.make_app()

    def make_app(self, **changes):
        values = dict(token=KEY, origins=frozenset({ORIGIN}), hosts=frozenset({"runtime.example.com"}), projects=self.projects,
                      public_origin=ORIGIN, supabase=SupabaseProject(PROJECT, PUBLISHABLE, SECRET_KEY),
                      owner_emails=frozenset({"owner@example.com"}))
        values.update(changes)
        return create_app(self.store, token=KEY, deployment=Deployment(**values), http_transport=httpx.MockTransport(self.supabase))

    def browser(self, app=None):
        client = TestClient(app or self.app, base_url=RUNTIME)
        self.addCleanup(client.close)
        return client

    def post(self, client, path, body):
        return client.post(path, json=body, headers={"Origin": ORIGIN})

    def confirmed(self, email="ada@example.com", password="correct horse battery", client=None):
        client = client or self.browser()
        self.assertEqual(self.post(client, "/api/auth/email/signup", {"email": email, "password": password}).status_code, 200)
        confirm = client.get("/api/auth/confirm", params={"token_hash": self.supabase.link(email, "email"), "type": "email"},
                             follow_redirects=False)
        self.assertEqual((confirm.status_code, confirm.headers["location"]), (303, "/"), confirm.text)
        return client


class EmailPasswordTests(SupabaseFixture):
    def test_config_lists_the_project_providers_and_survives_an_outage(self):
        client = self.browser()
        self.assertEqual(client.get("/api/auth/config").json(), {"github": True, "identity": "supabase", "providers": ["email", "github", "google"], "signup": "open"})
        self.supabase.external = {"email": True, "github": False, "google": True}
        self.assertEqual(client.get("/api/auth/config").json()["providers"], ["email", "github", "google"])  # Cached briefly.
        app = self.make_app()
        self.supabase.settings_fail = True
        self.assertEqual(self.browser(app).get("/api/auth/config").json()["providers"], ["email"])

    def test_sign_up_confirm_log_in_and_log_out(self):
        client = self.browser()
        reply = self.post(client, "/api/auth/email/signup", {"email": "Ada@Example.com", "password": "correct horse battery", "name": "Ada"})
        self.assertEqual(reply.json(), {"ok": True, "next": "confirm"})
        self.assertEqual(self.supabase.mail[-1], ("confirm", "ada@example.com", ORIGIN))
        # The address is not confirmed yet.
        early = self.post(client, "/api/auth/email/login", {"email": "ada@example.com", "password": "correct horse battery"})
        self.assertEqual((early.status_code, early.json()["detail"]), (403, "unconfirmed"))
        # The emailed link works on any device and signs the person in.
        phone = self.browser()
        confirm = phone.get("/api/auth/confirm", params={"token_hash": self.supabase.link("ada@example.com", "email"), "type": "email"},
                            follow_redirects=False)
        self.assertEqual((confirm.status_code, confirm.headers["location"]), (303, "/"))
        session = phone.get("/api/session").json()
        self.assertEqual((session["auth"], session["account"]["email"], session["account"]["name"], session["workspace"]["kind"]),
                         ("account", "ada@example.com", "Ada", "personal"))
        # The Supabase token was used once, revoked, and never stored.
        self.assertTrue(self.supabase.revoked)
        stored = self.store.path.read_bytes()
        self.assertFalse(any(token.encode() in stored for token in self.supabase.tokens))
        # Log out, then back in with the password.
        self.assertEqual(phone.delete("/api/session", headers={"Origin": ORIGIN}).status_code, 200)
        self.assertEqual(phone.get("/api/session").status_code, 401)
        login = self.post(client, "/api/auth/email/login", {"email": "ada@example.com", "password": "correct horse battery"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(client.get("/api/session").json()["workspace"]["id"], session["workspace"]["id"])
        # A used link cannot be replayed.
        replay = self.browser().get("/api/auth/confirm", params={"token_hash": "f" * 56, "type": "email"}, follow_redirects=False)
        self.assertEqual(replay.headers["location"], "/login?auth_error=link_expired")

    def test_wrong_passwords_are_generic_and_throttled_per_email(self):
        self.confirmed()
        client = self.browser()
        for _ in range(10):
            wrong = self.post(client, "/api/auth/email/login", {"email": "ada@example.com", "password": "not the password"})
            self.assertEqual((wrong.status_code, wrong.json()["detail"]), (401, "credentials"))
        blocked = self.post(client, "/api/auth/email/login", {"email": "ada@example.com", "password": "correct horse battery"})
        self.assertEqual((blocked.status_code, blocked.json()["detail"]), (429, "busy"))
        unknown = self.post(client, "/api/auth/email/login", {"email": "nobody@example.com", "password": "whatever it is"})
        self.assertEqual(unknown.json()["detail"], "credentials")  # Same answer as a wrong password.

    def test_sign_up_never_reveals_an_existing_email_and_checks_input(self):
        self.confirmed()
        client = self.browser()
        again = self.post(client, "/api/auth/email/signup", {"email": "ada@example.com", "password": "another long password"})
        self.assertEqual(again.json(), {"ok": True, "next": "confirm"})
        for body, code in (({"email": "not-an-email", "password": "long enough pass"}, "invalid_email"),
                           ({"email": "bo@example.com", "password": "short"}, "weak_password"),
                           ({"email": "bo@example.com", "password": "x" * 73}, "weak_password")):
            reply = self.post(client, "/api/auth/email/signup", body)
            self.assertEqual((reply.status_code, reply.json()["detail"]), (400, code))
        # Five sign-ups per address per hour.
        for _ in range(5):
            self.post(client, "/api/auth/email/signup", {"email": "flood@example.com", "password": "long enough pass"})
        self.assertEqual(self.post(client, "/api/auth/email/signup", {"email": "flood@example.com", "password": "long enough pass"}).status_code, 429)

    def test_forgot_and_reset_password(self):
        self.confirmed()
        client = self.browser()
        for email in ("ada@example.com", "nobody@example.com"):
            self.assertEqual(self.post(client, "/api/auth/password/forgot", {"email": email}).json(), {"ok": True})
        self.assertEqual(self.supabase.mail[-1], ("recover", "ada@example.com", ORIGIN + "/reset"))
        token = self.supabase.link("ada@example.com", "recovery")
        weak = self.post(client, "/api/auth/password/reset", {"token_hash": token, "password": "short"})
        self.assertEqual(weak.json()["detail"], "weak_password")
        reset = self.post(client, "/api/auth/password/reset", {"token_hash": token, "password": "a brand new passphrase"})
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(client.get("/api/session").json()["account"]["email"], "ada@example.com")
        self.assertEqual(self.post(self.browser(), "/api/auth/email/login", {"email": "ada@example.com", "password": "correct horse battery"}).status_code, 401)
        self.assertEqual(self.post(self.browser(), "/api/auth/email/login", {"email": "ada@example.com", "password": "a brand new passphrase"}).status_code, 200)
        reused = self.post(self.browser(), "/api/auth/password/reset", {"token_hash": token, "password": "yet another passphrase"})
        self.assertEqual(reused.json()["detail"], "link_expired")

    def test_sign_in_routes_require_the_studio_origin(self):
        client = self.browser()
        for path in ("/api/auth/email/signup", "/api/auth/email/login", "/api/auth/password/forgot", "/api/auth/oauth/start"):
            self.assertEqual(client.post(path, json={}).status_code, 403, path)
            self.assertEqual(client.post(path, json={}, headers={"Origin": "https://evil.example.com"}).status_code, 403, path)


class OAuthTests(SupabaseFixture):
    def start(self, client, provider="github"):
        start = self.post(client, "/api/auth/oauth/start", {"provider": provider})
        self.assertEqual(start.status_code, 200, start.text)
        self.assertEqual(start.cookies.get("parallax_oauth") is not None or "parallax_oauth" in start.headers.get("set-cookie", ""), True)
        return start.json()["url"]

    def test_github_round_trip_records_the_identity(self):
        client = self.browser()
        url = self.start(client)
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.assertEqual((f"{parts.scheme}://{parts.netloc}", parts.path), (PROJECT, "/auth/v1/authorize"))
        self.assertEqual((query["provider"], query["redirect_to"]), (["github"], [ORIGIN + "/api/auth/oauth/callback"]))
        callback = urlsplit(self.supabase.authorize(url))
        done = client.get(callback.path + "?" + callback.query, follow_redirects=False)
        self.assertEqual((done.status_code, done.headers["location"]), (303, "/"), done.text)
        account = client.get("/api/session").json()["account"]
        self.assertEqual((account["login"], account["name"], account["provider"]), ("octocat", "Octo Cat", "github"))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT github_id FROM accounts").fetchone()[0], 4242)

    def test_forged_replayed_denied_and_unknown_flows_fail(self):
        attacker = self.browser()
        forged = urlsplit(self.supabase.authorize(self.start(attacker), email="mallory@example.com"))
        # A victim with no flow, or with their own pending flow, cannot be signed in to the attacker's account.
        for pending in (False, True):
            victim = self.browser()
            if pending:
                self.start(victim)
            outcome = victim.get(forged.path + "?" + forged.query, follow_redirects=False)
            self.assertIn(outcome.headers["location"], ("/login?auth_error=expired", "/login?auth_error=link_expired"))
            self.assertEqual(victim.get("/api/session").status_code, 401)
        client = self.browser()
        url = self.start(client)
        denied = client.get("/api/auth/oauth/callback", params={"error": "access_denied"}, follow_redirects=False)
        self.assertEqual(denied.headers["location"], "/login?auth_error=denied")
        unknown = self.post(self.browser(), "/api/auth/oauth/start", {"provider": "myspace"})
        self.assertEqual(unknown.status_code, 422)
        late = self.browser()
        url = self.start(late)
        callback = urlsplit(self.supabase.authorize(url))
        with patch("parallax.accounts.time.time", return_value=time.time() + 601):
            expired = late.get(callback.path + "?" + callback.query, follow_redirects=False)
        self.assertEqual(expired.headers["location"], "/login?auth_error=expired")

    def test_unconfirmed_identities_are_refused(self):
        client = self.browser()
        callback = urlsplit(self.supabase.authorize(self.start(client, "google"), email="new@example.com", provider="google", confirmed=False))
        refused = client.get(callback.path + "?" + callback.query, follow_redirects=False)
        self.assertEqual(refused.headers["location"], "/login?auth_error=unconfirmed")


class PolicyTests(SupabaseFixture):
    def test_owner_email_opens_the_operator_workspace_until_removed(self):
        owner = self.confirmed("owner@example.com")
        self.assertEqual(owner.get("/api/session").json()["workspace"]["id"], "owner")
        demoted = self.make_app(owner_emails=frozenset())
        cookie = owner.cookies.get(SESSION_COOKIE)
        later = self.browser(demoted); later.cookies.set(SESSION_COOKIE, cookie)
        self.assertEqual(later.get("/api/session").status_code, 401)

    def test_capacity_and_closed_sign_up_are_refused_before_contacting_supabase(self):
        self.confirmed("first@example.com")
        full = self.browser(self.make_app(max_accounts=1))
        calls = len(self.supabase.calls)
        reply = self.post(full, "/api/auth/email/signup", {"email": "second@example.com", "password": "long enough pass"})
        self.assertEqual((reply.status_code, reply.json()["detail"]), (409, "capacity"))
        self.assertEqual(len(self.supabase.calls), calls)
        # An email that already has an account gets the same answer, so the refusal reveals nothing about it.
        again = self.post(full, "/api/auth/email/signup", {"email": "first@example.com", "password": "long enough pass"})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "capacity"))
        closed = self.browser(self.make_app(signup="closed"))
        self.assertEqual(self.post(closed, "/api/auth/email/signup", {"email": "third@example.com", "password": "long enough pass"}).json()["detail"], "closed")
        invited = self.browser(self.make_app(signup="allowlist", allowed_emails=frozenset({"guest@example.com"})))
        self.assertEqual(self.post(invited, "/api/auth/email/signup", {"email": "stranger@example.com", "password": "long enough pass"}).json()["detail"], "not_invited")
        self.assertEqual(self.post(invited, "/api/auth/email/signup", {"email": "guest@example.com", "password": "long enough pass"}).status_code, 200)
        # The owner can always sign up.
        self.assertEqual(self.post(full, "/api/auth/email/signup", {"email": "owner@example.com", "password": "long enough pass"}).status_code, 200)

    def test_deleting_an_account_removes_the_supabase_identity(self):
        client = self.confirmed()
        user = next(uid for uid, record in self.supabase.users.items() if record["email"] == "ada@example.com")
        wrong = client.delete("/api/account", params={"confirm": "someone@example.com"}, headers={"Origin": ORIGIN})
        self.assertEqual(wrong.status_code, 409)
        gone = client.delete("/api/account", params={"confirm": "ADA@example.com"}, headers={"Origin": ORIGIN})
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(self.supabase.deleted, [user])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
        self.confirmed()  # The same address can start over.

    def test_github_only_accounts_migrate_and_keep_their_sessions(self):
        home = self.root / "legacy"; home.mkdir()
        db = sqlite3.connect(home / "state.sqlite3")
        db.executescript("""
            CREATE TABLE accounts(id TEXT PRIMARY KEY, github_id INTEGER NOT NULL UNIQUE, login TEXT NOT NULL, name TEXT, avatar TEXT,
                workspace TEXT, created REAL NOT NULL, last_login REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE workspaces(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, hosted_execution INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
            CREATE TABLE sessions(hash TEXT PRIMARY KEY, kind TEXT NOT NULL, account TEXT, workspace TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, credential TEXT);""")
        now = time.time()
        db.execute("INSERT INTO workspaces VALUES('ws-1','personal','octo',0,?)", (now,))
        db.execute("INSERT INTO accounts VALUES('acct-1',4242,'octo',NULL,NULL,'ws-1',?,?,0)", (now, now))
        token = "legacy-session-token-value"
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,NULL)", (hashlib.sha256(token.encode()).hexdigest(), "github", "acct-1", "ws-1", now, now + 3600))
        db.commit(); db.close()
        store = Store(home)
        deployment = Deployment(token=KEY, origins=frozenset({ORIGIN}), hosts=frozenset({"runtime.example.com"}), projects=self.projects, public_origin=ORIGIN)
        accounts = Accounts(store, deployment)
        Accounts(store, deployment)  # Idempotent.
        with store.connect() as conn:
            self.assertEqual(tuple(conn.execute("SELECT subject,provider,github_id,login FROM accounts").fetchone()), ("github:4242", "github", 4242, "octo"))
        principal = accounts.principal(token)
        self.assertEqual((principal.kind, principal.workspace, principal.account["login"]), ("account", "ws-1", "octo"))


class SupabaseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = {"PARALLAX_ACCESS_TOKEN": KEY, "PARALLAX_STUDIO_ORIGINS": ORIGIN, "PARALLAX_ALLOWED_HOSTS": "runtime.example.com",
                     "PARALLAX_PROJECTS_ROOT": self.temp.name}

    def load(self, **extra):
        with patch.dict(os.environ, {**self.base, **extra}, clear=True):
            return Deployment.from_env()

    def test_supabase_configuration_is_validated_and_redacted(self):
        configured = self.load(PARALLAX_SUPABASE_URL=PROJECT + "/", PARALLAX_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE,
                               PARALLAX_SUPABASE_SECRET_KEY=SECRET_KEY, PARALLAX_OWNER_EMAILS="Owner@Example.com, two@example.com")
        self.assertEqual((configured.supabase.url, configured.oauth_redirect), (PROJECT, ORIGIN + "/api/auth/oauth/callback"))
        self.assertEqual(configured.owner_emails, frozenset({"owner@example.com", "two@example.com"}))
        for secret in (PUBLISHABLE, SECRET_KEY, KEY):
            self.assertNotIn(secret, repr(configured))
        self.assertIn("PARALLAX_SUPABASE_SECRET_KEY", HOSTED_SECRETS)
        self.assertIn("PARALLAX_SUPABASE_PUBLISHABLE_KEY", HOSTED_SECRETS)
        for extra in ({"PARALLAX_SUPABASE_URL": "http://proj.supabase.co", "PARALLAX_SUPABASE_PUBLISHABLE_KEY": PUBLISHABLE},
                      {"PARALLAX_SUPABASE_URL": PROJECT + "/rest", "PARALLAX_SUPABASE_PUBLISHABLE_KEY": PUBLISHABLE},
                      {"PARALLAX_SUPABASE_URL": PROJECT},
                      {"PARALLAX_SUPABASE_PUBLISHABLE_KEY": PUBLISHABLE},
                      {"PARALLAX_SUPABASE_URL": PROJECT, "PARALLAX_SUPABASE_PUBLISHABLE_KEY": "short"},
                      {"PARALLAX_OWNER_EMAILS": "not an email"}):
            with self.assertRaises(ValueError, msg=str(extra)):
                self.load(**extra)


if __name__ == "__main__":
    unittest.main()
