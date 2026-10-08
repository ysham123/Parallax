import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from parallax.deployment import Deployment
from parallax.server import create_app
from parallax.store import Store

class Registry:
    async def discover(self, **kwargs): return []

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.projects = Path(self.temp.name) / "projects"
        self.projects.mkdir()
        self.store = Store(Path(self.temp.name) / "state")
        self.token = "a-secure-test-key-with-at-least-32-characters"
        self.origin = "https://studio.example.com"
        self.deployment = Deployment(self.token, frozenset({self.origin}), frozenset({"runtime.example.com"}), self.projects)
        self.client = TestClient(create_app(self.store, Registry(), token=self.token, deployment=self.deployment), base_url="https://runtime.example.com")
        self.addCleanup(self.client.close)

    def sign_in(self):
        return self.client.post("/api/session", json={"token":self.token}, headers={"Origin":self.origin})

    def test_cookie_auth_restart_and_sign_out(self):
        self.assertEqual(self.client.get("/api/runs").status_code,401)
        response=self.sign_in()
        self.assertEqual(response.status_code,200)
        cookie=response.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=strict"): self.assertIn(flag,cookie)
        self.assertNotIn(self.token,response.text+cookie)
        self.assertEqual(self.client.get("/api/runs").status_code,200)
        with TestClient(create_app(self.store,Registry(),token=self.token,deployment=self.deployment),base_url="https://runtime.example.com") as restarted:
            restarted.cookies.update(self.client.cookies)
            self.assertEqual(restarted.get("/api/session").status_code,200)
        self.assertEqual(self.client.delete("/api/session",headers={"Origin":self.origin}).status_code,200)
        self.assertEqual(self.client.get("/api/session").status_code,401)

    def test_rejects_foreign_origins_hosts_and_csrf(self):
        self.sign_in()
        self.assertEqual(self.client.get("/api/runs",headers={"Host":"attacker.example.com"}).status_code,403)
        self.assertEqual(self.client.post("/api/session",json={"token":self.token},headers={"Origin":"https://attacker.example.com"}).status_code,403)
        self.assertEqual(self.client.delete("/api/session").status_code,403)
        self.assertEqual(self.client.delete("/api/session",headers={"Origin":"https://studio.example.com.attacker.com"}).status_code,403)
        self.assertEqual(self.client.get("/api/runs",headers={"X-Forwarded-Host":"attacker.example.com"}).status_code,200)

    def test_healthcheck_only_host_and_no_url_token_exchange(self):
        self.assertEqual(self.client.get("/api/health",headers={"Host":"healthcheck.railway.app"}).status_code,200)
        self.assertEqual(self.client.get("/api/runs",headers={"Host":"healthcheck.railway.app","Authorization":"Bearer "+self.token}).status_code,403)
        self.assertEqual(self.client.get("/?token="+self.token).status_code,401)
        self.assertNotIn("set-cookie",self.client.get("/?token="+self.token).headers)

    def test_workspace_boundaries_include_symlinks(self):
        self.sign_in()
        outside=Path(self.temp.name)/"outside";outside.mkdir()
        (self.projects/"escape").symlink_to(outside,target_is_directory=True)
        for value in (str(outside),str(self.projects/"escape"),str(self.projects/".."/"state")):
            for path,body in (("/api/runs",{"workspace":value,"prompt":"Review"}),
                              ("/api/project/assess",{"workspace":value}),
                              ("/api/profiles/example",{"workspace":value,"prompt":"Review"}),
                              ("/api/project-profiles/example",{"workspace":value})):
                method=self.client.put if "profiles" in path else self.client.post
                response=method(path,json=body,headers={"Origin":self.origin})
                self.assertEqual(response.status_code,400,response.text)
        self.deployment.check_workspace(str(self.projects))

    def test_login_denials_and_throttling(self):
        for _ in range(20):
            response=self.client.post("/api/session",json={"token":"wrong-ü"},headers={"Origin":self.origin})
            self.assertEqual(response.status_code,401)
            self.assertNotIn("wrong",response.text)
        self.assertEqual(self.client.post("/api/session",json={"token":"wrong-again"},headers={"Origin":self.origin}).status_code,429)
        # Only failures are throttled: other clients' guesses never lock out the valid key.
        self.assertEqual(self.sign_in().status_code,200)

    def test_configuration_fails_closed(self):
        base={"PARALLAX_ACCESS_TOKEN":self.token,"PARALLAX_STUDIO_ORIGINS":self.origin,"PARALLAX_ALLOWED_HOSTS":"runtime.example.com","PARALLAX_PROJECTS_ROOT":str(self.projects)}
        with patch.dict(os.environ,base,clear=True):
            config=Deployment.from_env()
            self.assertEqual(config.projects,self.projects.resolve())
        for key,value in (("PARALLAX_ACCESS_TOKEN","short"),("PARALLAX_STUDIO_ORIGINS","*"),
                          ("PARALLAX_STUDIO_ORIGINS","http://studio.example.com"),
                          ("PARALLAX_STUDIO_ORIGINS","https://studio.example.com/path"),
                          ("PARALLAX_ALLOWED_HOSTS","*.example.com")):
            with patch.dict(os.environ,{**base,key:value},clear=True), self.assertRaises(ValueError): Deployment.from_env()

    def test_provider_processes_do_not_inherit_workspace_access_key(self):
        import asyncio
        from unittest.mock import AsyncMock
        from parallax.providers import ProviderRegistry
        registry=ProviderRegistry(home=Path(self.temp.name))
        registry._help["codex"]="--config --sandbox"
        with patch.dict(os.environ,{"PARALLAX_ACCESS_TOKEN":self.token,"PARALLAX_GITHUB_CLIENT_SECRET":"github-secret-value-0123456789"}):
            _,_,env,_=registry._command("codex","codex",self.projects,"Review",{"model":"model","effort":"high"},"consult",None,60,None,self.projects,{})
            self.assertNotIn("PARALLAX_ACCESS_TOKEN",env)
            self.assertNotIn("PARALLAX_GITHUB_CLIENT_SECRET",env)
            with patch("parallax.providers._capture",new_callable=AsyncMock) as capture:
                asyncio.run(registry._metadata("codex",["--version"]))
                self.assertNotIn("PARALLAX_ACCESS_TOKEN",capture.call_args.kwargs["env"])
                self.assertNotIn("PARALLAX_GITHUB_CLIENT_SECRET",capture.call_args.kwargs["env"])

if __name__ == "__main__": unittest.main()
