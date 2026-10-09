"""Real JWT signatures, fake Supabase OAuth, and real account/relay isolation."""
import asyncio
import json
import time
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from test_supabase_auth import FakeSupabase, SupabaseFixture, ORIGIN, RUNTIME, PROJECT, KEY
from parallax.accounts import SESSION_COOKIE
from parallax.mcp_oauth import CONSENT_COOKIE, CONSENT_FLOW_COOKIE, redirect_url
from parallax.mcp_remote import RESOURCE_PATH, project_id

PASSWORD = "correct horse battery"


class OAuthSupabase(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = "test-signing-key"
        self.authorizations = {}
        self.decisions = []
        self.revoked_grants = []
        self.jwks_requests = 0
        self.auto_approved = False

    def request_authorization(self, name="Review app"):
        identifier, client = str(uuid.uuid4()), str(uuid.uuid4())
        self.authorizations[identifier] = {"client": {"id":client,"name":name}, "redirect_uri":"https://client.example/callback"}
        return identifier, client

    def __call__(self, request):
        path = request.url.path.removeprefix("/auth/v1")
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if path == "/.well-known/jwks.json":
            self.jwks_requests += 1
            key = jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx.Response(200, json={"keys":[{**key,"kid":self.kid,"alg":"ES256","use":"sig"}]})
        if path.startswith("/oauth/") or path == "/user/oauth/grants":
            user = self.tokens.get(token)
            if not user or token in self.revoked:
                return httpx.Response(401, json={})
            if path == "/user/oauth/grants" and request.method == "DELETE":
                self.revoked_grants.append(request.url.params["client_id"])
                self.auto_approved = False
                return httpx.Response(204)
            identifier = path.split("/")[3]
            details = self.authorizations.get(identifier)
            if not details:
                return httpx.Response(404, json={})
            if request.method == "GET":
                if self.auto_approved:
                    return httpx.Response(200, json={"redirect_url":details["redirect_uri"] + "?code=existing"})
                return httpx.Response(200, json={**details,"authorization_id":identifier,
                    "user":{"id":user,"email":self.users[user]["email"]},"scope":"openid email profile"})
            if request.method == "POST" and path.endswith("/consent"):
                action = json.loads(request.content)["action"]
                self.decisions.append((identifier, action))
                return httpx.Response(200, json={"redirect_url":details["redirect_uri"] + ("?code=approved" if action == "approve" else "?error=access_denied")})
        return super().__call__(request)

    def token(self, user, client, **changes):
        claims = {"sub":user,"client_id":client,"iss":PROJECT + "/auth/v1","aud":ORIGIN + "/api/mcp",
            "iat":int(time.time()),"exp":int(time.time()) + 300,"role":"authenticated","is_anonymous":False,
            "session_id":str(uuid.uuid4())}
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="ES256", headers={"kid":self.kid})


