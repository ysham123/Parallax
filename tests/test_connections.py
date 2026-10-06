import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import httpx
from parallax.connections import ConnectionRegistry,ConnectionInput
from parallax.api_agent import ApiAgent,ApiFailure,_bounded_json,_command_scope
from parallax.models import Participant
from parallax.store import Store

class Vault:
    storage="test vault"
    def __init__(self): self.data={}
    def get(self,i,env=None): return self.data.get(i)
    def set(self,i,value): self.data[i]=value
    def delete(self,i): self.data.pop(i,None)

class Native:
    async def discover(self): return []

class ConnectionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.workspace=self.home/"work";self.workspace.mkdir()
        (self.workspace/".parallax-owned").write_text("owned")
        (self.workspace/"math.py").write_text("broken")
        self.store=Store(self.home/"state");self.vault=Vault()
    def config(self,protocol="responses"):
        return {"id":"custom-api","provider":"custom","name":"Custom","endpoint":"https://example.test/v1","protocol":protocol}
    async def test_key_is_separate_and_settings_are_explicit(self):
        registry=ConnectionRegistry(self.store,Native(),self.vault)
        result=await registry.put("custom-api",ConnectionInput(provider="custom",endpoint="https://example.test/v1",api_key="private-test-key",models=[{"id":"custom-model","efforts":["high"]}],default_model="custom-model"))
        self.assertTrue(result["api_configured"])
        self.assertNotIn("private-test-key",self.store.path.read_bytes().decode(errors="ignore"))
        effective=registry.validate(Participant(provider="custom",transport="api",model="custom-model",effort="high"))
        self.assertEqual(effective["model"],"custom-model")
        with self.assertRaisesRegex(ValueError,"effort"):
            registry.validate(Participant(provider="custom",transport="api",effort="max"))
        with self.assertRaisesRegex(ValueError,"absent"):
            registry.validate(Participant(provider="custom",transport="api",model="missing"))
        registry.delete("custom-api");self.assertFalse(self.vault.data)
    async def test_insecure_and_embedded_credential_urls_rejected(self):
        registry=ConnectionRegistry(self.store,Native(),self.vault)
        for endpoint in ["http://example.com/v1","https://user:secret@example.com/v1","https://example.com/v1?key=secret"]:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):
                await registry.put("custom-api",ConnectionInput(provider="custom",endpoint=endpoint,models=[{"id":"test"}],default_model="test"))
    async def test_account_discovery_never_substitutes_default(self):
        async def handler(request):
            self.assertEqual(request.headers["authorization"],"Bearer test-key")
            return httpx.Response(200,json={"data":[{"id":"new-model"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            registry=ConnectionRegistry(self.store,Native(),self.vault,client)
            await registry.put("custom-api",ConnectionInput(provider="custom",endpoint="https://example.test/v1",api_key="test-key",models=[{"id":"saved-model"}],default_model="saved-model"))
            result=await registry.test("custom-api")
            self.assertTrue(result["ok"]);self.assertFalse(result["default_model_available"])
            self.assertEqual(result["connection"]["default_model"],"saved-model")
            with self.assertRaises(ValueError): registry.validate(Participant(provider="custom",transport="api",effort=None))
    async def test_real_tool_loop_all_protocols_and_model_effort_mapping(self):
        for protocol in ["responses","anthropic","openai"]:
            requests=[]
            async def handler(request):
                body=json.loads(request.content);requests.append(body)
                self.assertEqual(body["model"],"chosen-model")
                if len(requests)==1:
                    args={"path":"math.py","content":"fixed"}
                    if protocol=="responses": data={"status":"completed","output":[{"type":"function_call","call_id":"write1","name":"write_file","arguments":json.dumps(args)}],"usage":{"input_tokens":3}}
                    elif protocol=="anthropic": data={"stop_reason":"tool_use","content":[{"type":"tool_use","id":"write1","name":"write_file","input":args}]}
                    else: data={"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant","content":None,"tool_calls":[{"id":"write1","type":"function","function":{"name":"write_file","arguments":json.dumps(args)}}]}}]}
                else:
                    if protocol=="responses": data={"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Done"}]}]}
                    elif protocol=="anthropic": data={"stop_reason":"end_turn","content":[{"type":"text","text":"Done"}]}
                    else: data={"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"Done"}}]}
                return httpx.Response(200,json=data)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                config=self.config(protocol);effective={"model":"chosen-model","effort":"high"}
                result=await ApiAgent(self.store.home,client).run(config,key="test",effective=effective,workspace=self.workspace,prompt="Fix math",mode="edit",allowed_files=["math.py"])
                self.assertTrue(result["ok"],result);self.assertEqual((self.workspace/"math.py").read_text(),"fixed")
                effort=requests[0].get("reasoning",requests[0].get("output_config",{})).get("effort",requests[0].get("reasoning_effort"))
                self.assertEqual(effort,"high")
                self.assertEqual(len(requests),2)
    async def test_permission_denials_scope_escape_and_read_only(self):
        agent=ApiAgent(self.store.home)
        for path in ["../outside","/tmp/outside",".git/index",".env","unowned.py"]:
            with self.assertRaises(ValueError): await agent._tool(self.workspace,"write_file",{"path":path,"content":"no"},"edit",["math.py"],None,None)
        with self.assertRaises(ValueError): await agent._tool(self.workspace,"write_file",{"path":"math.py","content":"no"},"consult",["math.py"],None,None)
        target=self.home/"outside";target.write_text("private");(self.workspace/"link").symlink_to(target)
        with self.assertRaises(ValueError): await agent._tool(self.workspace,"read_file",{"path":"link"},"consult",None,None,None)
        files=await agent._tool(self.workspace,"list_files",{},"consult",None,None,None)
        self.assertNotIn("link",files["files"])
    async def test_auth_malformed_partial_and_cancellation(self):
        for response,code in [(httpx.Response(401,json={"error":"secret"}),"authentication_failed"),(httpx.Response(200,json={"wrong":True}),"malformed_stream"),(httpx.Response(200,json={"status":"incomplete","output":[]}),"partial_response")]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:response)) as client:
                result=await ApiAgent(self.store.home,client).run(self.config(),key="test",effective={"model":"m","effort":None},workspace=self.workspace,prompt="test")
                self.assertFalse(result["ok"]);self.assertEqual(result["error"]["code"],code)
        flag=asyncio.Event()
        async def slow(request): await asyncio.sleep(30);return httpx.Response(200,json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            task=asyncio.create_task(ApiAgent(self.store.home,client).run(self.config(),key="test",effective={"model":"m","effort":None},workspace=self.workspace,prompt="test",cancel_event=flag))
            await asyncio.sleep(.03);flag.set()
            with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task,1)
    async def test_resume_does_not_repeat_uncertain_tool_or_change_identity(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={"output":[{"type":"message","content":[{"type":"output_text","text":"Done"}]}]}))) as client:
            agent=ApiAgent(self.store.home,client);settings={"model":"m","effort":None}
            result=await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="test")
            path=self.store.home/"api-sessions"/(result["session_id"]+".json")
            state=json.loads(path.read_text());state["tools"]["call1"]={"status":"issued"};path.write_text(json.dumps(state))
            resumed=await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="resume",session_id=result["session_id"])
            self.assertEqual(resumed["error"]["code"],"tool_reconciliation_required")
            with self.assertRaises(ValueError): await agent.run(self.config(),key="test",effective={"model":"other","effort":None},workspace=self.workspace,prompt="resume",session_id=result["session_id"])

    async def test_stream_bounds_abort_before_body_is_consumed_and_close(self):
        class Body(httpx.AsyncByteStream):
            chunks=0;closed=False
            async def __aiter__(self):
                for _ in range(300): self.chunks+=1;yield b"x"*65536
            async def aclose(self): self.closed=True
        body=Body()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,stream=body))) as client:
            with self.assertRaises(ApiFailure):
                await _bounded_json(client,"POST","https://example.test",headers={},limit=100000,timeout=1)
        self.assertEqual(body.chunks,2);self.assertTrue(body.closed)

    async def test_redirects_cannot_forward_credentials_even_with_custom_client(self):
        requests=[]
        def handler(request):
            requests.append(str(request.url));return httpx.Response(307,headers={"location":"https://foreign.test/models"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
            registry=ConnectionRegistry(self.store,Native(),self.vault,client)
            await registry.put("custom-api",ConnectionInput(provider="custom",endpoint="https://example.test/v1",api_key="test-key",models=[{"id":"m"}],default_model="m"))
            self.assertFalse((await registry.test("custom-api"))["ok"])
            result=await ApiAgent(self.store.home,client).run(self.config(),key="test-key",effective={"model":"m","effort":None},workspace=self.workspace,prompt="hello")
            self.assertEqual(result["error"]["code"],"api_request_failed")
        self.assertEqual(requests,["https://example.test/v1/models","https://example.test/v1/responses"])

    async def test_malformed_shapes_and_tool_arguments_fail_without_mutation(self):
        payloads=[[],{"output":[]},{"output":[{"type":"function_call","call_id":"x","name":"write_file","arguments":"[]"}]},
                  {"output":[{"type":"function_call","call_id":{},"name":"write_file","arguments":"{}"}]},
                  {"output":[{"type":"message","content":[{"type":"output_text","text":1}]}]}]
        for payload in payloads:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
                result=await ApiAgent(self.store.home,client).run(self.config(),key="test",effective={"model":"m","effort":None},workspace=self.workspace,prompt="test",mode="edit",allowed_files=["math.py"])
                self.assertEqual(result["error"]["code"],"malformed_stream")
        agent=ApiAgent(self.store.home)
        for name,args in [("write_file",{"path":"math.py","content":True}),("read_file",{"path":[]}),("list_files",{"extra":1}),("run_command",{"argv":[True]}),("read_file",[])]:
            with self.assertRaises(ValueError): await agent._tool(self.workspace,name,args,"edit",["math.py"],None,None)
        self.assertEqual((self.workspace/"math.py").read_text(),"broken")

    async def test_internal_aliases_case_variants_and_atomic_permissions(self):
        (self.workspace/".env").write_text("secret")
        (self.workspace/"alias").symlink_to(".env")
        (self.workspace/"unowned").write_text("safe")
        (self.workspace/"owned-alias").symlink_to("unowned")
        agent=ApiAgent(self.store.home)
        for name in ["alias",".ENV",".GIT/config"]:
            with self.assertRaises(ValueError): await agent._tool(self.workspace,"read_file",{"path":name},"consult",None,None,None)
        with self.assertRaises(ValueError): await agent._tool(self.workspace,"write_file",{"path":"owned-alias","content":"no"},"edit",["owned-alias"],None,None)
        self.assertEqual((self.workspace/"unowned").read_text(),"safe")
        target=self.workspace/"math.py";target.chmod(0o600)
        await agent._tool(self.workspace,"write_file",{"path":"math.py","content":"new"},"edit",["math.py"],None,None)
        self.assertEqual(target.stat().st_mode&0o777,0o600)
        self.assertFalse(list(self.workspace.glob(".api-write-*")))

    async def test_resume_binds_credentials_protocol_schema_and_ownership(self):
        payload={"output":[{"type":"message","content":[{"type":"output_text","text":"Done"}]}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            agent=ApiAgent(self.store.home,client);settings={"model":"m","effort":None};config=self.config()
            result=await agent.run(config,key="first-key",effective=settings,workspace=self.workspace,prompt="test",mode="edit",allowed_files=["math.py"])
            base={"key":"first-key","effective":settings,"workspace":self.workspace,"prompt":"continue","mode":"edit","allowed_files":["math.py"],"session_id":result["session_id"]}
            for changes in [{"key":"new-key"},{"allowed_files":["math.py","unowned.py"]},{"schema":{"type":"object"}}]:
                with self.assertRaises(ValueError): await agent.run(config,**{**base,**changes})
            with self.assertRaises(ValueError): await agent.run({**config,"protocol":"openai"},**base)
            self.assertNotIn("first-key",(self.store.home/"api-sessions"/(result["session_id"]+".json")).read_text())
        registry=ConnectionRegistry(self.store,Native(),self.vault)
        first=await registry.put("custom-api",ConnectionInput(provider="custom",endpoint="https://example.test/v1",api_key="first",models=[{"id":"m"}],default_model="m"))
        same=await registry.put("custom-api",ConnectionInput(provider="custom",name="renamed"))
        self.assertEqual(first["credential_version"],same["credential_version"])
        rotated=await registry.put("custom-api",ConnectionInput(provider="custom",api_key="second"))
        self.assertNotEqual(first["credential_version"],rotated["credential_version"])

    async def test_concurrent_resume_is_rejected_without_second_request(self):
        started=asyncio.Event();identifier=[];calls=[]
        async def emit(event):
            if event["type"]=="api.session": identifier.append(event["session_id"])
        async def handler(request): calls.append(request);started.set();await asyncio.sleep(30)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            agent=ApiAgent(self.store.home,client);settings={"model":"m","effort":None}
            task=asyncio.create_task(agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="first",on_event=emit))
            await asyncio.wait_for(started.wait(),1)
            with self.assertRaisesRegex(ValueError,"already active"):
                await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="second",session_id=identifier[0])
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(len(calls),1)

    async def test_completed_tool_result_is_saved_atomically_and_not_repeated(self):
        requests=[]
        async def handler(request):
            body=json.loads(request.content);requests.append(body)
            if len(requests)==1: return httpx.Response(200,json={"output":[{"type":"function_call","call_id":"write1","name":"write_file","arguments":json.dumps({"path":"math.py","content":"fixed"})}]})
            outputs=[x for x in body["input"] if x.get("type")=="function_call_output"]
            self.assertEqual(len(outputs),1);self.assertEqual(body["input"][-1]["content"],"resume")
            return httpx.Response(200,json={"output":[{"type":"message","content":[{"type":"output_text","text":"Done"}]}]})
        identifier=[]
        async def emit(event):
            if event["type"]=="api.session": identifier.append(event["session_id"])
            if event["type"]=="api.tool_finished": raise asyncio.CancelledError
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            agent=ApiAgent(self.store.home,client);settings={"model":"m","effort":None}
            with self.assertRaises(asyncio.CancelledError): await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="fix",mode="edit",allowed_files=["math.py"],on_event=emit)
            path=self.store.home/"api-sessions"/(identifier[0]+".json");state=json.loads(path.read_text())
            self.assertEqual(state["tools"]["write1"]["status"],"completed")
            self.assertEqual(state["history"][-1]["call_id"],"write1")
            # Simulate the old journal completion window; repair history only.
            state["history"].pop();path.write_text(json.dumps(state))
            (self.workspace/"math.py").write_text("user-later-edit")
            result=await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="resume",mode="edit",allowed_files=["math.py"],session_id=identifier[0])
            self.assertTrue(result["ok"]);self.assertEqual((self.workspace/"math.py").read_text(),"user-later-edit")

    async def test_finish_schema_is_validated_and_completed_for_next_turn(self):
        schema={"type":"object","properties":{"approved":{"type":"boolean"}},"required":["approved"],"additionalProperties":False}
        for arguments in [{"approved":"yes"},{"approved":True,"unknown":1},{}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={"output":[{"type":"function_call","call_id":"finish1","name":"finish","arguments":json.dumps(arguments)}]}))) as client:
                result=await ApiAgent(self.store.home,client).run(self.config(),key="test",effective={"model":"m","effort":None},workspace=self.workspace,prompt="review",schema=schema)
                self.assertEqual(result["error"]["code"],"invalid_structured_output")
        requests=[]
        async def handler(request):
            body=json.loads(request.content);requests.append(body)
            if len(requests)==2: self.assertEqual(body["input"][-2]["call_id"],"finish1")
            return httpx.Response(200,json={"output":[{"type":"function_call","call_id":"finish"+str(len(requests)),"name":"finish","arguments":'{"approved":true}'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            agent=ApiAgent(self.store.home,client);settings={"model":"m","effort":None}
            first=await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="review",schema=schema)
            second=await agent.run(self.config(),key="test",effective=settings,workspace=self.workspace,prompt="again",schema=schema,session_id=first["session_id"])
            self.assertTrue(first["ok"]);self.assertTrue(second["ok"])

    async def test_command_scope_excludes_other_temp_dirs_and_credentials(self):
        private=self.home/"private-command";private.mkdir()
        rule,env=_command_scope(self.workspace,private)
        grants=rule.split("(deny file-read-data",1)[0]
        self.assertNotIn('(subpath "/private/tmp")',grants)
        self.assertNotIn('(subpath '+json.dumps(tempfile.gettempdir())+')',grants)
        self.assertEqual(env["TMPDIR"],str(private.resolve()));self.assertEqual(env["HOME"],str(private.resolve()))
        self.assertNotIn("OPENAI_API_KEY",env)
        self.assertIn(str(self.workspace/".git"),rule)

    @unittest.skipUnless(sys.platform=="darwin" or sys.platform.startswith("linux"),"requires macOS or Linux sandbox")
    async def test_actual_command_sandbox_restricts_secret_and_external_access(self):
        from parallax.assessment import execution_capability
        if not execution_capability()["enforced"]: self.skipTest("Command sandbox is unavailable on this host")
        secret=self.home/"outside-secret";secret.write_text("private")
        (self.workspace/".env").write_text("private")
        (self.workspace/"nested").mkdir();(self.workspace/"nested"/".ENV.local").write_text("private")
        (self.workspace/"nested"/".ssh").mkdir();(self.workspace/"nested"/".ssh"/"key").write_text("private")
        script=self.workspace/"test_scope.py"
        script.write_text('import pathlib,os,sys\nassert sys.prefix == '+repr(sys.prefix)+'\nfor p in '+repr([str(secret),str(self.workspace/".env"),str(self.workspace/"nested"/".ENV.local"),str(self.workspace/"nested"/".ssh"/"key")])+':\n try:\n  value=pathlib.Path(p).read_text()\n except (PermissionError,FileNotFoundError): pass\n else: assert value != "private", "secret readable"\nassert os.environ.get("API_SECRET") is None\npathlib.Path(os.environ["TMPDIR"],"ok").write_text("ok")\nprint("protected")\n')
        events=[]
        result=await ApiAgent(self.store.home)._tool(self.workspace,"run_command",{"argv":[sys.executable,"-B",str(script)]},"edit",["math.py"],None,events.append)
        self.assertTrue(result["ok"],result);self.assertIn("protected",result["output"])
        self.assertEqual([e["type"] for e in events],["parallax.process_started","parallax.process_finished"])
        self.assertFalse((self.workspace/".parallax-home").exists())
