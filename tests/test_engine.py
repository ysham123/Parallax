import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from parallax.engine import Engine,RunProblem
from parallax.models import RunSpec, RunResult, Participant, TaskSpec, CheckSpec,CoordinatorAction
from parallax.store import Store
from parallax.workspaces import WorkspaceManager

def git(root,*args):
    return subprocess.run(["git",*args],cwd=root,capture_output=True,text=True,check=True).stdout

class FakeRegistry:
    def __init__(self,fail_worker=False,fail_review=False):
        self.calls=[];self.turn=0;self.fail_worker=fail_worker;self.fail_review=fail_review
    async def discover(self): return []
    def validate(self,p): return {"provider":p.provider,"model":p.model,"effort":p.effort}
    async def run(self,provider,**kwargs):
        self.calls.append((provider,kwargs["mode"]))
        path=kwargs["workspace"]
        structured=None
        if kwargs["mode"]=="coordinate":
            actions=[
                {"id":"plan","action":"plan","tasks":[{"id":"fix","title":"Fix addition","provider":"claude","prompt":"Fix addition","files":["maths.py"],"acceptance":["2+3 returns 5"]}]},
                {"id":"dispatch","action":"dispatch","task_ids":["fix"]},
                {"id":"validate","action":"validate"},
                {"id":"integrate","action":"request_integration"},
                {"id":"finish","action":"finish","summary":"Fixed addition; independent review and tests passed."}]
            structured=actions[min(self.turn,len(actions)-1)];self.turn+=1
        elif kwargs["mode"]=="edit":
            (path/"maths.py").write_text("def add(a, b):\n    return a + b\n")
            if self.fail_worker:
                return {"ok":False,"error":{"code":"worker_failed","message":"Simulated failure"},"answer":"partial","session_id":"partial"}
        elif kwargs.get("schema"):
            structured={"approved":not self.fail_review,"findings":[],"summary":"Verified source."}
        return {"ok":True,"answer":json.dumps(structured) if structured else "Independent assessment","structured_output":structured,"session_id":"fake-session","provider":provider,"effective_settings":{"model":"fake","effort":"high"},"usage":{"input_tokens":10}}

