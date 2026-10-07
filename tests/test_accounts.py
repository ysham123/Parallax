"""Hosted accounts, personal workspaces, and cross-workspace denial.

GitHub is replaced by an httpx MockTransport; no network access or real OAuth
application is used. Two TestClient instances on one app act as two browsers.
"""
import asyncio
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
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
import httpx
from fastapi.testclient import TestClient
from parallax import executors
from parallax.accounts import OWNER_WORKSPACE, SESSION_COOKIE, FLOW_COOKIE
from parallax.deployment import Deployment, GitHubApp
from parallax.executors import ExecutorHub
from parallax.server import create_app
from parallax.store import Store

ORIGIN = "https://studio.example.com"
RUNTIME = "https://runtime.example.com"
KEY = "operator-access-key-with-at-least-32-characters"
SECRET = "github-client-secret-for-tests-0123456789"
OWNER_ID = 111


class FakeGitHub:
    """Implements the two GitHub endpoints Parallax calls, and checks PKCE."""

    def __init__(self):
        self.users = {}
        self.challenges = {}
        self.calls = []
        self.fail_exchange = False

    def issue(self, user, challenge):
        code = "code-" + uuid.uuid4().hex
        self.users[code] = user
        self.challenges[code] = challenge
        return code

    def __call__(self, request):
        self.calls.append(str(request.url))
        if request.url.host == "github.com" and request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            code = form["code"][0]
            verifier = form["code_verifier"][0]
            expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if self.fail_exchange or code not in self.users or self.challenges[code] != expected or form["client_secret"][0] != SECRET:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            assert request.headers["accept"] == "application/json"
            assert form["redirect_uri"][0] == ORIGIN + "/api/auth/github/callback"
            return httpx.Response(200, json={"access_token": "gho_" + code, "token_type": "bearer", "scope": ""})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            code = request.headers["authorization"].removeprefix("Bearer gho_")
            if code not in self.users:
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json=self.users[code])
        return httpx.Response(404)


def user(identifier, login, kind="User"):
    return {"id": identifier, "login": login, "name": login.title(), "type": kind,
            "avatar_url": f"https://avatars.githubusercontent.com/u/{identifier}?v=4"}


