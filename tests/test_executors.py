"""Real relay/engine operations with deterministic providers and no paid inference."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch, AsyncMock
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from parallax.deployment import Deployment
from parallax.executors import ExecutorHub, digest, encode, permitted
from parallax.models import RunSpec, RunResult
from parallax.server import create_app
from parallax.store import Store
from parallax.worker import WorkerRuntime, run_worker
from test_engine import FakeRegistry, git


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"; self.project.mkdir()
        self.cloud = Store(self.root / "cloud")
        self.local = Store(self.root / "local")
        self.hub = ExecutorHub(self.cloud)
        self.credentials = self.hub.connect(self.hub.pair("owner")["code"], "Test Mac", {"platform":"darwin", "workspaces":[str(self.project)]})
        self.worker = self.credentials["id"]
        self.registry = FakeRegistry()

    def command(self, method, path, body=None, **extra):
        return {"id":str(uuid.uuid4()), "method":method, "path":path, "query":"", "body":body, "expires_at":time.time()+60, **extra}

    async def roundtrip(self, runtime, method, path, body=None):
        pending = asyncio.create_task(self.hub.request(self.worker, method, path, "", body, workspace="owner", timeout=10))
        await asyncio.sleep(.01)
        commands = self.hub.pending(self.worker)
        self.assertEqual(len(commands), 1)
        response = await runtime.dispatch(commands[0])
        self.hub.complete(self.worker, commands[0]["id"], response)
        return await pending

    async def test_relay_build_preserves_staging_and_requires_real_checks(self):
        git(self.project,"init","-q"); git(self.project,"config","user.name","Test"); git(self.project,"config","user.email","test@example.com")
        (self.project/"maths.py").write_text("def add(a,b):\n    return a-b\n")
        (self.project/"check.py").write_text("from maths import add\nassert add(2,3)==5\n")
        git(self.project,"add","."); git(self.project,"commit","-qm","baseline")
        (self.project/"notes.txt").write_text("staged user work");git(self.project,"add","notes.txt")
        (self.project/"untracked.txt").write_text("untracked user work")
        staging = git(self.project,"diff","--cached")
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            spec = {"workspace":str(self.project),"prompt":"Fix addition","mode":"build",
                    "team":[{"provider":"claude"},{"provider":"grok","role":"reviewer"}],
                    "checks":[{"name":"addition","argv":[sys.executable,"-B","check.py"]}]}
            response = await self.roundtrip(runtime,"POST","/api/runs",spec)
            self.assertEqual(response["status"],200,response)
            run_id = response["body"]["run_id"]
            await asyncio.wait_for(runtime.app.state.engine.jobs[run_id],30)
            result = self.local.get(run_id)
            self.assertEqual(result["status"],"completed",result["errors"])
            self.assertIn("return a + b",(self.project/"maths.py").read_text())
            self.assertEqual(git(self.project,"diff","--cached"),staging)
            self.assertEqual((self.project/"untracked.txt").read_text(),"untracked user work")
            self.assertTrue(all(check["ok"] for check in result["checks"]))
            self.assertTrue(all(review["ok"] for review in result["reviews"]))
            runs, events = runtime.snapshot({},0)
            self.hub.sync(self.worker,runs,events)
            self.assertEqual(self.hub.cached(self.worker,"/api/runs/"+run_id)["body"]["status"],"completed")
            cursor = events[0]["sequence"]
            self.assertTrue(all(e["sequence"]>cursor for e in self.hub.events(self.worker,run_id,cursor,"owner")))

    async def test_duplicate_dispatch_and_lost_reply_never_start_twice(self):
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            command = self.command("POST","/api/runs",{"workspace":str(self.project),"prompt":"Read","mode":"review","team":[{"provider":"claude"}]})
            first = await runtime.dispatch(command)
            second = await runtime.dispatch(command)
            self.assertEqual(first,second)
            self.assertEqual(len(self.local.runs()),1)
            changed = {**command,"body":{**command["body"],"prompt":"Different"}}
            self.assertEqual((await runtime.dispatch(changed))["status"],409)
            # Persisted running journal is ambiguous after a crash, not permission to repeat.
            interrupted = self.command("POST","/api/runs",command["body"])
            fingerprint=digest(encode({k:interrupted.get(k) for k in ("method","path","query","body")}))
            with self.local.connect() as db: db.execute("INSERT INTO worker_dispatch VALUES(?,?,NULL,?,0)",(interrupted["id"],fingerprint,time.time()))
            self.assertEqual((await runtime.dispatch(interrupted))["status"],409)
            self.assertEqual(len(self.local.runs()),1)

    async def test_dispatch_journal_survives_worker_restart(self):
        command=self.command("GET","/api/context")
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            response=await runtime.dispatch(command)
        async with WorkerRuntime(Store(self.local.home),[self.project],registry=self.registry) as restarted:
            self.assertEqual(await restarted.dispatch(command),response)

    async def test_unapproved_and_symlink_projects_cannot_dispatch(self):
        outside=self.root/"outside"; outside.mkdir()
        (self.project/"escape").symlink_to(outside,target_is_directory=True)
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            for workspace in (outside,self.project/"escape",self.root):
                response=await runtime.dispatch(self.command("POST","/api/runs",{"workspace":str(workspace),"prompt":"Read","mode":"review"}))
                self.assertEqual(response["status"],400,response)
            self.assertFalse(self.local.runs())

    async def test_expired_and_disallowed_commands_never_execute(self):
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            self.assertEqual((await runtime.dispatch(self.command("POST","/api/runs",{},expires_at=0)))["status"],408)
            for method,path in (("PUT","/api/connections/new"),("GET","/api/session"),("POST","/api/executors/pair"),("GET","/etc/passwd")):
                self.assertEqual((await runtime.dispatch(self.command(method,path)))["status"],403)
            self.assertFalse(self.local.runs())

    async def test_removed_project_cannot_resume_prior_run(self):
        result=RunResult(run_id=str(uuid.uuid4()),status="interrupted",spec=RunSpec(workspace=str(self.root/"removed"),prompt="Prior request")).model_dump()
        result["artifacts"]["directory"]=str(self.local.home/"runs"/result["run_id"])
        self.local.save(result)
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            response=await runtime.dispatch(self.command("POST","/api/runs/"+result["run_id"]+"/resume"))
            self.assertEqual(response["status"],400)
            self.assertFalse(runtime.app.state.engine.jobs)

    async def test_offline_cached_evidence_cannot_dispatch_work(self):
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            await self.roundtrip(runtime,"GET","/api/context")
        with self.cloud.connect() as db: db.execute("UPDATE workers SET seen=0")
        response=await self.hub.request(self.worker,"GET","/api/context","",None,workspace="owner")
        self.assertTrue(response["offline"])
        with self.assertRaises(HTTPException) as failure: await self.hub.request(self.worker,"POST","/api/runs","",{},workspace="owner")
        self.assertEqual(failure.exception.status_code,503)
        self.assertEqual(self.hub.pending(self.worker),[])

    async def test_timeout_is_retained_and_not_redispatched_automatically(self):
        with self.assertRaises(HTTPException) as failure:
            await self.hub.request(self.worker,"POST","/api/runs","",{},workspace="owner",timeout=.001)
        self.assertEqual(failure.exception.status_code,504)
        pending=self.hub.pending(self.worker)
        self.assertEqual(len(pending),1)
        async with WorkerRuntime(self.local,[self.project],registry=self.registry) as runtime:
            self.assertEqual((await runtime.dispatch(pending[0]))["status"],408)
            self.assertFalse(self.local.runs())

    async def test_worker_events_replay_after_relay_restart_without_duplicates(self):
        run_id=str(uuid.uuid4())
        events=[{"run_id":run_id,"sequence":n,"kind":"status","data":{}} for n in (1,2,3)]
        self.hub.sync(self.worker,[],events)
        restarted=ExecutorHub(Store(self.cloud.home))
        restarted.sync(self.worker,[],events)
        self.assertEqual([e["sequence"] for e in restarted.events(self.worker,run_id,1,"owner")],[2,3])

    async def test_worker_response_scope_and_immutability(self):
        pending=asyncio.create_task(self.hub.request(self.worker,"GET","/api/context","",None,workspace="owner",timeout=10))
        await asyncio.sleep(.01); command=self.hub.pending(self.worker)[0]
        other=self.hub.connect(self.hub.pair("owner")["code"],"Other",{"platform":"linux","workspaces":[]})
        response={"status":200,"body":{},"content_type":"application/json"}
        with self.assertRaises(HTTPException): self.hub.complete(other["id"],command["id"],response)
        self.hub.complete(self.worker,command["id"],response)
        self.hub.complete(self.worker,command["id"],response)
        with self.assertRaises(HTTPException): self.hub.complete(self.worker,command["id"],{**response,"body":{"tampered":True}})
        self.assertEqual(await pending,response)

    async def test_network_loss_retries_but_revocation_exits_worker(self):
        state=self.root/"connection-state";state.mkdir()
        credentials={"id":str(uuid.uuid4()),"token":"worker-secret","url":"https://relay.example.com","workspaces":[str(self.project)]}
        (state/"worker-connection.json").write_text(encode(credentials))
        requests=[]
        def handle(request):
            requests.append(request.url.path)
            if len(requests)==1: raise httpx.ConnectError("temporary network loss")
            return httpx.Response(401,json={"detail":"revoked"})
        original_client=httpx.AsyncClient
        def client(**kwargs):
            if "transport" not in kwargs: kwargs["transport"]=httpx.MockTransport(handle)
            return original_client(**kwargs)
        with patch("parallax.worker.httpx.AsyncClient",side_effect=client), patch("parallax.worker.asyncio.sleep",new_callable=AsyncMock):
            with self.assertRaises(PermissionError):
                await run_worker("https://relay.example.com",state,[self.project],name="Test")
        self.assertEqual(requests,["/api/worker/sync","/api/worker/sync"])


class WorkerEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_evidence_declined_by_a_relay_low_on_storage_is_resent(self):
        root = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        project = root / "project"; project.mkdir(); state = root / "state"; state.mkdir()
        (state / "worker-connection.json").write_text(encode({"id": str(uuid.uuid4()), "token": "worker-secret", "url": "https://relay.example.com",
                                                              "workspaces": [str(project)]}))
        run_id = str(uuid.uuid4())
        events = [{"run_id": run_id, "sequence": n, "kind": "status", "data": {}} for n in (1, 2)]
        sent = []
        def handle(request):
            if request.url.path == "/api/worker/next":
                return httpx.Response(200, json=[])
            sent.append([e["sequence"] for e in json.loads(request.content)["events"]])
            if len(sent) == 1:
                return httpx.Response(200, json={"ok": True, "stored": False})
            if len(sent) == 2:
                return httpx.Response(200, json={"ok": True, "stored": True})
            return httpx.Response(401, json={"detail": "stop"})
        original = httpx.AsyncClient
        def client(**kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(handle))
            return original(**kwargs)
        snapshot = lambda self, hashes, cursor: ([], [e for e in events if e["sequence"] > cursor])
        with patch("parallax.worker.httpx.AsyncClient", side_effect=client), patch("parallax.worker.asyncio.sleep", new_callable=AsyncMock), \
                patch.object(WorkerRuntime, "snapshot", snapshot):
            with self.assertRaises(PermissionError):
                await run_worker("https://relay.example.com", state, [project], name="Test")
        self.assertEqual(sent, [[1, 2], [1, 2], []])


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.projects=self.root/"projects"; self.projects.mkdir()
        self.store=Store(self.root/"state")
        self.key="private-studio-key-with-at-least-32-characters"
        deployment=Deployment(self.key,frozenset({"https://studio.example.com"}),frozenset({"runtime.example.com"}),self.projects)
        self.client=TestClient(create_app(self.store,token=self.key,deployment=deployment),base_url="https://runtime.example.com")
        self.addCleanup(self.client.close)
        self.admin={"Authorization":"Bearer "+self.key}
        self.hub=self.client.app.state.executors

    def pair(self):
        code=self.client.post("/api/executors/pair",headers=self.admin).json()["code"]
        return self.client.post("/api/worker/connect",json={"code":code,"name":"Mac","platform":"darwin","workspaces":["/project"]})

    def test_pairing_requires_studio_auth_and_is_single_use(self):
        self.assertEqual(self.client.post("/api/executors/pair",headers={"Origin":"https://studio.example.com"}).status_code,401)
        code=self.client.post("/api/executors/pair",headers=self.admin).json()["code"]
        body={"code":code,"name":"Mac","platform":"darwin","workspaces":["/project"]}
        response=self.client.post("/api/worker/connect",json=body)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post("/api/worker/connect",json=body).status_code,401)
        workers=self.client.get("/api/executors",headers=self.admin)
        self.assertNotIn(response.json()["token"],workers.text)
        self.assertNotIn(code,workers.text)
        self.assertNotIn(response.json()["token"],self.store.path.read_bytes().decode("latin1"))

    def test_expired_pair_and_browser_worker_protocol_are_rejected(self):
        with patch("parallax.executors.time.time",return_value=0): code=self.hub.pair("owner")["code"]
        body={"code":code,"name":"Mac","platform":"darwin","workspaces":["/project"]}
        self.assertEqual(self.client.post("/api/worker/connect",json=body).status_code,401)
        self.assertEqual(self.client.post("/api/worker/connect",json=body,headers={"Origin":"https://studio.example.com"}).status_code,403)

    def test_scoped_worker_token_cannot_control_studio_and_revocation_persists(self):
        credentials=self.pair().json();headers={"Authorization":"Bearer "+credentials["token"]}
        self.assertEqual(self.client.get("/api/worker/next",headers=headers).status_code,200)
        for method,path in (("get","/api/runs"),("post","/api/executors/pair"),("get","/api/executors")):
            self.assertEqual(getattr(self.client,method)(path,headers=headers).status_code,401)
        self.assertEqual(self.client.delete("/api/executors/"+credentials["id"],headers=self.admin).status_code,200)
        self.assertEqual(self.client.get("/api/worker/next",headers=headers).status_code,401)
        with self.assertRaises(HTTPException): ExecutorHub(Store(self.store.home)).authenticate(credentials["token"])

    def test_path_query_and_credentials_allowlist(self):
        for path in ("/api/session","/api/../runs","/api/models/%2e%2e","http://attacker.example/api/runs"):
            self.assertFalse(permitted("GET",path))
        self.assertFalse(permitted("GET","/api/context","token=secret"))
        self.assertFalse(permitted("PUT","/api/connections/new"))
        self.assertTrue(permitted("GET","/api/models/codex","refresh=true"))


if __name__=="__main__": unittest.main()