class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/"project";self.project.mkdir()
        git(self.project,"init","-q");git(self.project,"config","user.name","Test");git(self.project,"config","user.email","test@example.com")
        (self.project/"maths.py").write_text("def add(a, b):\n    return a - b\n")
        (self.project/"check.py").write_text("from maths import add\nassert add(2,3)==5\n")
        git(self.project,"add",".");git(self.project,"commit","-qm","baseline")
        self.store=Store(self.root/"state")
    def spec(self):
        return RunSpec(workspace=str(self.project),prompt="Fix the addition bug",team=[Participant(provider="claude"),Participant(provider="grok",role="reviewer")],checks=[CheckSpec(name="Addition check",argv=[sys.executable,"-B","check.py"])])
    async def finish(self,engine,result):
        await asyncio.wait_for(engine.jobs[result["run_id"]],30)
        return self.store.get(result["run_id"])
    def seed(self):
        spec=self.spec();run_id=str(uuid.uuid4())
        result=RunResult(run_id=run_id,status="interrupted",spec=spec).model_dump()
        result["artifacts"]={"directory":str(self.store.home/"runs"/run_id),"started_at":time.time(),"user_checks":[c.model_dump() for c in spec.checks]}
        self.store.save(result)
        manager=WorkspaceManager(self.project,Path(result["artifacts"]["directory"]))
        manager.prepare()
        return run_id,spec,manager
    def task(self):
        return {**TaskSpec(id="fix",title="Fix addition",provider="claude",prompt="Fix addition",files=["maths.py"]).model_dump(),"status":"pending","attempts":0}
    async def test_build_reviews_checks_integrates_and_preserves_staging(self):
        (self.project/"notes.txt").write_text("user staged work");git(self.project,"add","notes.txt")
        index=git(self.project,"diff","--cached")
        engine=Engine(self.store,FakeRegistry())
        result=await self.finish(engine,await engine.start(self.spec()))
        self.assertEqual(result["status"],"completed",result["errors"])
        self.assertIn("return a + b",(self.project/"maths.py").read_text())
        self.assertEqual(git(self.project,"diff","--cached"),index)
        self.assertTrue(result["checks"] and all(c["ok"] for c in result["checks"]))
        self.assertTrue(result["reviews"] and all(r["ok"] for r in result["reviews"]))
    async def test_failed_worker_never_integrates_partial_changes(self):
        registry=FakeRegistry(fail_worker=True);engine=Engine(self.store,registry)
        result=await self.finish(engine,await engine.start(self.spec()))
        self.assertNotEqual(result["status"],"completed")
        self.assertIn("return a - b",(self.project/"maths.py").read_text())
        self.assertEqual(result["tasks"][0]["status"],"failed")
    async def test_rejected_independent_review_blocks_integration(self):
        engine=Engine(self.store,FakeRegistry(fail_review=True))
        result=await self.finish(engine,await engine.start(self.spec()))
        self.assertNotEqual(result["status"],"completed")
        self.assertIn("return a - b",(self.project/"maths.py").read_text())
    async def test_project_lock_prevents_concurrent_builds(self):
        engine=Engine(self.store,FakeRegistry());result=await engine.start(self.spec())
        with self.assertRaises(ValueError): await engine.start(self.spec())
        engine.control(result["run_id"],"cancel");await self.finish(engine,result)
    async def test_review_partial_provider_failure_keeps_other_findings(self):
        registry=FakeRegistry();engine=Engine(self.store,registry)
        spec=self.spec();spec.mode="review"
        result=await self.finish(engine,await engine.start(spec))
        self.assertEqual(result["status"],"completed")
        self.assertEqual(len(result["reviews"]),2)
        self.assertEqual(git(self.project,"diff"),"")
    async def test_pause_steering_and_resume(self):
        engine=Engine(self.store,FakeRegistry());result=await engine.start(self.spec())
        engine.control(result["run_id"],"pause")
        engine.steer(result["run_id"],"Preserve the public signature")
        for _ in range(100):
            if self.store.get(result["run_id"])["status"]=="paused": break
            await asyncio.sleep(.01)
        self.assertEqual(self.store.get(result["run_id"])["status"],"paused")
        engine.control(result["run_id"],"resume")
        result=await self.finish(engine,result)
        self.assertEqual(result["status"],"completed",result["errors"])
        self.assertIn("Preserve the public signature",result["artifacts"]["steering"])
    def test_graph_scope_and_provider_validation(self):
        engine=Engine(self.store,FakeRegistry());spec=self.spec()
        for tasks in [
            [TaskSpec(id="a",title="a",provider="claude",prompt="a",files=["../outside"])],
            [TaskSpec(id="a",title="a",provider="grok",prompt="a",files=["maths.py"])],
            [TaskSpec(id="a",title="a",provider="claude",prompt="a",files=["maths.py"],dependencies=["b"]),TaskSpec(id="b",title="b",provider="claude",prompt="b",files=["check.py"],dependencies=["a"])]]:
            with self.assertRaises(ValueError): engine._validate_tasks(spec,tasks,[])

    async def test_action_journal_finishes_every_successful_action(self):
        engine=Engine(self.store,FakeRegistry())
        result=await self.finish(engine,await engine.start(self.spec()))
        self.assertEqual(result["status"],"completed",result["errors"])
        with self.store.connect() as db:
            actions=[json.loads(row[0]) for row in db.execute("SELECT result FROM actions WHERE run_id=?",(result["run_id"],))]
        self.assertEqual(len(actions),5)
        self.assertTrue(all(action["state"]=="completed" for action in actions),actions)

    def test_recovery_reconciles_persisted_plan_without_replaying_dispatch(self):
        run_id,spec,manager=self.seed()
        task=self.task();task["status"]="running";task["attempts"]=1
        result=self.store.get(run_id);result["status"]="running";result["tasks"]=[task];self.store.save(result)
        proposed={k:v for k,v in task.items() if k not in {"status","attempts"}}
        self.store.save_action(run_id,"plan",{"state":"issued","action":{"action":"plan","tasks":[proposed]}})
        self.store.save_action(run_id,"dispatch",{"state":"issued","action":{"action":"dispatch","task_ids":["fix"]}})
        engine=Engine(self.store,FakeRegistry());engine.recover()
        self.assertEqual(self.store.action(run_id,"plan")["state"],"completed")
        self.assertEqual(self.store.action(run_id,"dispatch")["state"],"interrupted")
        result=self.store.get(run_id)
        self.assertEqual(result["tasks"][0]["status"],"interrupted")
        self.assertTrue(result["artifacts"]["interrupted_actions"])

    async def test_interrupted_worker_resumes_same_checkout_and_bound_session(self):
        run_id,spec,manager=self.seed()
        target=manager.create_worker("fix-1")
        (target/"maths.py").write_text("# saved partial work\ndef add(a,b):\n    return a-b\n")
        task=self.task();task.update({"status":"interrupted","attempts":1,"active_attempt":{"number":1,"worker_id":"fix-1","workspace":str(target),"participant":spec.team[0].model_dump(),"state":"running"}})
        result=self.store.get(run_id);result["tasks"]=[task]
        result["sessions"]=[{"task_id":"fix","provider":"claude","transport":"cli","connection_id":None,"workspace":str(target),"mode":"edit","session_id":"saved-session","requested_settings":{"model":None,"effort":"high"},"effective_settings":{"model":"fake","effort":"high"}}]
        self.store.save(result)
        observed={}
        class ContinuingRegistry(FakeRegistry):
            async def run(self,provider,**kwargs):
                if kwargs["mode"]=="edit":
                    observed.update({"workspace":kwargs["workspace"],"session":kwargs["session_id"],"model":kwargs["model"]})
                    assert "saved partial work" in (kwargs["workspace"]/"maths.py").read_text()
                return await super().run(provider,**kwargs)
        engine=Engine(self.store,ContinuingRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        outcome=await engine._worker(run_id,spec,manager,task)
        self.assertTrue(outcome["ok"],outcome.get("error"))
        self.assertEqual(observed,{"workspace":target,"session":"saved-session","model":"fake"})
        saved=self.store.get(run_id)["tasks"][0]
        self.assertEqual(saved["attempts"],1)
        self.assertEqual(saved["active_attempt"]["state"],"reviewed")

    async def test_reviewed_worker_after_crash_reuses_evidence_without_new_edit(self):
        run_id,spec,manager=self.seed();task=self.task()
        result=self.store.get(run_id);result["tasks"]=[task];self.store.save(result)
        registry=FakeRegistry();engine=Engine(self.store,registry);engine.cancel_flags[run_id]=asyncio.Event()
        first=await engine._worker(run_id,spec,manager,task)
        self.assertTrue(first["ok"])
        saved=self.store.get(run_id);saved["tasks"][0]["status"]="interrupted";self.store.save(saved)
        calls=len(registry.calls)
        second=await engine._worker(run_id,spec,manager,saved["tasks"][0])
        self.assertTrue(second["ok"])
        self.assertEqual(len(registry.calls),calls)
        self.assertEqual(second["workspace"],first["workspace"])

    async def test_worker_exception_does_not_abandon_other_batch_members(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        completed=[]
        async def work(run_id,spec,manager,task):
            if task["id"]=="bad": raise ValueError("unexpected worker failure")
            await asyncio.sleep(.01);completed.append(task["id"])
            return {"ok":False,"error":"normal worker result"}
        with patch.object(engine,"_worker",side_effect=work):
            outcomes=await engine._worker_batch(run_id,spec,manager,[{"id":"bad"},{"id":"good"}])
        self.assertEqual(completed,["good"])
        self.assertEqual(outcomes[0]["code"],"worker_exception")

    async def test_batch_cancellation_awaits_every_sibling_cleanup(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        started=asyncio.Event();active=[];cleaned=[]
        async def work(run_id,spec,manager,task):
            active.append(task["id"])
            if len(active)==2: started.set()
            try: await asyncio.Event().wait()
            finally: cleaned.append(task["id"])
        with patch.object(engine,"_worker",side_effect=work):
            batch=asyncio.create_task(engine._worker_batch(run_id,spec,manager,[{"id":"a"},{"id":"b"}]))
            await started.wait();batch.cancel()
            with self.assertRaises(asyncio.CancelledError): await batch
        self.assertEqual(set(cleaned),{"a","b"})

    async def test_server_shutdown_preserves_interrupted_attempt(self):
        editing=asyncio.Event()
        class SlowRegistry(FakeRegistry):
            async def run(self,provider,**kwargs):
                if kwargs["mode"]=="edit":
                    editing.set();await asyncio.sleep(30)
                return await super().run(provider,**kwargs)
        engine=Engine(self.store,SlowRegistry());result=await engine.start(self.spec())
        await asyncio.wait_for(editing.wait(),10)
        await engine.shutdown()
        result=self.store.get(result["run_id"])
        self.assertEqual(result["status"],"interrupted")
        self.assertEqual(result["tasks"][0]["status"],"interrupted")
        self.assertTrue(result["tasks"][0]["active_attempt"]["workspace"])

    async def test_process_recovery_does_not_signal_reused_pid(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        self.store.event(run_id,"provider",{"type":"parallax.process_started","pid":123456,"process_group":123456,"cwd":str(manager.integration_path),"identity":{"started_at":"old","command_sha256":"old"}})
        with patch("parallax.providers.process_identity",new=AsyncMock(return_value={"started_at":"new","command_sha256":"new"})),patch("parallax.engine.os.killpg") as kill:
            await engine._reconcile_processes(run_id)
        kill.assert_not_called()
        self.assertEqual(self.store.events(run_id)[-1]["data"]["disposition"],"pid_reused")

    async def test_process_recovery_signals_only_matching_owned_identity(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        identity={"started_at":"old","command_sha256":"known"}
        self.store.event(run_id,"provider",{"type":"parallax.process_started","pid":123456,"process_group":123456,"cwd":str(manager.integration_path),"identity":identity})
        with patch("parallax.providers.process_identity",new=AsyncMock(side_effect=[identity,None,None])),patch("parallax.engine.os.killpg") as kill,patch("parallax.engine.os.getpgid",return_value=123456):
            await engine._reconcile_processes(run_id)
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[0],123456)

    async def test_surviving_child_keeps_identity_and_blocks_recovery(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        identity={"started_at":"old","command_sha256":"known"}
        self.store.event(run_id,"process",{"type":"parallax.process_started","pid":123456,"process_group":123456,"cwd":str(manager.integration_path),"identity":identity})
        with patch("parallax.providers.process_identity",new=AsyncMock(return_value=identity)),patch("parallax.engine.os.killpg") as kill,patch("parallax.engine.os.getpgid",return_value=123456),patch("parallax.engine.asyncio.sleep",new=AsyncMock()):
            with self.assertRaisesRegex(RunProblem,"survived"): await engine._reconcile_processes(run_id)
            await engine.reconcile_children()
        self.assertGreaterEqual(kill.call_count,2)
        self.assertEqual(self.store.get(run_id)["status"],"needs_attention")
        self.assertFalse(any(e["kind"]=="process_reconciled" for e in self.store.events(run_id)))

    async def test_opaque_live_process_identity_cannot_be_treated_as_exited(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        self.store.event(run_id,"process",{"type":"parallax.process_started","pid":123456,"process_group":123456,"cwd":str(manager.integration_path),"identity":None})
        with patch("parallax.providers.process_identity",new=AsyncMock(return_value=None)),patch("parallax.engine.os.kill"),patch("parallax.engine.os.killpg") as kill:
            with self.assertRaisesRegex(RunProblem,"cannot be inspected"): await engine._reconcile_processes(run_id)
        kill.assert_not_called()

    async def test_check_policy_rejects_every_invalid_command_before_provisioning(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        checks=[CheckSpec(name="Valid",argv=[sys.executable,"-B","check.py"]),CheckSpec(name="Untrusted",argv=[sys.executable,"-c","print('unsafe')"])]
        with patch.object(engine,"_ensure_environment",new=AsyncMock()) as prepare:
            with self.assertRaisesRegex(ValueError,"outside project verification"): await engine._checks(run_id,manager.integration_path,checks)
        prepare.assert_not_called()

    async def test_declared_python_dependency_installs_only_in_private_environment(self):
        wheel=self.project/"parallax_fixture_dep-1.0-py3-none-any.whl"
        files={"parallax_fixture_dep.py":"VALUE=7\n","parallax_fixture_dep-1.0.dist-info/METADATA":"Metadata-Version: 2.1\nName: parallax-fixture-dep\nVersion: 1.0\n","parallax_fixture_dep-1.0.dist-info/WHEEL":"Wheel-Version: 1.0\nGenerator: parallax-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
        files["parallax_fixture_dep-1.0.dist-info/RECORD"]="\n".join(path+",," for path in [*files,"parallax_fixture_dep-1.0.dist-info/RECORD"])+"\n"
        with zipfile.ZipFile(wheel,"w") as archive:
            for name,content in files.items(): archive.writestr(name,content)
        (self.project/"requirements.txt").write_text("--no-index\n./"+wheel.name+"\n")
        (self.project/"check.py").write_text("import parallax_fixture_dep,sys\nassert parallax_fixture_dep.VALUE==7\nprint(sys.executable)\n")
        git(self.project,"add",".");git(self.project,"commit","-qm","local dependency fixture")
        original_index=(self.project/".git"/"index").read_bytes()
        original_env=(Path(sys.prefix)/"pyvenv.cfg").read_bytes()
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        before=manager.fingerprint(manager.integration_path)
        evidence=await asyncio.wait_for(engine._checks(run_id,manager.integration_path,spec.checks),30)
        self.assertTrue(all(c["ok"] for c in evidence),evidence)
        self.assertIn(str(Path(self.store.get(run_id)["artifacts"]["directory"])/"environments"),evidence[0]["output"])
        self.assertEqual(before,manager.fingerprint(manager.integration_path))
        self.assertEqual((self.project/".git"/"index").read_bytes(),original_index)
        self.assertEqual((Path(sys.prefix)/"pyvenv.cfg").read_bytes(),original_env)
        import importlib.util
        self.assertIsNone(importlib.util.find_spec("parallax_fixture_dep"))
        self.assertFalse((self.project/".venv").exists())
        self.assertTrue(any(Path(self.store.get(run_id)["artifacts"]["directory"]).glob("environments/*/python-ready")))

    async def test_dependency_install_failure_preserves_private_attempt_and_source(self):
        (self.project/"requirements.txt").write_text("--no-index\nparallax-certainly-missing-dependency==12345\n")
        git(self.project,"add","requirements.txt");git(self.project,"commit","-qm","missing dependency fixture")
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        before=manager.fingerprint(manager.integration_path)
        with self.assertRaisesRegex(ValueError,"private environment preserved"):
            await asyncio.wait_for(engine._checks(run_id,manager.integration_path,spec.checks),30)
        self.assertEqual(before,manager.fingerprint(manager.integration_path))
        directory=Path(self.store.get(run_id)["artifacts"]["directory"])
        self.assertTrue(any(directory.glob("environments/*/venv/bin/python")))
        self.assertFalse(any(directory.glob("environments/*/python-ready")))

    @unittest.skipUnless(shutil.which("npm"),"requires npm")
    async def test_locked_npm_provision_uses_private_cache_and_preserves_source(self):
        (self.project/"package.json").write_text(json.dumps({"name":"parallax-fixture","version":"1.0.0","scripts":{"test":"node test_check.js"}}))
        (self.project/"package-lock.json").write_text(json.dumps({"name":"parallax-fixture","version":"1.0.0","lockfileVersion":3,"requires":True,"packages":{"":{"name":"parallax-fixture","version":"1.0.0"}}}))
        (self.project/".gitignore").write_text("node_modules/\n")
        (self.project/"test_check.js").write_text("require('assert').strictEqual(1 + 1, 2); console.log('verified');\n")
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        original=(self.project/".git"/"index").read_bytes();before=manager.fingerprint(manager.integration_path)
        evidence=await asyncio.wait_for(engine._checks(run_id,manager.integration_path,[CheckSpec(name="Npm",argv=["npm","run","test"])]),20)
        self.assertTrue(evidence[0]["ok"],evidence)
        self.assertEqual(before,manager.fingerprint(manager.integration_path))
        self.assertFalse((self.project/"node_modules").exists());self.assertEqual((self.project/".git"/"index").read_bytes(),original)
        self.assertTrue(any(Path(self.store.get(run_id)["artifacts"]["directory"]).glob("environments/*/npm-cache")))

    async def test_unlocked_node_dependency_fails_before_any_install(self):
        (self.project/"package.json").write_text(json.dumps({"name":"fixture","dependencies":{"example":"1.0.0"}}))
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        with patch.object(engine,"_command",new=AsyncMock()) as command:
            with self.assertRaisesRegex(ValueError,"requires npm checks"):
                await engine._checks(run_id,manager.integration_path,[CheckSpec(name="Test",argv=["npm","run","test"])])
        command.assert_not_called()

    async def test_node_modules_without_ignore_fails_before_any_install(self):
        (self.project/"package-lock.json").write_text("{}")
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        with patch.object(engine,"_command",new=AsyncMock()) as command:
            with self.assertRaisesRegex(ValueError,"gitignored"):
                await engine._checks(run_id,manager.integration_path,[CheckSpec(name="Test",argv=["npm","run","test"])])
        command.assert_not_called()

    @unittest.skipUnless(sys.platform=="darwin","requires macOS sandbox")
    async def test_model_proposed_check_cannot_read_canaries_or_inherit_credentials(self):
        outside=self.root/"outside-secret";outside.write_text("private")
        (self.project/".ENV.local").write_text("private")
        (self.project/"test_canary.py").write_text("import pathlib,os\nfor p in "+repr([str(outside),".ENV.local"])+":\n try:\n  pathlib.Path(p).read_text();raise AssertionError('secret readable')\n except PermissionError: pass\nassert os.environ.get('OPENAI_API_KEY') is None\nassert os.environ.get('ANTHROPIC_API_KEY') is None\nprint('protected')\n")
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        checks=[CheckSpec(name="Canary",argv=[sys.executable,"-B","test_canary.py"])]
        with patch.dict(os.environ,{"OPENAI_API_KEY":"not-for-tests","ANTHROPIC_API_KEY":"also-private"}):
            evidence=await asyncio.wait_for(engine._checks(run_id,manager.integration_path,checks),5)
        self.assertTrue(evidence[0]["ok"],evidence);self.assertIn("protected",evidence[0]["output"])

    async def test_unreaped_check_returns_failure_and_retains_started_event(self):
        from parallax.providers import Captured
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        async def capture(*args,**kwargs):
            await kwargs["on_event"]({"type":"parallax.process_started","pid":123456,"process_group":123456,"cwd":str(manager.integration_path),"identity":{"started_at":"old","command_sha256":"known"}})
            await kwargs["on_event"]({"type":"parallax.process_termination_failed","pid":123456,"cwd":str(manager.integration_path)})
            return Captured(None,"","",[],"process_termination_failed")
        with patch("parallax.providers._capture",side_effect=capture):
            with self.assertRaisesRegex(RunProblem,"survived termination"): await asyncio.wait_for(engine._checks(run_id,manager.integration_path,spec.checks),1)
        events=self.store.events(run_id)
        self.assertFalse(any(e["data"].get("type")=="parallax.process_finished" for e in events))
        self.assertEqual(next(e for e in events if e["kind"]=="check")["data"]["error"],"process_termination_failed")

    async def test_failed_task_resolution_requires_checks_budget_and_original_review(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        failed={**self.task(),"status":"failed","attempts":1,"prompt":"Original acceptance requirement"}
        replacement={**self.task(),"id":"replacement","status":"completed","attempts":1}
        result=self.store.get(run_id);result["tasks"]=[failed,replacement];self.store.save(result)
        action=CoordinatorAction(id="resolve",action="resolve_task",task_ids=["fix"],selected_task="replacement")
        with patch.object(engine,"_assess_patch",new=AsyncMock(return_value={"ok":True})) as review:
            with self.assertRaisesRegex(ValueError,"current combined verification"): await engine._action(run_id,spec,manager,action)
        review.assert_not_called()
        result=self.store.get(run_id);result["artifacts"]["validated_fingerprint"]=manager.diff();result["checks"]=[{"ok":True}];result["tasks"][0]["attempts"]=3;self.store.save(result)
        with patch.object(engine,"_assess_patch",new=AsyncMock(return_value={"ok":True})) as review:
            with self.assertRaisesRegex(ValueError,"repair budget"): await engine._action(run_id,spec,manager,action)
        review.assert_not_called()
        result=self.store.get(run_id);result["tasks"][0]["attempts"]=1;self.store.save(result)
        with patch.object(engine,"_assess_patch",new=AsyncMock(return_value={"ok":False})) as review:
            with self.assertRaisesRegex(ValueError,"original requirements"): await engine._action(run_id,spec,manager,action)
        self.assertEqual(review.call_args.args[4]["prompt"],"Original acceptance requirement")
        self.assertEqual(self.store.get(run_id)["tasks"][0]["status"],"failed")

    async def test_rejected_same_patch_reverification_invalidates_previous_approval(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
        task=self.task();task["status"]="completed"
        result=self.store.get(run_id);result["tasks"]=[task];self.store.save(result)
        evidence=[{"name":"Meaningful check","ok":True,"argv":[sys.executable,"-B","check.py"],"output":"passed"}]
        with patch.object(engine,"_checks",new=AsyncMock(return_value=evidence)),patch.object(engine,"_assess_patch",new=AsyncMock(side_effect=[{"ok":True},{"ok":False}])):
            await engine._verify(run_id,spec,manager,spec.checks)
            self.assertEqual(self.store.get(run_id)["artifacts"]["validated_fingerprint"],manager.diff())
            with self.assertRaisesRegex(ValueError,"review failed"): await engine._verify(run_id,spec,manager,spec.checks)
        self.assertNotIn("validated_fingerprint",self.store.get(run_id)["artifacts"])
        with patch.object(manager,"apply") as apply:
            with self.assertRaisesRegex(ValueError,"not passed verification"): await engine._integrate(run_id,spec,manager)
        apply.assert_not_called()

    async def test_finalized_candidate_rejects_new_actions_but_allows_inspection_and_finish(self):
        for finalized in ("integration_applied","verified_only"):
            run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry());engine.cancel_flags[run_id]=asyncio.Event()
            task=self.task();task["status"]="completed"
            result=self.store.get(run_id);result["tasks"]=[task];result["artifacts"][finalized]=True;self.store.save(result)
            baseline=self.store.get(run_id)
            for kind in ("plan","dispatch","validate","resolve_task","request_integration"):
                action=CoordinatorAction(id="late-"+kind,action=kind,tasks=[TaskSpec(id="new",title="New work",provider="claude",prompt="Edit more",files=["maths.py"])],task_ids=["fix"],selected_task="fix")
                with self.assertRaisesRegex(ValueError,"candidate is finalized"): await engine._action(run_id,spec,manager,action)
                self.assertEqual(self.store.get(run_id),baseline)
            await engine._action(run_id,spec,manager,CoordinatorAction(id="inspect",action="inspect_results"))
            self.assertEqual(self.store.get(run_id),baseline)
            await engine._action(run_id,spec,manager,CoordinatorAction(id="finish",action="finish",summary="Verified result"))
            final=self.store.get(run_id)
            self.assertEqual(final["status"],"completed");self.assertEqual(final["summary"],"Verified result")
            self.assertEqual(final["tasks"],baseline["tasks"])
            self.assertEqual(final["spec"],baseline["spec"])
            self.assertEqual(final["diff"],baseline["diff"])

    async def test_coordinator_late_plan_is_rejected_and_applied_receipt_stays_consistent(self):
        from parallax.receipt import get_receipt
        class LatePlanner(FakeRegistry):
            async def run(self,provider,**kwargs):
                if kwargs["mode"]=="coordinate" and self.turn==4:
                    self.turn+=1
                    action={"id":"late-plan","action":"plan","tasks":[{"id":"extra","title":"Extra work","provider":"claude","prompt":"Change the implementation again","files":["maths.py"]}]}
                    return {"ok":True,"structured_output":action,"session_id":"fake-session","effective_settings":{"model":"fake","effort":"high"}}
                return await super().run(provider,**kwargs)
        engine=Engine(self.store,LatePlanner())
        result=await self.finish(engine,await engine.start(self.spec()))
        self.assertEqual(result["status"],"completed",result["errors"])
        self.assertEqual([task["id"] for task in result["tasks"]],["fix"])
        self.assertEqual(self.store.action(result["run_id"],"late-plan")["state"],"failed")
        self.assertEqual(self.store.action(result["run_id"],"finish")["state"],"completed")
        receipt=get_receipt(self.store,result["run_id"])
        self.assertEqual(receipt["outcome"],"applied")
        self.assertTrue(all(gate["status"]=="passed" for gate in receipt["gates"]),receipt["gates"])

    async def test_resume_cannot_reset_exhausted_time_budget(self):
        run_id,spec,manager=self.seed();result=self.store.get(run_id)
        result["artifacts"]["runtime_seconds"]=spec.limits.minutes*60
        self.store.save(result)
        registry=FakeRegistry();engine=Engine(self.store,registry)
        engine.control(run_id,"resume")
        await engine.jobs[run_id]
        result=self.store.get(run_id)
        self.assertEqual(result["status"],"needs_attention")
        self.assertEqual(result["errors"][-1]["code"],"budget_exceeded")
        self.assertEqual(registry.calls,[])

    def test_streamed_native_session_recovery_requires_workspace_and_mode(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        worker=manager.create_worker("fix-1");session=str(uuid.uuid4())
        event={"type":"system","session_id":session,"provider":"claude","workspace":str(worker),"mode":"edit","transport":"cli","connection_id":None,"effective_settings":{"model":"fake","effort":"high"}}
        self.store.event(run_id,"provider",event,"fix")
        self.store.event(run_id,"provider",{**event,"workspace":str(manager.integration_path),"session_id":str(uuid.uuid4())},"fix")
        recovered=engine._resume_session(run_id,"fix",worker,spec.team[0],"edit")
        self.assertEqual(recovered["session_id"],session)
        self.assertIsNone(engine._resume_session(run_id,"fix",worker,spec.team[0],"coordinate"))

    def test_streamed_api_session_recovery_requires_connection_identity(self):
        run_id,spec,manager=self.seed();engine=Engine(self.store,FakeRegistry())
        worker=manager.create_worker("api-worker");session="api-"+str(uuid.uuid4())
        member=Participant(provider="custom",transport="api",connection_id="chosen",model="custom-model",effort=None)
        self.store.event(run_id,"provider",{"type":"api.session","session_id":session,"provider":"custom","workspace":str(worker),"mode":"edit","transport":"api","connection_id":"chosen","effective_settings":{"model":"custom-model","effort":None}},"custom-task")
        recovered=engine._resume_session(run_id,"custom-task",worker,member,"edit")
        self.assertEqual(recovered["session_id"],session)
        changed=member.model_copy(update={"connection_id":"different"})
        self.assertIsNone(engine._resume_session(run_id,"custom-task",worker,changed,"edit"))

if __name__=="__main__": unittest.main()