class RemoteFixture(SupabaseFixture):
    def setUp(self):
        super().setUp()
        self.supabase = OAuthSupabase()
        self.app = self.make_app(remote_mcp=True, openai_challenge="public-verification-token")
        self.remote = self.app.state.remote_mcp

    def consent_login(self, email="ada@example.com", name="Review app"):
        user = next((uid for uid, u in self.supabase.users.items() if u["email"] == email), None)
        user = user or self.supabase._create(email, PASSWORD, confirmed=True)
        identifier, client_id = self.supabase.request_authorization(name)
        browser = self.browser()
        result = self.post(browser, "/api/oauth/password", {"authorization_id":identifier,"email":email,"password":PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)
        browser.consent_identifier = identifier
        return browser, identifier, client_id, user

    def details(self, browser):
        return browser.get("/api/oauth/consent", params={"authorization_id":getattr(browser, "consent_identifier", "")})

    def post(self, client, path, body):
        if path == "/api/oauth/consent":
            return client.post(path, params={"authorization_id":getattr(client, "consent_identifier", "")}, json=body, headers={"Origin":ORIGIN})
        return super().post(client, path, body)

    def connected(self, email="ada@example.com"):
        browser, identifier, client_id, user = self.consent_login(email)
        details = self.details(browser)
        self.assertEqual(details.status_code, 200, details.text)
        approval = self.post(browser, "/api/oauth/consent", {"approve":True})
        self.assertEqual(approval.status_code, 200, approval.text)
        return browser, self.supabase.token(user, client_id), user, client_id

    def rpc(self, token, method="tools/list", arguments=None, name=None, **options):
        body = {"jsonrpc":"2.0","id":1,"method":method}
        if name:
            body["params"] = {"name":name,"arguments":arguments or {}}
        elif arguments is not None:
            body["params"] = arguments
        return self.browser().post("/api/mcp", json=body, headers={"Authorization":"Bearer " + token, **options})

    def machine(self, browser, name="Laptop"):
        workspace = browser.get("/api/session").json()["workspace"]["id"]
        hub = self.app.state.executors
        worker = hub.connect(hub.pair(workspace)["code"], name, {"platform":"darwin","workspaces":["/Users/private/project"]})
        return worker["id"], workspace


class RemoteAuthenticationTests(RemoteFixture):
    def test_discovery_challenge_and_disabled_mode(self):
        browser = self.browser()
        for path in [RESOURCE_PATH, "/.well-known/oauth-protected-resource"]:
            response = browser.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["resource"], ORIGIN + "/api/mcp")
            self.assertEqual(response.json()["authorization_servers"], [PROJECT + "/auth/v1"])
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(browser.get("/.well-known/openai-apps-challenge").text, "public-verification-token")
        response = browser.post("/api/mcp", json={})
        self.assertEqual(response.status_code, 401)
        self.assertIn(ORIGIN + RESOURCE_PATH, response.headers["www-authenticate"])
        disabled = self.browser(self.make_app())
        self.assertEqual(disabled.get(RESOURCE_PATH).status_code, 404)
        self.assertEqual(disabled.post("/api/mcp", json={}).status_code, 404)

    def test_valid_signature_and_protocol(self):
        _, token, _, _ = self.connected()
        response = self.rpc(token, "initialize", {"protocolVersion":"2025-11-25","clientInfo":{"name":"test","version":"1"},"capabilities":{}})
        self.assertEqual(response.json()["result"]["protocolVersion"], "2025-11-25")
        tools = self.rpc(token).json()["result"]["tools"]
        self.assertEqual(len(tools), 8)
        annotations = {t["name"]: t["annotations"] for t in tools}
        self.assertTrue(annotations["start_build"]["destructiveHint"])
        self.assertFalse(annotations["start_review"]["readOnlyHint"])
        self.assertTrue(annotations["get_run"]["readOnlyHint"])
        self.assertEqual(self.supabase.jwks_requests, 1)
        self.assertEqual(self.rpc(token, "ping").json()["result"], {})
        self.assertEqual(self.browser().get("/api/mcp", headers={"Authorization":"Bearer " + token}).status_code, 405)

    def test_tokens_need_correct_issuer_audience_expiry_and_oauth_client(self):
        _, token, user, client = self.connected()
        changes = [{"aud":"authenticated"},{"aud":[ORIGIN + "/api/mcp"]},{"iss":"https://attacker.example"},
            {"exp":int(time.time())-1},{"iat":int(time.time())+100},{"client_id":None},{"sub":str(uuid.uuid4())},
            {"role":"service_role"},{"is_anonymous":True},{"client_id":str(uuid.uuid4())}]
        for values in changes:
            with self.subTest(values=values):
                self.assertEqual(self.rpc(self.supabase.token(user, client, **values)).status_code, 401)
        foreign_key = ec.generate_private_key(ec.SECP256R1())
        claims = jwt.decode(token, options={"verify_signature":False})
        bad_signature = jwt.encode(claims, foreign_key, algorithm="ES256", headers={"kid":self.supabase.kid})
        self.assertEqual(self.rpc(bad_signature).status_code, 401)
        symmetric = jwt.encode(claims, "a"*32, algorithm="HS256", headers={"kid":self.supabase.kid})
        self.assertEqual(self.rpc(symmetric).status_code, 401)

    def test_cookies_and_operator_keys_do_not_authorize_remote_tools(self):
        browser, _, _, _ = self.connected()
        self.assertEqual(browser.post("/api/mcp", json={}).status_code, 401)
        for _ in range(25):
            self.assertEqual(self.rpc(KEY).status_code, 401)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rate_events WHERE bucket='operator-sign-in-failure'").fetchone()[0], 0)

    def test_host_origin_and_body_limits_still_apply(self):
        _, token, _, _ = self.connected()
        self.assertEqual(self.rpc(token, Origin="https://evil.example").status_code, 403)
        self.assertEqual(self.rpc(token, Host="evil.example").status_code, 403)
        response = self.browser().post("/api/mcp", content=b"x"*65537, headers={"Authorization":"Bearer " + token,"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 413)

    def test_revocation_disable_and_deletion_block_existing_tokens(self):
        browser, token, user, client = self.connected()
        self.assertEqual(self.rpc(token).status_code, 200)
        response = browser.delete("/api/oauth/grants/" + client, headers={"Origin":ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rpc(token).status_code, 401)
        self.assertEqual(browser.get("/api/oauth/grants").json(), [])
        other, token2, _, _ = self.connected("other@example.com")
        with self.store.connect() as db:
            db.execute("UPDATE accounts SET disabled=1 WHERE email='other@example.com'")
        self.assertEqual(self.rpc(token2).status_code, 401)
        self.assertEqual(browser.delete("/api/account?confirm=ada@example.com", headers={"Origin":ORIGIN}).status_code, 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mcp_grants WHERE client=?", (client,)).fetchone()[0], 0)

    def test_unknown_keys_are_rate_limited_and_rotation_is_refreshed(self):
        _, token, user, client = self.connected()
        self.assertEqual(self.rpc(token).status_code, 200)
        self.supabase.key = ec.generate_private_key(ec.SECP256R1())
        self.supabase.kid = "rotated-key"
        rotated = self.supabase.token(user, client)
        for _ in range(4):
            self.assertEqual(self.rpc(rotated).status_code, 401)
        self.assertEqual(self.supabase.jwks_requests, 1)
        self.remote.refresh_after = 0
        self.assertEqual(self.rpc(rotated).status_code, 200)
        self.assertEqual(self.supabase.jwks_requests, 2)


class ConsentTests(RemoteFixture):
    def test_password_consent_is_bound_single_use_and_does_not_expose_tokens(self):
        browser, identifier, client, _ = self.consent_login()
        cookies = dict(browser.cookies)
        self.assertIn(CONSENT_COOKIE, cookies)
        self.assertIn(SESSION_COOKIE, cookies)
        self.assertEqual(self.post(browser, "/api/oauth/consent", {"approve":True}).status_code, 409)
        details = self.details(browser)
        self.assertEqual(details.json()["client"]["id"], client)
        stolen = self.browser()
        stolen.cookies.set(CONSENT_COOKIE, cookies[CONSENT_COOKIE])
        self.assertEqual(self.details(stolen).status_code, 401)
        result = self.post(browser, "/api/oauth/consent", {"approve":True})
        self.assertEqual(result.json()["redirect_url"], "https://client.example/callback?code=approved")
        self.assertEqual(self.post(browser, "/api/oauth/consent", {"approve":True}).status_code, 401)
        self.assertEqual(self.supabase.decisions, [(identifier, "approve")])
        self.assertEqual(self.remote.consent.pending, {})
        self.assertEqual(set(self.supabase.tokens), self.supabase.revoked)
        data = self.store.path.read_bytes() if hasattr(self.store, "path") else b""
        for token in self.supabase.tokens:
            self.assertNotIn(token, details.text + result.text + json.dumps(cookies))
            self.assertNotIn(token.encode(), data)

    def test_denial_does_not_create_a_grant(self):
        browser, identifier, _, _ = self.consent_login()
        self.details(browser)
        response = self.post(browser, "/api/oauth/consent", {"approve":False})
        self.assertIn("access_denied", response.json()["redirect_url"])
        self.assertEqual(browser.get("/api/oauth/grants").json(), [])
        self.assertEqual(self.supabase.decisions, [(identifier, "deny")])

    def test_expired_consent_and_signout_discard_provider_session(self):
        browser, _, _, _ = self.consent_login()
        for value in self.remote.consent.pending.values(): value["expires"] = time.time() - 1
        self.assertEqual(self.details(browser).status_code, 401)
        asyncio.run(self.remote.consent.sweep())
        self.assertFalse(self.remote.consent.pending)
        browser, _, _, _ = self.consent_login()
        self.assertEqual(browser.delete("/api/session", headers={"Origin":ORIGIN}).status_code, 200)
        self.assertFalse(self.remote.consent.pending)
        self.assertEqual(set(self.supabase.tokens), self.supabase.revoked)

    def test_social_consent_pkce_flow_and_tampered_binding(self):
        identifier, _, = self.supabase.request_authorization()
        browser = self.browser()
        response = self.post(browser, "/api/oauth/start", {"provider":"google","authorization_id":identifier})
        browser.consent_identifier = identifier
        self.assertEqual(response.status_code, 200)
        destination = self.supabase.authorize(response.json()["url"], provider="google")
        self.assertIn("/api/oauth/callback", destination)
        callback = browser.get(destination.replace(ORIGIN, ""), follow_redirects=False)
        self.assertEqual(callback.status_code, 303)
        self.assertIn(identifier, callback.headers["location"])
        self.assertEqual(self.details(browser).status_code, 200)
        self.assertEqual(browser.get("/api/oauth/consent", params={"authorization_id":str(uuid.uuid4())}).status_code, 401)
        attacker = self.browser()
        attacker.cookies.set(CONSENT_FLOW_COOKIE, "tampered")
        failure = attacker.get("/api/oauth/callback?code=stolen", follow_redirects=False)
        self.assertIn("auth_error=expired", failure.headers["location"])
        self.assertEqual(attacker.get("/api/session").status_code, 401)

    def test_cross_account_grants_and_consent_cannot_be_used(self):
        first, _, _, client = self.connected()
        second, _, _, _ = self.connected("other@example.com")
        second.delete("/api/oauth/grants/" + client, headers={"Origin":ORIGIN})
        self.assertEqual(first.get("/api/oauth/grants").json()[0]["client"], client)
        fresh, _, _, _ = self.consent_login()
        second.cookies.set(CONSENT_COOKIE, fresh.cookies[CONSENT_COOKIE], domain="runtime.example.com", path="/api/oauth")
        self.assertEqual(self.details(second).status_code, 401)

    def test_signin_requires_origin_and_operator_workspace_is_refused(self):
        identifier, _ = self.supabase.request_authorization()
        self.supabase._create("owner@example.com", PASSWORD, confirmed=True)
        body = {"authorization_id":identifier,"email":"owner@example.com","password":PASSWORD}
        self.assertEqual(self.browser().post("/api/oauth/password", json=body).status_code, 403)
        self.assertEqual(self.post(self.browser(), "/api/oauth/password", body).status_code, 403)
        self.assertFalse(self.remote.consent.pending)

    def test_reconnection_clears_upstream_revoked_consent(self):
        browser, _, _, client = self.connected()
        browser.delete("/api/oauth/grants/" + client, headers={"Origin":ORIGIN})
        self.supabase.auto_approved = True
        fresh, _, _, _ = self.consent_login()
        self.assertIn(client, self.supabase.revoked_grants)
        self.assertIn("client", self.details(fresh).json())

    def test_redirect_validation_and_auto_consent_token_cleanup(self):
        for value in ["javascript:alert(1)","http://evil.example/","https://user:pass@app.example/","https://app.example/#token","https://app.example/\\evil"]:
            with self.assertRaises(HTTPException): redirect_url(value)
        self.assertEqual(redirect_url("http://127.0.0.1:1455/callback?code=x"), "http://127.0.0.1:1455/callback?code=x")
        browser, _, _, _ = self.consent_login()
        self.supabase.auto_approved = True
        self.assertIn("redirect_url", self.details(browser).json())
        self.assertFalse(self.remote.consent.pending)


class RemoteToolTests(RemoteFixture):
    def test_machine_handles_hide_paths_and_other_workspaces(self):
        browser, token, _, _ = self.connected()
        own, _ = self.machine(browser)
        other, token2, _, _ = self.connected("other@example.com")
        foreign, _ = self.machine(other, "Other private computer")
        result = self.rpc(token, "tools/call", name="list_machines").json()["result"]
        self.assertEqual(result["structuredContent"]["machines"][0]["machine_id"], own)
        self.assertNotIn(foreign, json.dumps(result))
        self.assertNotIn("/Users", json.dumps(result))
        result = self.rpc(token2, "tools/call", name="get_run", arguments={"machine_id":own,"run_id":str(uuid.uuid4())}).json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("not found", result["content"][0]["text"])

    def test_all_tools_map_to_scoped_allowlisted_routes(self):
        browser, token, _, _ = self.connected()
        machine, workspace = self.machine(browser)
        run = str(uuid.uuid4())
        project = {"machine_id":machine,"project_id":project_id("/Users/private/project")}
        get = {"machine_id":machine,"run_id":run}
        cases = [("assess_project",project,"POST","/api/project/assess"),
            ("start_review",{**project,"prompt":"Review this project"},"POST","/api/runs"),
            ("start_build",{**project,"prompt":"Fix the parser","apply_changes":True},"POST","/api/runs"),
            ("get_run",get,"GET","/api/runs/" + run),
            ("list_runs",{"machine_id":machine},"GET","/api/runs"),
            ("stop_run",get,"POST","/api/runs/" + run + "/cancel")]
        for name, args, method, path in cases:
            with self.subTest(name=name):
                body = [] if name == "list_runs" else {"run_id":run,"status":"running","summary":"Checking"}
                with patch.object(self.app.state.executors, "request", AsyncMock(return_value={"status":200,"body":body})) as relay:
                    result = self.rpc(token, "tools/call", name=name, arguments=args).json()["result"]
                    self.assertFalse(result["isError"], result)
                    self.assertEqual(relay.call_args.args[:4], (machine, method, path, ""))
                    self.assertEqual(relay.call_args.kwargs["workspace"], workspace)
                    if name.startswith("start_"):
                        spec = relay.call_args.args[4]
                        self.assertEqual(spec["workspace"], "/Users/private/project")
                        self.assertEqual(spec["mode"], name.removeprefix("start_"))
                        self.assertEqual(spec["integrate"], name == "start_build")
                        self.assertNotIn(token, json.dumps(spec))

    def test_pairing_codes_belong_to_the_account_and_are_single_use(self):
        browser, token, _, _ = self.connected()
        data = self.rpc(token, "tools/call", name="pairing_instructions").json()["result"]["structuredContent"]
        hub = self.app.state.executors
        worker = hub.connect(data["code"], "Laptop", {"workspaces":["/project"]})
        workspace = browser.get("/api/session").json()["workspace"]["id"]
        self.assertEqual(hub.worker(worker["id"], workspace)["name"], "Laptop")
        with self.assertRaises(HTTPException): hub.connect(data["code"], "Again", {})

    def test_bad_projects_offline_workers_and_timeouts_are_actionable(self):
        browser, token, _, _ = self.connected()
        machine, _ = self.machine(browser)
        with patch.object(self.app.state.executors, "request", AsyncMock()) as relay:
            reply = self.rpc(token, "tools/call", name="assess_project", arguments={"machine_id":machine,"project_id":"0"*20}).json()["result"]
            self.assertTrue(reply["isError"])
            relay.assert_not_called()
        with self.store.connect() as db: db.execute("UPDATE workers SET seen=0 WHERE id=?", (machine,))
        args = {"machine_id":machine,"project_id":project_id("/Users/private/project"),"prompt":"Review"}
        reply = self.rpc(token, "tools/call", name="start_review", arguments=args).json()["result"]
        self.assertIn("offline", reply["content"][0]["text"])
        with patch.object(self.app.state.executors, "request", AsyncMock(side_effect=HTTPException(504, "internal request secret-id"))):
            reply = self.rpc(token, "tools/call", name="start_review", arguments=args).json()["result"]
            self.assertIn("list_runs", reply["content"][0]["text"])
            self.assertNotIn("secret-id", str(reply))

    def test_summaries_exclude_raw_records_and_mark_offline_cache(self):
        browser, token, _, _ = self.connected()
        machine, _ = self.machine(browser)
        run = str(uuid.uuid4())
        raw = {"run_id":run,"status":"completed","summary":"See /Users/private/project; api_key=should-not-leak",
            "spec":{"prompt":"private prompt"},"sessions":[{"token":"secret-provider-session"}],
            "diff":"private source code","artifacts":{"directory":"/tmp/private"},"checks":[{"name":"unit","ok":True,"output":"private log"}]}
        with patch.object(self.app.state.executors, "request", AsyncMock(return_value={"status":200,"body":raw,"offline":True})):
            result = self.rpc(token, "tools/call", name="get_run", arguments={"machine_id":machine,"run_id":run}).json()["result"]
        self.assertTrue(result["structuredContent"]["offline"])
        for private in ["/Users", "should-not-leak", "private prompt", "secret-provider-session", "private source code", "private log", "/tmp"]:
            self.assertNotIn(private, json.dumps(result))

    def test_rpc_validation_and_notifications_never_dispatch(self):
        _, token, _, _ = self.connected()
        browser = self.browser()
        headers = {"Authorization":"Bearer " + token,"Content-Type":"application/json"}
        for invalid in [[],{}, {"jsonrpc":"2.0","method":"tools/list","id":True}, {"jsonrpc":"2.0","method":"tools/call","id":1,"params":[]}]:
            self.assertEqual(browser.post("/api/mcp", json=invalid, headers=headers).json()["error"]["code"], -32600)
        self.assertEqual(browser.post("/api/mcp", content=b"{", headers=headers).json()["error"]["code"], -32700)
        self.assertEqual(self.rpc(token, "unknown").json()["error"]["code"], -32601)
        self.assertEqual(self.rpc(token, "tools/call", name="list_machines", arguments={"workspace":"owner"}).json()["error"]["code"], -32602)
        self.assertEqual(self.rpc(token, "tools/call", name="unknown").json()["error"]["code"], -32602)
        with patch.object(self.app.state.executors, "pair") as pair:
            notification = {"jsonrpc":"2.0","method":"tools/call","params":{"name":"pairing_instructions"}}
            self.assertEqual(browser.post("/api/mcp", json=notification, headers=headers).status_code, 202)
            pair.assert_not_called()
        self.assertEqual(self.rpc(token, **{"MCP-Protocol-Version":"nonsense"}).status_code, 400)


class RemoteWorkerIntegrationTests(RemoteFixture):
    def test_signed_mcp_request_completes_review_through_real_worker(self):
        from parallax.store import Store
        from parallax.worker import WorkerRuntime
        from test_engine import FakeRegistry, git

        browser, token, _, _ = self.connected()
        project = (self.root / "approved-project").resolve()
        project.mkdir()
        git(project, "init", "-q")
        git(project, "config", "user.name", "Test")
        git(project, "config", "user.email", "test@example.com")
        (project / "example.py").write_text("def add(a, b):\n    return a + b\n")
        git(project, "add", ".")
        git(project, "commit", "-qm", "baseline")
        scope = browser.get("/api/session").json()["workspace"]["id"]
        hub = self.app.state.executors
        machine = hub.connect(hub.pair(scope)["code"], "Review machine", {"workspaces":[str(project)]})["id"]
        local = Store(self.root / "worker-state")
        registry = FakeRegistry()

        async def exercise():
            async with WorkerRuntime(local, [project], registry=registry) as runtime, httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url=RUNTIME,
                headers={"Authorization":"Bearer " + token},
            ) as client:
                async def call(name, arguments):
                    request = asyncio.create_task(client.post("/api/mcp", json={"jsonrpc":"2.0","id":1,
                        "method":"tools/call","params":{"name":name,"arguments":{"machine_id":machine, **arguments}}}))
                    try:
                        for _ in range(200):
                            commands = hub.pending(machine)
                            if commands or request.done():
                                break
                            await asyncio.sleep(.01)
                        self.assertEqual(len(commands), 1, request.result().text if request.done() else "No worker command received")
                        self.assertNotIn(token, json.dumps(commands))
                        response = await runtime.dispatch(commands[0])
                        hub.complete(machine, commands[0]["id"], response)
                        reply = await asyncio.wait_for(request, 5)
                        self.assertEqual(reply.status_code, 200, reply.text)
                        result = reply.json()["result"]
                        self.assertFalse(result["isError"], result)
                        return result["structuredContent"]
                    finally:
                        if not request.done():
                            request.cancel()
                            await asyncio.gather(request, return_exceptions=True)

                started = await call("start_review", {"project_id":project_id(str(project)),"prompt":"Review addition."})
                run_id = started["run_id"]
                job = runtime.app.state.engine.jobs.get(run_id)
                if job:
                    await asyncio.wait_for(job, 30)
                finished = await call("get_run", {"run_id":run_id})
                self.assertEqual(finished["status"], "completed", finished)
                self.assertEqual((await call("list_runs", {}))["runs"][0]["run_id"], run_id)
                self.assertEqual(git(project, "status", "--porcelain"), "")
                self.assertTrue(registry.calls)
                self.assertNotIn(str(project), json.dumps(finished))

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