class HostedFixture(unittest.TestCase):
    """Shared hosted app, fake GitHub, and browser helpers. Holds no tests."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"; self.projects.mkdir()
        self.store = Store(self.root / "state")
        self.github = FakeGitHub()
        self.deployment = self.make_deployment()
        self.app = create_app(self.store, token=KEY, deployment=self.deployment, http_transport=httpx.MockTransport(self.github))

    def make_deployment(self, **changes):
        values = dict(token=KEY, origins=frozenset({ORIGIN}), hosts=frozenset({"runtime.example.com"}), projects=self.projects,
                      public_origin=ORIGIN, github=GitHubApp("Iv1.testclientid", SECRET), owner_github_ids=frozenset({OWNER_ID}))
        values.update(changes)
        return Deployment(**values)

    def browser(self, app=None):
        client = TestClient(app or self.app, base_url=RUNTIME)
        self.addCleanup(client.close)
        return client

    def sign_in(self, profile, client=None):
        client = client or self.browser()
        start = client.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        self.assertEqual(start.status_code, 200, start.text)
        query = parse_qs(urlsplit(start.json()["url"]).query)
        code = self.github.issue(profile, query["code_challenge"][0])
        callback = client.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        return client, callback

    def signed_in(self, profile):
        client, callback = self.sign_in(profile)
        self.assertEqual(callback.status_code, 303, callback.text)
        self.assertEqual(callback.headers["location"], "/")
        return client

    def pair(self, client, name="Mac", workspaces=("/project",)):
        code = client.post("/api/executors/pair", headers={"Origin": ORIGIN})
        self.assertEqual(code.status_code, 200, code.text)
        worker = self.browser().post("/api/worker/connect", json={"code": code.json()["code"], "name": name, "platform": "darwin", "workspaces": list(workspaces)})
        self.assertEqual(worker.status_code, 200, worker.text)
        return worker.json()


class HostedAccountTests(HostedFixture):
    # Sign-in flow ---------------------------------------------------------------
    def test_public_config_and_start_are_safe_to_expose(self):
        anonymous = self.browser()
        config = anonymous.get("/api/auth/config")
        self.assertEqual(config.json(), {"github": True, "signup": "open"})
        self.assertNotIn(SECRET, config.text)
        self.assertEqual(anonymous.post("/api/auth/github/start").status_code, 403)
        self.assertEqual(anonymous.post("/api/auth/github/start", headers={"Origin": "https://attacker.example"}).status_code, 403)
        start = anonymous.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        url = urlsplit(start.json()["url"])
        query = parse_qs(url.query)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "github.com", "/login/oauth/authorize"))
        self.assertEqual(query["redirect_uri"], [ORIGIN + "/api/auth/github/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("scope", query)
        self.assertNotIn(SECRET, start.text)
        cookie = start.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/api/auth/github", "Max-Age=600"):
            self.assertIn(flag, cookie)
        self.assertEqual(anonymous.get("/api/session").status_code, 401)

    def test_new_github_account_gets_an_empty_personal_workspace(self):
        client, callback = self.sign_in(user(501, "ada"))
        self.assertEqual(callback.status_code, 303)
        session = callback.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=strict"):
            self.assertIn(flag, session)
        body = client.get("/api/session").json()
        self.assertEqual(body["auth"], "github")
        self.assertEqual(body["account"]["login"], "ada")
        self.assertEqual(body["workspace"]["kind"], "personal")
        self.assertFalse(body["workspace"]["hosted_execution"])
        self.assertNotEqual(body["workspace"]["id"], OWNER_WORKSPACE)
        self.assertEqual(client.get("/api/executors").json(), [])
        # The GitHub token is used once and never persisted.
        self.assertNotIn(b"gho_", self.store.path.read_bytes())
        # A second sign-in reuses the same account and workspace.
        again = self.signed_in(user(501, "ada-renamed"))
        self.assertEqual(again.get("/api/session").json()["workspace"]["id"], body["workspace"]["id"])
        self.assertEqual(again.get("/api/session").json()["account"]["login"], "ada-renamed")

    def test_callback_rejects_replay_foreign_browser_denial_and_bad_profiles(self):
        attacker = self.browser()
        start = attacker.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        query = parse_qs(urlsplit(start.json()["url"]).query)
        code = self.github.issue(user(777, "mallory"), query["code_challenge"][0])
        # Login CSRF: a victim browser, with or without its own pending flow, cannot complete the attacker's flow.
        for pending_flow in (False, True):
            victim = self.browser()
            if pending_flow:
                victim.post("/api/auth/github/start", headers={"Origin": ORIGIN})
            forced = victim.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
            self.assertEqual(forced.headers["location"], "/?auth_error=expired")
            self.assertEqual(victim.get("/api/session").status_code, 401)
        cookieless = self.browser().get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        self.assertEqual(cookieless.headers["location"], "/?auth_error=expired")
        # The initiating browser completes once; replaying the same callback fails.
        first = attacker.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        self.assertEqual(first.headers["location"], "/")
        replay = attacker.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        self.assertEqual(replay.headers["location"], "/?auth_error=expired")
        # Cancelling on GitHub.
        client = self.browser()
        start = client.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        state = parse_qs(urlsplit(start.json()["url"]).query)["state"][0]
        denied = client.get("/api/auth/github/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
        self.assertEqual(denied.headers["location"], "/?auth_error=denied")
        # Organizations, malformed profiles, failed exchanges and unknown parameters never create sessions.
        for profile in (user(888, "acme", kind="Organization"), {"id": "888", "login": "x", "type": "User"}, {"id": 889, "login": "bad login", "type": "User"}):
            _, outcome = self.sign_in(profile)
            self.assertEqual(outcome.headers["location"], "/?auth_error=failed")
        self.github.fail_exchange = True
        _, outcome = self.sign_in(user(890, "eve"))
        self.assertEqual(outcome.headers["location"], "/?auth_error=failed")
        self.assertEqual(self.browser().get("/api/auth/github/callback", params={"state": "x" * 300, "code": "c"}, follow_redirects=False).headers["location"], "/?auth_error=expired")
        with self.store.connect() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT login FROM accounts")], ["mallory"])

    def test_expired_flow_and_callback_origin_exemption(self):
        client = self.browser()
        start = client.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        query = parse_qs(urlsplit(start.json()["url"]).query)
        code = self.github.issue(user(502, "grace"), query["code_challenge"][0])
        with patch("parallax.accounts.time.time", return_value=time.time() + 601):
            late = client.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        self.assertEqual(late.headers["location"], "/?auth_error=expired")
        # A browser that labels the GitHub navigation with an Origin is still handled by state validation.
        client, _ = self.browser(), None
        start = client.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        query = parse_qs(urlsplit(start.json()["url"]).query)
        code = self.github.issue(user(502, "grace"), query["code_challenge"][0])
        ok = client.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, headers={"Origin": "https://github.com"}, follow_redirects=False)
        self.assertEqual(ok.headers["location"], "/")

    def test_unconfigured_github_reports_unavailable(self):
        app = create_app(Store(self.root / "plain"), token=KEY, deployment=self.make_deployment(github=None))
        client = self.browser(app)
        self.assertEqual(client.get("/api/auth/config").json()["github"], False)
        refused = client.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (503, "unavailable"))
        self.assertEqual(client.get("/api/auth/github/callback", params={"code": "c", "state": "s"}, follow_redirects=False).headers["location"], "/?auth_error=unavailable")

    # Sessions ---------------------------------------------------------------------
    def test_sign_out_revokes_the_server_side_session(self):
        client = self.signed_in(user(503, "linus"))
        stolen = client.cookies.get(SESSION_COOKIE)
        copy = self.browser(); copy.cookies.set(SESSION_COOKIE, stolen)
        self.assertEqual(copy.get("/api/session").status_code, 200)
        self.assertEqual(client.delete("/api/session").status_code, 403)  # Studio Origin required
        self.assertEqual(client.delete("/api/session", headers={"Origin": ORIGIN}).status_code, 200)
        self.assertEqual(copy.get("/api/session").status_code, 401)
        self.assertEqual(client.get("/api/session").status_code, 401)

    def test_sessions_expire_and_tampering_fails(self):
        client = self.signed_in(user(504, "margaret"))
        self.assertEqual(client.get("/api/session").status_code, 200)
        with patch("parallax.accounts.time.time", return_value=time.time() + 7 * 86400 + 5):
            self.assertEqual(client.get("/api/session").status_code, 401)
        tampered = self.browser(); tampered.cookies.set(SESSION_COOKIE, client.cookies.get(SESSION_COOKIE) + "x")
        self.assertEqual(tampered.get("/api/session").status_code, 401)

    def test_operator_access_key_is_server_side_and_legacy_cookies_fail(self):
        stale = self.browser()
        legacy = "abc." + str(int(time.time())) + "." + "0" * 64
        stale.cookies.set(SESSION_COOKIE, legacy)
        self.assertEqual(stale.get("/api/session").status_code, 401)
        client = self.browser()
        signed = client.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN})
        self.assertEqual(signed.status_code, 200)
        self.assertNotIn(KEY, signed.text + signed.headers["set-cookie"])
        body = client.get("/api/session").json()
        self.assertEqual((body["auth"], body["workspace"]["id"], body["workspace"]["hosted_execution"]), ("operator", OWNER_WORKSPACE, True))
        self.assertEqual(client.get("/api/runs").status_code, 200)
        cookie = client.cookies.get(SESSION_COOKIE)
        # Rotating the access key ends sessions it opened, without affecting GitHub sessions.
        github = self.signed_in(user(505, "rotation"))
        rotated = create_app(self.store, token="a-rotated-operator-key-with-32-characters!!", deployment=self.make_deployment(token="a-rotated-operator-key-with-32-characters!!"), http_transport=httpx.MockTransport(self.github))
        after = self.browser(rotated); after.cookies.set(SESSION_COOKIE, cookie)
        self.assertEqual(after.get("/api/session").status_code, 401)
        kept = self.browser(rotated); kept.cookies.set(SESSION_COOKIE, github.cookies.get(SESSION_COOKIE))
        self.assertEqual(kept.get("/api/session").status_code, 200)
        self.assertEqual(client.delete("/api/session", headers={"Origin": ORIGIN}).status_code, 200)
        replay = self.browser(); replay.cookies.set(SESSION_COOKIE, cookie)
        self.assertEqual(replay.get("/api/runs").status_code, 401)

    def test_operator_github_account_and_removal(self):
        owner = self.signed_in(user(OWNER_ID, "yosef"))
        body = owner.get("/api/session").json()
        self.assertEqual(body["workspace"]["id"], OWNER_WORKSPACE)
        self.assertTrue(body["workspace"]["hosted_execution"])
        self.assertEqual(owner.get("/api/runs").status_code, 200)
        self.assertEqual(owner.delete("/api/account", headers={"Origin": ORIGIN}).status_code, 409)
        # Removing the account from PARALLAX_OWNER_GITHUB_IDS ends its operator access on the next request.
        demoted = create_app(self.store, token=KEY, deployment=self.make_deployment(owner_github_ids=frozenset()), http_transport=httpx.MockTransport(self.github))
        later = self.browser(demoted); later.cookies.set(SESSION_COOKIE, owner.cookies.get(SESSION_COOKIE))
        self.assertEqual(later.get("/api/runs").status_code, 401)
        personal = self.sign_in(user(OWNER_ID, "yosef"), self.browser(demoted))[0]
        self.assertEqual(personal.get("/api/session").json()["workspace"]["kind"], "personal")

    # Workspace boundary -------------------------------------------------------------
    def test_personal_workspaces_cannot_reach_the_hosted_engine(self):
        client = self.signed_in(user(505, "barbara"))
        run_id = str(uuid.uuid4())
        for method, path, body in (("get", "/api/runs", None), ("get", "/api/providers", None), ("get", "/api/providers?refresh=true", None),
                                   ("get", "/api/models/codex", None), ("get", "/api/connections", None), ("put", "/api/connections/key", {"provider": "codex"}),
                                   ("get", "/api/context", None), ("get", "/api/deployment", None), ("get", "/api/profiles", None),
                                   ("post", "/api/project/assess", {"workspace": str(self.projects)}), ("get", "/api/feedback/export", None),
                                   ("post", "/api/runs", {"workspace": str(self.projects), "prompt": "x"}), ("get", f"/api/runs/{run_id}/events", None),
                                   ("get", f"/api/runs/{run_id}/patch", None), ("post", f"/api/runs/{run_id}/cancel", None), ("get", "/api/project-profiles", None)):
            kwargs = {"headers": {"Origin": ORIGIN}}
            if body is not None: kwargs["json"] = body
            response = getattr(client, method)(path, **kwargs)
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.json()["code"], "hosted_execution_unavailable", path)

    def test_two_accounts_cannot_see_or_control_each_others_machines(self):
        alice, bob = self.signed_in(user(601, "alice")), self.signed_in(user(602, "bob"))
        operator = self.browser(); operator.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN})
        legacy = self.pair(operator, "Operator Mac", ["/operator/project"])
        a = self.pair(alice, "Alice Mac", ["/alice/project"])
        b = self.pair(bob, "Bob Mac", ["/bob/project"])
        self.assertEqual([m["name"] for m in alice.get("/api/executors").json()], ["Alice Mac"])
        self.assertEqual([m["name"] for m in bob.get("/api/executors").json()], ["Bob Mac"])
        self.assertEqual([m["name"] for m in operator.get("/api/executors").json()], ["Operator Mac"])
        run_id = str(uuid.uuid4())
        sync = self.browser().post("/api/worker/sync", headers={"Authorization": "Bearer " + a["token"]}, json={
            "runs": [{"run_id": run_id, "status": "completed", "spec": {"workspace": "/alice/project", "prompt": "secret alice prompt"}, "diff": "alice diff"}],
            "events": [{"run_id": run_id, "sequence": 1, "timestamp": "t", "kind": "status", "data": {"note": "alice event"}}]})
        self.assertEqual(sync.status_code, 200, sync.text)
        # Bob guesses Alice's and the operator's machine and run IDs through every route.
        for victim in (a["id"], legacy["id"]):
            for method, path in (("get", f"/api/executors/{victim}/proxy/runs"), ("get", f"/api/executors/{victim}/proxy/runs/{run_id}"),
                                 ("get", f"/api/executors/{victim}/proxy/runs/{run_id}/events"), ("get", f"/api/executors/{victim}/proxy/runs/{run_id}/patch"),
                                 ("post", f"/api/executors/{victim}/proxy/runs"), ("delete", f"/api/executors/{victim}")):
                response = getattr(bob, method)(path, headers={"Origin": ORIGIN})
                self.assertEqual(response.status_code, 404, (victim, path, response.text))
                self.assertNotIn("alice", response.text)
        missing = bob.get(f"/api/executors/{uuid.uuid4()}/proxy/runs")
        self.assertEqual((missing.status_code, missing.json()), (404, {"detail": "Execution machine not found"}))
        # Alice still sees her own mirrored evidence while her machine is offline.
        with self.store.connect() as db: db.execute("UPDATE workers SET seen=0 WHERE id=?", (a["id"],))
        own = alice.get(f"/api/executors/{a['id']}/proxy/runs/{run_id}")
        self.assertEqual((own.status_code, own.headers["x-parallax-offline"]), (200, "true"))
        self.assertEqual(own.json()["diff"], "alice diff")
        # Worker tokens cannot act as Studio sessions in any workspace.
        for token in (a["token"], b["token"]):
            for path in ("/api/executors", "/api/session", f"/api/executors/{a['id']}/proxy/runs"):
                self.assertEqual(self.browser().get(path, headers={"Authorization": "Bearer " + token}).status_code, 401)
        # Bob's pairing codes always land in Bob's workspace.
        self.assertEqual(sorted(m["name"] for m in bob.get("/api/executors").json()), ["Bob Mac"])
        self.assertEqual(alice.get("/api/executors").json()[0]["workspaces"], ["/alice/project"])

    def test_hub_methods_require_the_owning_workspace(self):
        hub = self.app.state.executors
        alice = self.signed_in(user(603, "carol"))
        workspace = alice.get("/api/session").json()["workspace"]["id"]
        worker = self.pair(alice)["id"]
        with self.assertRaises(Exception): hub.worker(worker, OWNER_WORKSPACE)
        with self.assertRaises(Exception): hub.revoke(worker, "someone-else")
        with self.assertRaises(Exception): hub.events(worker, str(uuid.uuid4()), 0, OWNER_WORKSPACE)
        self.assertEqual(hub.worker(worker, workspace)["id"], worker)
        with self.assertRaises(TypeError): hub.pair()  # The workspace is mandatory, never defaulted.
        with self.assertRaises(TypeError): hub.workers()

    # Policies, limits and lifecycle -------------------------------------------------
    def test_signup_policies_and_disabled_accounts(self):
        closed = create_app(self.store, token=KEY, deployment=self.make_deployment(signup="closed"), http_transport=httpx.MockTransport(self.github))
        self.assertEqual(self.sign_in(user(701, "new"), self.browser(closed))[1].headers["location"], "/?auth_error=closed")
        self.signed_in(user(702, "existing"))
        self.assertEqual(self.sign_in(user(702, "existing"), self.browser(closed))[1].headers["location"], "/")
        self.assertEqual(self.sign_in(user(OWNER_ID, "yosef"), self.browser(closed))[1].headers["location"], "/")
        invite = create_app(self.store, token=KEY, deployment=self.make_deployment(signup="allowlist", allowed_github_ids=frozenset({703})), http_transport=httpx.MockTransport(self.github))
        self.assertEqual(self.sign_in(user(704, "uninvited"), self.browser(invite))[1].headers["location"], "/?auth_error=not_invited")
        self.assertEqual(self.sign_in(user(703, "invited"), self.browser(invite))[1].headers["location"], "/")
        full = create_app(self.store, token=KEY, deployment=self.make_deployment(max_accounts=3), http_transport=httpx.MockTransport(self.github))
        self.assertEqual(self.sign_in(user(705, "late"), self.browser(full))[1].headers["location"], "/?auth_error=capacity")
        client = self.signed_in(user(706, "disabled"))
        with self.store.connect() as db: db.execute("UPDATE accounts SET disabled=1 WHERE github_id=706")
        self.assertEqual(client.get("/api/session").status_code, 401)
        self.assertEqual(self.sign_in(user(706, "disabled"))[1].headers["location"], "/?auth_error=disabled")

    def test_account_deletion_purges_machines_evidence_and_sessions(self):
        client = self.signed_in(user(801, "dora"))
        other = self.signed_in(user(802, "ellen"))
        workspace = client.get("/api/session").json()["workspace"]["id"]
        machine = self.pair(client)
        keep = self.pair(other)
        run_id = str(uuid.uuid4())
        self.browser().post("/api/worker/sync", headers={"Authorization": "Bearer " + machine["token"]},
                            json={"runs": [], "events": [{"run_id": run_id, "sequence": 1, "timestamp": "t", "kind": "status", "data": {}}]})
        self.assertEqual(client.delete("/api/account?confirm=dora").status_code, 403)
        # A stale tab confirming a different login cannot delete whoever the cookie belongs to now.
        self.assertEqual(client.delete("/api/account?confirm=ellen", headers={"Origin": ORIGIN}).status_code, 409)
        self.assertEqual(client.delete("/api/account", headers={"Origin": ORIGIN}).status_code, 409)
        self.assertEqual(client.delete("/api/account?confirm=DORA", headers={"Origin": ORIGIN}).status_code, 200)
        self.assertEqual(client.get("/api/session").status_code, 401)
        self.assertEqual(self.browser().get("/api/worker/next", headers={"Authorization": "Bearer " + machine["token"]}).status_code, 401)
        with self.store.connect() as db:
            for table in ("worker_scope", "worker_pair_scope"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace=?", (workspace,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workers WHERE id=?", (machine["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_events WHERE worker=?", (machine["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts WHERE github_id=801").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspaces WHERE id=?", (workspace,)).fetchone()[0], 0)
        self.assertEqual([m["id"] for m in other.get("/api/executors").json()], [keep["id"]])
        # Signing in again starts over with a new, empty workspace.
        again = self.signed_in(user(801, "dora"))
        self.assertNotEqual(again.get("/api/session").json()["workspace"]["id"], workspace)
        self.assertEqual(again.get("/api/executors").json(), [])

    def test_pairing_machine_and_queue_limits(self):
        client = self.signed_in(user(901, "frances"))
        codes = [client.post("/api/executors/pair", headers={"Origin": ORIGIN}) for _ in range(4)]
        self.assertEqual([c.status_code for c in codes], [200, 200, 200, 429])
        for code in codes[:3]:
            self.assertEqual(self.browser().post("/api/worker/connect", json={"code": code.json()["code"], "name": "M", "platform": "darwin", "workspaces": ["/p"]}).status_code, 200)
        self.assertEqual(client.post("/api/executors/pair", headers={"Origin": ORIGIN}).status_code, 409)
        machine = client.get("/api/executors").json()[0]["id"]
        hub = self.app.state.executors
        workspace = client.get("/api/session").json()["workspace"]["id"]
        with self.store.connect() as db:
            for _ in range(executors.PERSONAL_LIMITS.pending_commands):
                db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,NULL,?)",
                           (str(uuid.uuid4()), machine, json.dumps({"method": "GET", "path": "/api/runs", "query": "", "body": None, "expires_at": 0}), time.time()))
        busy = client.get(f"/api/executors/{machine}/proxy/runs")
        self.assertEqual(busy.status_code, 429, busy.text)
        self.assertEqual(len(hub.pending(machine)), 8)
        self.assertTrue(workspace)

    def test_evidence_budget_and_large_event_truncation(self):
        client = self.signed_in(user(902, "hedy"))
        machine = self.pair(client)
        token = {"Authorization": "Bearer " + machine["token"]}
        run_id = str(uuid.uuid4())
        big = {"run_id": run_id, "sequence": 1, "timestamp": "t", "kind": "tool", "data": {"output": "x" * (300 * 1024)}}
        self.assertEqual(self.browser().post("/api/worker/sync", headers=token, json={"runs": [], "events": [big]}).status_code, 200)
        stored = self.app.state.executors.events(machine["id"], run_id, 0, client.get("/api/session").json()["workspace"]["id"])
        self.assertEqual(stored[0]["data"], {"truncated": True, "bytes": stored[0]["data"]["bytes"]})
        self.assertGreater(stored[0]["data"]["bytes"], 300 * 1024)
        small = executors.WorkspaceLimits(**{**executors.PERSONAL_LIMITS.__dict__, "evidence_bytes": 20_000})
        with patch.object(executors, "PERSONAL_LIMITS", small):
            for batch in range(10):
                events = [{"run_id": run_id, "sequence": 2 + batch * 10 + n, "timestamp": "t", "kind": "status", "data": {"pad": "y" * 500}} for n in range(10)]
                self.assertEqual(self.browser().post("/api/worker/sync", headers=token, json={"runs": [], "events": events}).status_code, 200)
            with self.store.connect() as db:
                total, recorded = db.execute("SELECT (SELECT SUM(length(CAST(event AS BLOB))) FROM worker_events WHERE worker=?), evidence_bytes FROM worker_scope WHERE worker=?",
                                             (machine["id"], machine["id"])).fetchone()
                newest = db.execute("SELECT MAX(sequence), MIN(sequence) FROM worker_events WHERE worker=?", (machine["id"],)).fetchone()
            self.assertLessEqual(recorded, 20_000)
            self.assertEqual(total, recorded)
            self.assertEqual(newest[0], 101)  # The newest evidence is kept; the oldest is pruned first.
            self.assertGreater(newest[1], 1)

    def test_operator_workspace_migration_preserves_existing_machines(self):
        legacy_home = self.root / "legacy"; legacy_home.mkdir()
        db = sqlite3.connect(legacy_home / "state.sqlite3")
        db.executescript("""
            CREATE TABLE worker_pairs(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE workers(id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, seen REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, metadata TEXT NOT NULL);
            CREATE TABLE worker_commands(id TEXT PRIMARY KEY, worker TEXT NOT NULL, request TEXT NOT NULL, response TEXT, created REAL NOT NULL);
            CREATE TABLE worker_cache(worker TEXT NOT NULL, path TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(worker,path));
            CREATE TABLE worker_events(worker TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY(worker,run_id,sequence));""")
        worker, token = str(uuid.uuid4()), "legacy-worker-token"
        db.execute("INSERT INTO workers VALUES(?,?,?,?,0,?)", (worker, "Legacy Mac", hashlib.sha256(token.encode()).hexdigest(), time.time(), json.dumps({"platform": "darwin", "workspaces": ["/project"]})))
        db.execute("INSERT INTO worker_events VALUES(?,?,?,?)", (worker, str(uuid.uuid4()), 1, '{"kind":"status"}'))
        db.commit(); db.close()
        store = Store(legacy_home)
        app = create_app(store, token=KEY, deployment=self.make_deployment(), http_transport=httpx.MockTransport(self.github))
        operator = self.browser(app); operator.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN})
        self.assertEqual([m["name"] for m in operator.get("/api/executors").json()], ["Legacy Mac"])
        self.assertEqual(app.state.executors.authenticate(token), worker)
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT evidence_bytes FROM worker_scope WHERE worker=?", (worker,)).fetchone()[0], len('{"kind":"status"}'))
        personal = self.sign_in(user(903, "ida"), self.browser(app))[0]
        self.assertEqual(personal.get("/api/executors").json(), [])
        self.assertEqual(personal.get(f"/api/executors/{worker}/proxy/runs").status_code, 404)
        # Re-running the migration is a no-op.
        ExecutorHub(Store(legacy_home))
        self.assertEqual(len(operator.get("/api/executors").json()), 1)

    def test_chunked_and_declared_bodies_are_bounded(self):
        client = self.signed_in(user(904, "joan"))
        oversized = b"{" + b" " * (3 * 1024 * 1024) + b"}"
        declared = client.post("/api/executors/pair", headers={"Origin": ORIGIN}, content=oversized)
        self.assertEqual(declared.status_code, 413)
        def chunks():
            for _ in range(48):
                yield b" " * 65536
        chunked = client.post("/api/executors/pair", headers={"Origin": ORIGIN}, content=chunks())
        self.assertEqual(chunked.status_code, 413)
        self.assertEqual(client.post("/api/executors/pair", headers={"Origin": ORIGIN, "Content-Length": "abc"}).status_code, 400)
        # Worker messages keep their larger, explicit bound.
        machine = self.pair(client)
        events = [{"run_id": str(uuid.uuid4()), "sequence": 1, "timestamp": "t", "kind": "status", "data": {"pad": "z" * (3 * 1024 * 1024)}}]
        self.assertEqual(self.browser().post("/api/worker/sync", headers={"Authorization": "Bearer " + machine["token"]}, json={"runs": [], "events": events}).status_code, 200)

    def test_durable_operator_sign_in_throttle(self):
        client = self.browser()
        for _ in range(20):
            self.assertEqual(client.post("/api/session", json={"token": "wrong-key"}, headers={"Origin": ORIGIN}).status_code, 401)
        restarted = self.browser(create_app(self.store, token=KEY, deployment=self.deployment))
        self.assertEqual(restarted.post("/api/session", json={"token": "wrong-key"}, headers={"Origin": ORIGIN}).status_code, 429)
        self.assertEqual(restarted.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN}).status_code, 200)


class HardeningTests(HostedFixture):
    """Regressions for the adversarial review of the accounts change."""

    def test_crafted_host_headers_cannot_shift_the_checked_path(self):
        personal = self.signed_in(user(1001, "kim"))
        anonymous = self.browser()
        for host in ("runtime.example.com:443/api/health?", "runtime.example.com/api/session#", "runtime.example.com:80@evil",
                     "runtime.example.com:443/api/executors?x=", "runtime.example.com:", "runtime.example.com:1:2", " runtime.example.com"):
            for client in (personal, anonymous):
                for path in ("/api/runs", "/api/providers", "/api/runs/" + str(uuid.uuid4()) + "/patch"):
                    response = client.get(path, headers={"Host": host})
                    self.assertEqual(response.status_code, 403, (host, path, response.text))
        # Well-formed hosts with ports still work.
        self.assertEqual(personal.get("/api/session", headers={"Host": "runtime.example.com:443"}).status_code, 200)

    def test_answered_commands_leave_no_payload_behind(self):
        client = self.signed_in(user(1002, "lee"))
        machine = self.pair(client)
        hub = self.app.state.executors
        workspace = client.get("/api/session").json()["workspace"]["id"]
        async def roundtrip(method, path, body):
            pending = asyncio.create_task(hub.request(machine["id"], method, path, "", body, workspace=workspace, timeout=5))
            await asyncio.sleep(.05)
            for command in hub.pending(machine["id"]):
                hub.complete(machine["id"], command["id"], {"status": 200, "body": {"echo": len(json.dumps(command["body"] or {}))}, "content_type": "application/json"})
            return await pending
        big = {"note": "x" * (2 * 1024 * 1024)}
        for _ in range(5):
            self.assertEqual(asyncio.run(roundtrip("POST", "/api/feedback/baseline", big))["status"], 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands").fetchone()[0], 0)
        # Answers nobody collected are dropped after five minutes.
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,?,?)",
                       (str(uuid.uuid4()), machine["id"], "{}", json.dumps({"status": 200, "body": "late"}), time.time() - 301))
        hub.pending(machine["id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands").fetchone()[0], 0)

    def test_queued_bytes_and_relay_rate_are_bounded(self):
        client = self.signed_in(user(1003, "max"))
        machine = self.pair(client)
        workspace = client.get("/api/session").json()["workspace"]["id"]
        hub = self.app.state.executors
        small = executors.WorkspaceLimits(**{**executors.PERSONAL_LIMITS.__dict__, "pending_bytes": 1024 * 1024, "relayed_per_window": 3})
        with patch.object(executors, "PERSONAL_LIMITS", small):
            with self.store.connect() as db:
                db.execute("INSERT INTO worker_commands(id,worker,request,response,created) VALUES(?,?,?,NULL,?)",
                           (str(uuid.uuid4()), machine["id"], "x" * (1024 * 1024 - 10), time.time()))
            with self.assertRaises(Exception) as full:
                asyncio.run(hub.request(machine["id"], "POST", "/api/feedback/baseline", "", {"n": 1}, workspace=workspace, timeout=1))
            self.assertEqual(full.exception.status_code, 429)
            for _ in range(2):
                with self.assertRaises(Exception): asyncio.run(hub.request(machine["id"], "GET", "/api/runs", "", None, workspace=workspace, timeout=.2))
            with self.assertRaises(Exception) as limited:
                asyncio.run(hub.request(machine["id"], "GET", "/api/runs", "", None, workspace=workspace, timeout=.2))
            self.assertEqual(limited.exception.status_code, 429)
            self.assertIn("five minutes", limited.exception.detail)

    def test_anonymous_traffic_cannot_block_sign_in_or_pairing(self):
        # A visitor's flow started before a flood of anonymous starts still completes: pending flows hold no server state.
        visitor = self.browser()
        start = visitor.post("/api/auth/github/start", headers={"Origin": ORIGIN})
        query = parse_qs(urlsplit(start.json()["url"]).query)
        with self.store.connect() as db:
            before = db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], self.store.path.stat().st_size
        anonymous = self.browser()
        for _ in range(650):
            self.assertEqual(anonymous.post("/api/auth/github/start", headers={"Origin": ORIGIN}).status_code, 200)
        with self.store.connect() as db:
            self.assertEqual((db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], self.store.path.stat().st_size), before)
        code = self.github.issue(user(1004, "noor"), query["code_challenge"][0])
        finished = visitor.get("/api/auth/github/callback", params={"code": code, "state": query["state"][0]}, follow_redirects=False)
        self.assertEqual(finished.headers["location"], "/")
        # A forged or altered flow cookie is refused.
        forged = self.browser()
        forged.cookies.set("parallax_oauth", "A" * 43 + "." + str(int(time.time()) + 300) + "." + "B" * 43)
        refused = forged.get("/api/auth/github/callback", params={"code": "c", "state": "C" * 43}, follow_redirects=False)
        self.assertEqual(refused.headers["location"], "/?auth_error=expired")
        for _ in range(150):
            self.assertEqual(anonymous.post("/api/worker/connect", json={"code": "x" * 32, "name": "M", "platform": "darwin", "workspaces": ["/p"]}).status_code, 401)
        client = self.signed_in(user(1005, "omar"))
        self.pair(client)  # A valid code still pairs.

    def test_restarted_worker_replay_does_not_displace_newer_evidence(self):
        client = self.signed_in(user(1006, "pat"))
        machine = self.pair(client)
        token = {"Authorization": "Bearer " + machine["token"]}
        run_id = str(uuid.uuid4())
        def batch(start, count):
            return [{"run_id": run_id, "sequence": start + n, "timestamp": "t", "kind": "status", "data": {"pad": "y" * 500}} for n in range(count)]
        small = executors.WorkspaceLimits(**{**executors.PERSONAL_LIMITS.__dict__, "evidence_bytes": 20_000})
        with patch.object(executors, "PERSONAL_LIMITS", small):
            for start in range(1, 101, 10):
                self.browser().post("/api/worker/sync", headers=token, json={"runs": [], "events": batch(start, 10)})
            with self.store.connect() as db:
                kept = [r[0] for r in db.execute("SELECT sequence FROM worker_events WHERE worker=? ORDER BY sequence", (machine["id"],))]
            # The worker restarts and replays its whole history from the beginning.
            for start in range(1, 101, 10):
                self.browser().post("/api/worker/sync", headers=token, json={"runs": [], "events": batch(start, 10)})
            with self.store.connect() as db:
                after = [r[0] for r in db.execute("SELECT sequence FROM worker_events WHERE worker=? ORDER BY sequence", (machine["id"],))]
        self.assertEqual(after, kept)
        self.assertEqual(after[-1], 100)

    def test_previous_release_can_still_write_after_migration(self):
        self.pair(self.signed_in(user(1007, "quinn")))
        with self.store.connect() as db:  # The 4f1b5ec release's positional statements.
            db.execute("INSERT INTO worker_pairs VALUES(?,?)", ("legacy-hash", time.time() + 300))
            db.execute("INSERT INTO workers VALUES(?,?,?,?,0,?)", ("legacy-worker", "Old", "hash", time.time(), "{}"))
            db.execute("INSERT INTO worker_cache VALUES(?,?,?)", ("legacy-worker", "/api/runs", "{}"))
        operator = self.browser(); operator.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN})
        self.assertIn("legacy-worker", [m["id"] for m in operator.get("/api/executors").json()])

    def test_low_disk_keeps_machines_controllable(self):
        client = self.signed_in(user(1008, "rae"))
        machine = self.pair(client)
        workspace = client.get("/api/session").json()["workspace"]["id"]
        hub = self.app.state.executors
        full = type("Usage", (), {"free": 1024})()
        with patch("parallax.executors.shutil.disk_usage", return_value=full):
            with self.store.connect() as db: db.execute("UPDATE workers SET seen=0 WHERE id=?", (machine["id"],))
            reply = self.browser().post("/api/worker/sync", headers={"Authorization": "Bearer " + machine["token"]},
                                        json={"runs": [], "events": [{"run_id": str(uuid.uuid4()), "sequence": 1, "timestamp": "t", "kind": "status", "data": {}}]})
            self.assertEqual(reply.json(), {"ok": True, "stored": False})
            self.assertTrue(hub.worker(machine["id"], workspace)["online"])
            with self.assertRaises(Exception) as large:
                asyncio.run(hub.request(machine["id"], "POST", "/api/feedback/baseline", "", {"x": "y" * 70000}, workspace=workspace, timeout=.2))
            self.assertEqual(large.exception.status_code, 507)
            with self.assertRaises(Exception) as small:  # Small controls are still queued (and time out here only because no worker answers).
                asyncio.run(hub.request(machine["id"], "POST", "/api/runs/" + str(uuid.uuid4()) + "/cancel", "", None, workspace=workspace, timeout=.2))
            self.assertEqual(small.exception.status_code, 504)

    def test_client_disconnect_mid_body_is_answered(self):
        from parallax.server import BodyLimit
        sent = []
        async def app(scope, receive, send): raise AssertionError("must not route")
        async def receive(): return {"type": "http.disconnect"}
        async def send(message): sent.append(message)
        asyncio.run(BodyLimit(app, lambda path: 1024)({"type": "http", "path": "/api/session", "headers": []}, receive, send))
        self.assertEqual(sent[0]["status"], 400)

    def test_machine_listing_names_its_workspace(self):
        client = self.signed_in(user(1009, "sam"))
        workspace = client.get("/api/session").json()["workspace"]["id"]
        self.assertEqual(client.get("/api/executors").headers["x-parallax-workspace"], workspace)


class RollbackAndRaceTests(HostedFixture):
    """Schema transitions in both directions, and requests racing revocation."""

    def operator(self, app=None):
        client = self.browser(app); client.post("/api/session", json={"token": KEY}, headers={"Origin": ORIGIN})
        return client

    def test_previous_release_sees_neither_personal_machines_nor_their_codes(self):
        client = self.signed_in(user(1101, "tess"))
        machine = self.pair(client)
        code = client.post("/api/executors/pair", headers={"Origin": ORIGIN}).json()["code"]
        operator_code = self.operator().post("/api/executors/pair", headers={"Origin": ORIGIN}).json()["code"]
        token_hash = hashlib.sha256(machine["token"].encode()).hexdigest()
        with self.store.connect() as db:  # The 4f1b5ec release's own queries.
            self.assertNotIn(machine["id"], [r[0] for r in db.execute("SELECT id FROM workers WHERE revoked=0")])
            self.assertIsNone(db.execute("SELECT id FROM workers WHERE token_hash=? AND revoked=0", (token_hash,)).fetchone())
            pairs = [r[0] for r in db.execute("SELECT hash FROM worker_pairs WHERE expires>=?", (time.time(),))]
        self.assertNotIn(hashlib.sha256(code.encode()).hexdigest(), pairs)
        self.assertIn(hashlib.sha256(operator_code.encode()).hexdigest(), pairs)
        # This release still lists, authenticates and pairs them normally.
        self.assertEqual([m["id"] for m in client.get("/api/executors").json()], [machine["id"]])
        self.assertEqual(self.app.state.executors.authenticate(machine["token"]), machine["id"])
        second = self.browser().post("/api/worker/connect", json={"code": code, "name": "Two", "platform": "darwin", "workspaces": ["/p"]})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(client.get("/api/executors").json()), 2)
        self.assertEqual(self.operator().get("/api/executors").json(), [])
        # Disconnecting a personal machine revokes its real token.
        self.assertEqual(client.delete(f"/api/executors/{machine['id']}", headers={"Origin": ORIGIN}).status_code, 200)
        with self.assertRaises(Exception):
            self.app.state.executors.authenticate(machine["token"])

    def test_databases_from_earlier_builds_upgrade_without_exposing_personal_machines(self):
        home = self.root / "prerelease"; home.mkdir()
        db = sqlite3.connect(home / "state.sqlite3")
        db.executescript("""
            CREATE TABLE worker_pairs(hash TEXT PRIMARY KEY, expires REAL NOT NULL, workspace TEXT NOT NULL DEFAULT 'owner');
            CREATE TABLE workers(id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, seen REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0, metadata TEXT NOT NULL, workspace TEXT NOT NULL DEFAULT 'owner');
            CREATE TABLE worker_commands(id TEXT PRIMARY KEY, worker TEXT NOT NULL, request TEXT NOT NULL, response TEXT, created REAL NOT NULL);
            CREATE TABLE worker_cache(worker TEXT NOT NULL, path TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(worker,path));
            CREATE TABLE worker_events(worker TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY(worker,run_id,sequence));
            CREATE INDEX worker_scope ON workers(workspace, revoked);
            CREATE INDEX worker_pair_scope ON worker_pairs(workspace, expires);""")
        rows = [("personal-mac", "personal-token", "ws-personal"), ("operator-mac", "operator-token", "owner")]
        for identifier, token, workspace in rows:
            db.execute("INSERT INTO workers VALUES(?,?,?,?,0,?,?)", (identifier, identifier, hashlib.sha256(token.encode()).hexdigest(), time.time(), "{}", workspace))
        db.execute("INSERT INTO worker_pairs VALUES(?,?,?)", ("personal-code-hash", time.time() + 300, "ws-personal"))
        db.commit(); db.close()
        store = Store(home)
        hub = ExecutorHub(store)
        self.assertEqual([m["id"] for m in hub.workers("ws-personal")], ["personal-mac"])
        self.assertEqual([m["id"] for m in hub.workers(OWNER_WORKSPACE)], ["operator-mac"])
        self.assertEqual((hub.authenticate("personal-token"), hub.authenticate("operator-token")), ("personal-mac", "operator-mac"))
        with store.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT id FROM workers WHERE revoked=0")], ["operator-mac"])
            self.assertEqual(conn.execute("SELECT workspace FROM worker_pair_scope WHERE hash='personal-code-hash'").fetchone()[0], "ws-personal")
            self.assertIsNone(conn.execute("SELECT 1 FROM worker_pairs WHERE hash='personal-code-hash'").fetchone())
        # The previous build of this release (side tables without the hiding columns) upgrades the same way.
        home = self.root / "earlier"; home.mkdir()
        earlier = Store(home)
        ExecutorHub(earlier)
        with earlier.connect() as conn:
            conn.executescript("""DROP TABLE worker_scope; DROP TABLE worker_pair_scope;
                CREATE TABLE worker_scope(worker TEXT PRIMARY KEY, workspace TEXT NOT NULL, evidence_bytes INTEGER NOT NULL DEFAULT 0, pruned_through INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE worker_pair_scope(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL);""")
            conn.execute("INSERT INTO workers VALUES(?,?,?,?,0,?)", ("older-personal", "Older", hashlib.sha256(b"older-token").hexdigest(), time.time(), "{}"))
            conn.execute("INSERT INTO worker_scope(worker,workspace) VALUES('older-personal','ws-older')")
        hub = ExecutorHub(Store(home))
        ExecutorHub(Store(home))  # Idempotent.
        self.assertEqual(hub.authenticate("older-token"), "older-personal")
        self.assertEqual([m["id"] for m in hub.workers("ws-older")], ["older-personal"])
        with earlier.connect() as conn:
            self.assertEqual(conn.execute("SELECT revoked,token_hash FROM workers WHERE id='older-personal'").fetchone()[:], (1, "scoped:older-personal"))

    def test_requests_racing_revocation_or_account_deletion_are_refused(self):
        client = self.signed_in(user(1102, "uma"))
        workspace = client.get("/api/session").json()["workspace"]["id"]
        machine = self.pair(client)
        hub = self.app.state.executors
        worker = hub.authenticate(machine["token"])  # Authenticated, then the account is deleted before the handler runs.
        hub.purge_workspace(workspace)
        event = [{"run_id": str(uuid.uuid4()), "sequence": 1, "kind": "status", "data": {}}]
        for call in (lambda: hub.sync(worker, [], event), lambda: hub.pending(worker), lambda: hub.complete(worker, "x", {"status": 200})):
            with self.assertRaises(Exception) as refused:
                call()
            self.assertEqual(refused.exception.status_code, 401)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_scope WHERE worker=?", (worker,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_events WHERE worker=?", (worker,)).fetchone()[0], 0)

    def test_uncollected_answers_are_bounded_and_expire_for_offline_machines(self):
        client = self.signed_in(user(1103, "val"))
        workspace = client.get("/api/session").json()["workspace"]["id"]
        machine = self.pair(client)
        hub = self.app.state.executors
        large = {"status": 200, "content_type": "application/json", "body": {"blob": "x" * (7 * 1024 * 1024)}}
        kept = []
        for _ in range(6):  # Each Studio request times out before the machine answers.
            with self.assertRaises(Exception):
                asyncio.run(hub.request(machine["id"], "GET", "/api/runs", "", None, workspace=workspace, timeout=.05))
            command = hub.pending(machine["id"])[-1]
            hub.complete(machine["id"], command["id"], large)
            with self.store.connect() as db:
                kept.append(db.execute("SELECT response FROM worker_commands WHERE id=?", (command["id"],)).fetchone()[0])
        self.assertTrue(json.loads(kept[0])["status"] == 200)
        self.assertEqual(json.loads(kept[-1])["status"], 507)
        with self.store.connect() as db:
            held = db.execute("SELECT SUM(length(CAST(response AS BLOB))) FROM worker_commands WHERE worker=?", (machine["id"],)).fetchone()[0]
        self.assertLessEqual(held, executors.PERSONAL_LIMITS.pending_bytes + 4096)
        # The machine goes offline for good; another workspace's activity still sweeps its answers.
        other = self.pair(self.signed_in(user(1104, "wes")))
        with patch("parallax.executors.time.time", return_value=time.time() + 301):
            hub.pending(other["id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands WHERE worker=?", (machine["id"],)).fetchone()[0], 0)

    def test_wrong_bearer_keys_share_the_sign_in_throttle(self):
        anonymous = self.browser()
        statuses = [anonymous.get("/api/runs", headers={"Authorization": "Bearer wrong-key-" + str(n)}).status_code for n in range(22)]
        self.assertEqual(statuses[:20], [401] * 20)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(anonymous.get("/api/session", headers={"Authorization": "Bearer " + KEY}).status_code, 200)

    def test_live_event_streams_end_with_their_session(self):
        client = self.signed_in(user(1105, "xia"))
        machine = self.pair(client)
        run_id = str(uuid.uuid4())
        self.browser().post("/api/worker/sync", headers={"Authorization": "Bearer " + machine["token"]},
                            json={"runs": [], "events": [{"run_id": run_id, "sequence": 1, "timestamp": "t", "kind": "status", "data": {}}]})
        accounts = self.app.state.accounts
        real, calls = accounts.principal, []
        def principal(token):
            calls.append(token)
            return real(token) if len(calls) == 1 else None  # Valid when the stream opens, signed out afterwards.
        with patch.object(accounts, "principal", side_effect=principal), patch("parallax.server.asyncio.sleep", new=AsyncMock()):
            stream = client.get(f"/api/executors/{machine['id']}/proxy/runs/{run_id}/events")
        self.assertEqual(stream.status_code, 200)
        self.assertIn('"sequence": 1', stream.text)
        self.assertGreaterEqual(len(calls), 2)

    def test_unauthenticated_pairing_bodies_are_small(self):
        body = {"code": "x" * 32, "name": "M", "platform": "darwin", "workspaces": ["/" + "p" * 200_000]}
        self.assertEqual(self.browser().post("/api/worker/connect", json=body).status_code, 413)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = {"PARALLAX_ACCESS_TOKEN": KEY, "PARALLAX_STUDIO_ORIGINS": ORIGIN, "PARALLAX_ALLOWED_HOSTS": "runtime.example.com",
                     "PARALLAX_PROJECTS_ROOT": self.temp.name}

    def load(self, **extra):
        with patch.dict(os.environ, {**self.base, **extra}, clear=True):
            return Deployment.from_env()

    def test_repetitive_access_keys_are_refused(self):
        with patch.dict(os.environ, {**self.base, "PARALLAX_ACCESS_TOKEN": "ab" * 20}, clear=True):
            with self.assertRaisesRegex(ValueError, "repetitive"):
                Deployment.from_env()

    def test_github_configuration_is_explicit_and_redacted(self):
        plain = self.load()
        self.assertIsNone(plain.github)
        self.assertEqual(plain.public_origin, ORIGIN)
        self.assertIsNone(plain.github_redirect)
        configured = self.load(PARALLAX_GITHUB_CLIENT_ID="Iv1.abcdef123", PARALLAX_GITHUB_CLIENT_SECRET=SECRET, PARALLAX_OWNER_GITHUB_IDS="111611815, 42")
        self.assertEqual(configured.github_redirect, ORIGIN + "/api/auth/github/callback")
        self.assertEqual(configured.owner_github_ids, frozenset({111611815, 42}))
        self.assertNotIn(SECRET, repr(configured))
        self.assertNotIn(KEY, repr(configured))
        for extra in ({"PARALLAX_GITHUB_CLIENT_ID": "Iv1.abcdef123"}, {"PARALLAX_GITHUB_CLIENT_SECRET": SECRET},
                      {"PARALLAX_GITHUB_CLIENT_ID": "bad id!", "PARALLAX_GITHUB_CLIENT_SECRET": SECRET},
                      {"PARALLAX_OWNER_GITHUB_IDS": "yosef"}, {"PARALLAX_SIGNUP": "everyone"}, {"PARALLAX_MAX_ACCOUNTS": "0"},
                      {"PARALLAX_PUBLIC_ORIGIN": "https://other.example.com"}):
            with self.assertRaises(ValueError, msg=str(extra)):
                self.load(**extra)
        two = {"PARALLAX_STUDIO_ORIGINS": ORIGIN + ",https://preview.example.com"}
        self.assertIsNone(self.load(**two).public_origin)
        with self.assertRaises(ValueError):
            self.load(**two, PARALLAX_GITHUB_CLIENT_ID="Iv1.abcdef123", PARALLAX_GITHUB_CLIENT_SECRET=SECRET)
        chosen = self.load(**two, PARALLAX_PUBLIC_ORIGIN=ORIGIN, PARALLAX_GITHUB_CLIENT_ID="Iv1.abcdef123", PARALLAX_GITHUB_CLIENT_SECRET=SECRET)
        self.assertEqual(chosen.github_redirect, ORIGIN + "/api/auth/github/callback")

    def test_cloud_entry_point_scrubs_hosted_secrets(self):
        from parallax import cloud
        env = {**self.base, "PARALLAX_HOME": str(Path(self.temp.name) / "state"), "PARALLAX_GITHUB_CLIENT_ID": "Iv1.abcdef123",
               "PARALLAX_GITHUB_CLIENT_SECRET": SECRET, "PORT": "8099"}
        captured = {}
        def run(app, **kwargs):
            captured["app"], captured["env"] = app, dict(os.environ)
        with patch.dict(os.environ, env, clear=True), patch("parallax.cloud.uvicorn.run", side_effect=run), patch("builtins.print"):
            cloud.main()
        self.assertNotIn("PARALLAX_ACCESS_TOKEN", captured["env"])
        self.assertNotIn("PARALLAX_GITHUB_CLIENT_SECRET", captured["env"])
        self.assertTrue(captured["app"].state.accounts.deployment.github)


if __name__ == "__main__":
    unittest.main()
