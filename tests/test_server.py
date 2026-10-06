import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from parallax.server import create_app
from parallax.store import Store
from parallax.cli import mcp_tools, invoke

class Registry:
    async def discover(self, *, refresh=False):
        self.refreshed=refresh
        return [{"provider":"codex","authenticated":True,"models":[]}]
    def validate(self,p): return {}
    async def catalog(self,p, *, refresh=False):
        self.refreshed=refresh
        return {"provider":p,"models":[]}

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name))
        self.client=TestClient(create_app(self.store,Registry(),token="private-token",workspace="/project"))
        self.addCleanup(self.client.close)
    def test_requires_auth_and_exchange_removes_token(self):
        self.assertEqual(self.client.get("/api/providers").status_code,401)
        response=self.client.get("/?token=private-token",follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers["location"],"/")
        self.assertIn("HttpOnly",response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/providers").status_code,200)
    def test_origin_and_host_rejected(self):
        headers={"Authorization":"Bearer private-token"}
        self.assertEqual(self.client.get("/api/providers",headers={**headers,"Origin":"https://attacker.example"}).status_code,403)
        self.assertEqual(self.client.get("/api/providers",headers={**headers,"Host":"attacker.example"}).status_code,403)
    def test_explicit_model_refresh_reaches_registry(self):
        headers={"Authorization":"Bearer private-token"}
        registry=self.client.app.state.engine.registry
        for path in ("/api/providers", "/api/models/codex"):
            self.assertEqual(self.client.get(path+"?refresh=true",headers=headers).status_code,200)
            self.assertTrue(registry.refreshed)
            self.assertEqual(self.client.get(path,headers=headers).status_code,200)
            self.assertFalse(registry.refreshed)
    def test_cli_and_mcp_expose_explicit_refresh(self):
        with patch("parallax.cli.service",return_value={}), patch("parallax.cli._request") as request:
            invoke("doctor",{"refresh":True})
            self.assertEqual(request.call_args.args[2],"/api/providers?refresh=true")
            invoke("models",{"provider":"codex","refresh":True})
            self.assertEqual(request.call_args.args[2],"/api/models/codex?refresh=True")
        for name in ("parallax_doctor","parallax_models"):
            tool=next(t for t in mcp_tools() if t["name"]==name)
            self.assertEqual(tool["inputSchema"]["properties"]["refresh"]["type"],"boolean")
    def test_profiles_share_contract_and_event_cursor_replays(self):
        headers={"Authorization":"Bearer private-token"}
        spec={"workspace":"/project","prompt":"A request"}
        self.assertEqual(self.client.put("/api/profiles/My team",json=spec,headers=headers).status_code,200)
        profiles=self.client.get("/api/profiles",headers=headers).json()
        self.assertEqual(profiles[0]["spec"]["coordinator"]["provider"],"codex")
        a=self.store.event("run","one");b=self.store.event("run","two")
        self.assertEqual(self.store.events("run",a["sequence"]),[b])
    def test_mcp_schema_references_are_at_root(self):
        schema=next(t["inputSchema"] for t in mcp_tools() if t["name"]=="parallax_start_run")
        self.assertIn("Participant",schema["$defs"])
        self.assertNotIn("$defs",schema["properties"]["spec"])
    def test_invalid_connection_body_never_echoes_credentials(self):
        response=self.client.put("/api/connections/test",json={"api_key":"secret-for-regression","provider":"invalid provider"},headers={"Authorization":"Bearer private-token"})
        self.assertEqual(response.status_code,422)
        self.assertNotIn("secret-for-regression",response.text)

    def test_session_cookie_reconnects_after_runtime_restart(self):
        self.client.get("/?token=private-token")
        cookie=self.client.cookies.get("parallax_session")
        with TestClient(create_app(self.store,Registry(),token="private-token")) as restarted:
            restarted.cookies.set("parallax_session",cookie)
            self.assertEqual(restarted.get("/api/providers").status_code,200)
            restarted.cookies.set("parallax_session",cookie+"tampered")
            self.assertEqual(restarted.get("/api/providers").status_code,401)

    def test_unknown_run_and_invalid_body(self):
        headers={"Authorization":"Bearer private-token"}
        self.assertEqual(self.client.get("/api/runs/missing",headers=headers).status_code,404)
        self.assertEqual(self.client.post("/api/runs",json={"prompt":""},headers=headers).status_code,422)

if __name__=="__main__": unittest.main()
