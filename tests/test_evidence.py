import asyncio
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from parallax.candidates import Candidates, POLICY, digest
from parallax.engine import Engine
from parallax.evidence import (CONTENT_SCHEME, READONLY_SCHEME, content_digest,
                               phase_attempt, record_observation, text_digest)
from parallax.models import CheckEvidence, CheckSpec, CoordinatorAction, Participant, RunResult, RunSpec
from parallax.receipt import build_receipt, get_receipt, save_receipt
from parallax.store import Store
from parallax.workspaces import WorkspaceManager, fingerprint
from test_engine import FakeRegistry, git


class EvidenceJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.result = RunResult(run_id="run-1", status="failed",
            spec=RunSpec(workspace=str(self.project), prompt="private prompt")).model_dump()
        directory = self.store.home / "runs" / "run-1"
        directory.mkdir(parents=True)
        self.result["artifacts"]["directory"] = str(directory)
        self.store.save(self.result)

    def record(self, **changes):
        evidence = {"ok": False, "task_id": "integration", "provider": "claude",
                    "findings": [], "summary": "private summary", **changes}
        return record_observation(self.store, "run-1", "review", evidence,
            phase_attempt("final", "integration"), before="a" * 64, after="a" * 64,
            patch="GIT binary patch\nprivate patch", requirements={"request":"private prompt"})

    def test_failed_evidence_is_durable_without_candidate_or_result_update(self):
        row = self.record()
        self.assertEqual(self.store.get("run-1")["reviews"], [])
        restarted = Store(self.store.home)
        self.addCleanup(restarted.close)
        found = restarted.observation("run-1", row["observation"]["id"], row["observation"]["content_sha256"])
        self.assertFalse(found["evidence"]["ok"])
        self.assertEqual(found["kind"], "review")
        self.assertFalse(found["legacy"])
        self.assertNotIn("candidate_digest", found["observation"])

    def test_content_is_canonical_and_excludes_candidate_and_labels(self):
        self.assertEqual(content_digest({"b":2,"a":"é"}), content_digest({"a":"é","b":2}))
        row = self.record(candidate_digest="b" * 64, labels=["confirmed_defect"])
        found = self.store.observation("run-1", row["observation"]["id"])
        self.assertNotIn("candidate_digest", found["evidence"])
        self.assertNotIn("labels", found["evidence"])
        self.assertEqual(found["observation"]["content_scheme"], CONTENT_SCHEME)
        self.assertEqual(found["observation"]["patch_sha256"], text_digest("GIT binary patch\nprivate patch"))

    def test_reference_cannot_cross_runs_and_expected_digest_is_enforced(self):
        row = self.record()
        other = copy.deepcopy(self.result)
        other["run_id"] = "run-2"
        self.store.save(other)
        with self.assertRaises(KeyError): self.store.observation("run-2", row["observation"]["id"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.observation("run-1", row["observation"]["id"], "b" * 64)
        with self.assertRaises(ValueError): self.store.observation("run-1", "../private/path")

    def test_tampered_observation_fails_closed(self):
        row = self.record()
        with self.store.connect() as db:
            event = db.execute("SELECT sequence,data FROM events WHERE kind='evidence_observation'").fetchone()
            data = json.loads(event["data"])
            data["evidence"]["ok"] = True
            db.execute("UPDATE events SET data=? WHERE sequence=?", (json.dumps(data), event["sequence"]))
        with self.assertRaisesRegex(ValueError, "content changed"):
            self.store.observation("run-1", row["observation"]["id"])

    def test_legacy_journal_anchor_is_stable_without_rewriting_evidence(self):
        original = copy.deepcopy(self.result)
        event = self.store.event("run-1", "check", {"ok":False,"argv":["python3","check.py"]}, "baseline")
        values = self.store.observations("run-1")
        self.assertEqual(len(values), 1)
        value = values[0]
        UUID(value["observation"]["id"])
        self.assertTrue(value["legacy"])
        self.assertIsNone(value["observation"]["provenance"])
        self.assertEqual(value["sequence"], event["sequence"])
        self.assertEqual(self.store.observations("run-1"), values)
        self.assertEqual(self.store.get("run-1"), original)

    def test_unanchored_legacy_result_is_not_labelable(self):
        self.result["reviews"] = [{"provider":"claude","ok":False}]
        self.store.save(self.result)
        self.assertEqual(self.store.observations("run-1"), [])

    def test_receipt_exports_safe_identity_without_observation_payload(self):
        row = self.record()
        row["observation"]["extra"] = "private output"
        row["observation"]["provenance"]["path"] = "/private/workspace"
        self.result["reviews"] = [row]
        receipt = build_receipt(self.result)
        self.assertEqual(receipt["contract_version"], "1.2")
        self.assertEqual(len(receipt["observations"]), 1)
        self.assertEqual(receipt["reviews"][0]["observation"]["id"], row["observation"]["id"])
        data = json.dumps(receipt)
        for secret in ("private prompt", "private summary", "private output", "/private/workspace", "private patch"):
            self.assertNotIn(secret, data)

    def test_saved_legacy_receipt_bytes_and_result_evidence_remain_unchanged(self):
        record = save_receipt(self.result)
        record["contract_version"] = "1.1"
        record.pop("observations")
        target = Path(self.result["artifacts"]["verification_record"])
        data = json.dumps(record, sort_keys=True, indent=2) + "\n"
        target.write_text(data)
        self.result["artifacts"]["verification_record_sha256"] = hashlib.sha256(data.encode()).hexdigest()
        self.store.save(self.result)
        original = copy.deepcopy(self.store.get("run-1"))
        self.assertEqual(get_receipt(self.store, "run-1"), record)
        self.assertEqual(target.read_text(), data)
        self.assertEqual(self.store.get("run-1"), original)
        legacy = CheckEvidence.model_validate({"schema_version":"1.1","name":"check","argv":["python3"],"ok":False})
        self.assertEqual(legacy.schema_version, "1.1")

    def test_binary_workspace_mutation_changes_recorded_identity(self):
        target = self.project / "image.bin"
        target.write_bytes(bytes(range(256)))
        before = fingerprint(self.project)
        target.write_bytes(bytes(reversed(range(256))))
        after = fingerprint(self.project)
        self.assertNotEqual(before, after)
        row = record_observation(self.store, "run-1", "check", {"ok":False},
            phase_attempt("final"), before=before, after=after)
        self.assertFalse(row["observation"]["provenance"]["unchanged"])

    def test_partial_download_includes_failed_journal_only_identity(self):
        row=self.record(verdict="unavailable",error={"code":"cancelled","message":"private diagnostic output"})
        receipt=get_receipt(self.store,"run-1")
        self.assertEqual(self.store.get("run-1")["reviews"],[])
        self.assertEqual(receipt["observations"][0]["observation"]["id"],row["observation"]["id"])
        self.assertEqual(receipt["observation_scope"],"recorded journal and saved result")
        self.assertEqual(receipt["record_state"],"snapshot")
        self.assertEqual(receipt["observations"][0]["outcome"],"unavailable")
        self.assertEqual(receipt["observations"][0]["error_code"],"cancelled")
        self.assertNotIn("private summary",json.dumps(receipt))
        self.assertNotIn("private diagnostic output",json.dumps(receipt))

    def test_receipt_omits_unknown_provider_error_content(self):
        self.record(error={"code":"private_provider_secret","message":"private details","path":"/private/secret"})
        receipt=get_receipt(self.store,"run-1")
        self.assertEqual(receipt["observations"][0]["outcome"],"unavailable")
        self.assertNotIn("error_code",receipt["observations"][0])
        for secret in ("private_provider_secret","private details","/private/secret"):
            self.assertNotIn(secret,json.dumps(receipt))

    def test_final_record_keeps_discarded_journal_identity_without_raw_payload(self):
        row=self.record()
        save_receipt(self.result,journal_observations=self.store.observations("run-1"))
        self.store.save(self.result)
        receipt=get_receipt(self.store,"run-1")
        self.assertEqual(receipt["observations"][0]["observation"]["id"],row["observation"]["id"])
        self.assertEqual(receipt["record_state"],"final")
        self.assertNotIn("private summary",json.dumps(receipt))


class EvidenceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        git(self.project,"init","-q")
        git(self.project,"config","user.name","Test")
        git(self.project,"config","user.email","test@example.com")
        (self.project / "app.py").write_text("value = 1\n")
        (self.project / "check.py").write_text("assert True\n")
        git(self.project,"add",".")
        git(self.project,"commit","-qm","baseline")
        self.store = Store(Path(self.temp.name) / "state")
        self.addCleanup(self.store.close)
        self.spec = RunSpec(workspace=str(self.project),prompt="Preserve value",
            checks=[CheckSpec(name="check",argv=["python3","-B","check.py"])],
            team=[Participant(provider="claude"),Participant(provider="grok",role="reviewer")],integrate=False)
        result = RunResult(run_id="runtime-1",status="running",spec=self.spec).model_dump()
        result["artifacts"] = {"directory":str(self.store.home / "runs" / "runtime-1"),
            "required_checks":[check.model_dump() for check in self.spec.checks],
            "user_checks":[check.model_dump() for check in self.spec.checks]}
        self.store.save(result)
        self.manager = WorkspaceManager(self.project,Path(result["artifacts"]["directory"]))
        self.manager.prepare()
        self.engine = Engine(self.store,FakeRegistry())
        self.verdict = {"ok":True,"structured_output":{"approved":True,"findings":[],"summary":"Reviewed"}}

    async def assess(self, value=None, **kwargs):
        with patch.object(self.engine,"_provider",new=AsyncMock(return_value=value or self.verdict)):
            return await self.engine._assess_patch("runtime-1",Participant(provider="grok"),
                self.manager.integration_path,self.spec.prompt,{"acceptance":["value remains 1"]},"fix",patch="binary diff",**kwargs)

    async def test_worker_attempt_and_rejected_verdict_survive_without_candidate(self):
        value={"ok":True,"structured_output":{"approved":False,"findings":[{}],"summary":"Reject"}}
        row = await self.assess(value,observation_attempt=phase_attempt("task","fix",2))
        self.assertFalse(row["ok"])
        self.assertEqual(row["verdict"],"rejected")
        self.assertEqual(row["observation"]["worker_attempt"],2)
        self.assertEqual(row["observation"]["provenance"]["scheme"],READONLY_SCHEME)
        self.assertEqual(self.store.observation("runtime-1",row["observation"]["id"])["evidence"]["verdict"],"rejected")

    async def test_retries_keep_distinct_immutable_references(self):
        first = await self.assess()
        second = await self.assess()
        self.assertNotEqual(first["observation"]["id"],second["observation"]["id"])
        self.assertNotEqual(first["observation"]["phase_attempt_id"],second["observation"]["phase_attempt_id"])
        self.assertEqual(len(self.store.observations("runtime-1")),2)

    async def test_review_observation_is_durable_before_run_save(self):
        original = self.store.save
        def fail_save(result):
            if result["reviews"]: raise RuntimeError("crash before result update")
            original(result)
        with patch.object(self.store,"save",side_effect=fail_save):
            with self.assertRaisesRegex(RuntimeError,"crash"):
                await self.assess()
        self.assertEqual(self.store.get("runtime-1")["reviews"],[])
        self.assertEqual(len(self.store.observations("runtime-1")),1)

    async def test_cancelled_reviewer_leaves_unavailable_observation(self):
        with patch.object(self.engine,"_provider",new=AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await self.engine._assess_patch("runtime-1",Participant(provider="grok"),self.manager.integration_path,"request",{},"fix")
        observation = self.store.observations("runtime-1")[0]
        self.assertEqual(observation["evidence"]["error"]["code"],"cancelled")
        self.assertEqual(observation["evidence"]["verdict"],"unavailable")
        self.assertNotIn("validated_fingerprint",self.store.get("runtime-1")["artifacts"])

    async def test_malformed_then_valid_review_retains_discarded_attempt(self):
        malformed={"ok":True,"structured_output":{"approved":True,"findings":[{}],"summary":"Malformed"}}
        with patch.object(self.engine,"_provider",new=AsyncMock(side_effect=[malformed,self.verdict])):
            row=await self.engine._assess_patch("runtime-1",Participant(provider="grok"),self.manager.integration_path,"request",{},"fix")
        values=self.store.observations("runtime-1")
        self.assertEqual(len(values),2)
        self.assertEqual(values[0]["evidence"]["verdict"],"unavailable")
        self.assertFalse(values[0]["evidence"]["ok"])
        self.assertEqual(values[0]["observation"]["reviewer_attempt"],1)
        self.assertEqual(values[1]["observation"]["reviewer_attempt"],2)
        self.assertEqual(values[0]["observation"]["phase_attempt_id"],values[1]["observation"]["phase_attempt_id"])
        self.assertTrue(row["ok"])
        self.assertEqual(self.store.get("runtime-1")["reviews"],[row])

    async def test_cancelled_consultation_retains_observation(self):
        spec=self.spec.model_copy(update={"mode":"review","team":[Participant(provider="claude")]})
        with patch.object(self.engine,"checkpoint",new=AsyncMock()), \
             patch.object(self.engine,"_provider",new=AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await self.engine._review_run("runtime-1",spec,self.manager,Path(self.store.get("runtime-1")["artifacts"]["directory"]))
        values=self.store.observations("runtime-1")
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]["observation"]["phase"],"consultation")
        self.assertEqual(values[0]["evidence"]["error"]["code"],"cancelled")
        self.assertEqual(self.store.get("runtime-1")["reviews"],[])

    async def test_changed_review_workspace_still_blocks_approval(self):
        async def changed(*args,**kwargs):
            (self.manager.integration_path / "app.py").write_bytes(b"\x00\xff")
            return self.verdict
        with patch.object(self.engine,"_provider",new=changed):
            row = await self.engine._assess_patch("runtime-1",Participant(provider="grok"),self.manager.integration_path,"request",{},"fix")
        self.assertFalse(row["ok"])
        self.assertEqual(row["verdict"],"unavailable")
        self.assertFalse(row["observation"]["provenance"]["unchanged"])

    async def test_final_checks_and_review_share_phase_attempt(self):
        outcome=SimpleNamespace(stdout="checked",stderr="",exit_code=0,failure=None)
        with patch.object(self.engine,"checkpoint",new=AsyncMock()), \
             patch.object(self.engine,"_ensure_environment",new=AsyncMock(return_value=({},None))), \
             patch.object(self.engine,"_command",new=AsyncMock(return_value=outcome)), \
             patch.object(self.engine,"_provider",new=AsyncMock(return_value=self.verdict)):
            await self.engine._verify("runtime-1",self.spec,self.manager,self.spec.checks)
        result=self.store.get("runtime-1")
        check,review=result["checks"][0],result["reviews"][-1]
        self.assertEqual(check["schema_version"],"1.2")
        self.assertEqual(check["observation"]["phase_attempt_id"],review["observation"]["phase_attempt_id"])
        self.assertEqual(check["observation"]["phase"],"final")
        self.assertEqual(check["observation"]["provenance"]["before_sha256"],review["observation"]["provenance"]["before_sha256"])
        self.assertEqual(result["artifacts"]["current_verification_attempt"]["phase_attempt_id"],check["observation"]["phase_attempt_id"])

    async def test_aborted_revalidation_marks_old_checks_historical(self):
        outcome=SimpleNamespace(stdout="checked",stderr="",exit_code=0,failure=None)
        with patch.object(self.engine,"checkpoint",new=AsyncMock()), \
             patch.object(self.engine,"_ensure_environment",new=AsyncMock(return_value=({},None))), \
             patch.object(self.engine,"_command",new=AsyncMock(return_value=outcome)), \
             patch.object(self.engine,"_provider",new=AsyncMock(return_value=self.verdict)):
            await self.engine._verify("runtime-1",self.spec,self.manager,self.spec.checks)
        previous=self.store.get("runtime-1")
        with patch.object(self.engine,"_checks",new=AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await self.engine._verify("runtime-1",self.spec,self.manager,self.spec.checks)
        result=self.store.get("runtime-1")
        self.assertNotIn("validated_fingerprint",result["artifacts"])
        self.assertEqual(result["checks"],previous["checks"])
        self.assertNotEqual(result["artifacts"]["current_verification_attempt"]["phase_attempt_id"],
            result["checks"][0]["observation"]["phase_attempt_id"])

    async def test_unavailable_environment_leaves_journal_evidence(self):
        with patch.object(self.engine,"_ensure_environment",new=AsyncMock(side_effect=ValueError("setup failed"))):
            with self.assertRaisesRegex(ValueError,"setup failed"):
                await self.engine._checks("runtime-1",self.manager.integration_path,self.spec.checks)
        values=self.store.observations("runtime-1")
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]["evidence"]["error"],"check_unavailable")
        self.assertFalse(values[0]["evidence"]["ok"])

    async def test_legacy_pending_candidate_digest_does_not_gain_defaults(self):
        result=self.store.get("runtime-1")
        result.update(status="completed",diff=self.manager.diff(),checks=[{"ok":True}],
            reviews=[{"task_id":"integration","provider":"grok","ok":True}],
            tasks=[{"provider":"claude","status":"completed"}])
        result["artifacts"].update(verified_only=True,validated_fingerprint=result["diff"],
            source_snapshot_sha256=self.manager.fingerprint(self.project))
        self.store.save(result)
        original=copy.deepcopy(result)
        identity={"run_id":result["run_id"],"policy":POLICY,"spec":digest(result["spec"]),
            "patch":digest(result["diff"]),"source":result["artifacts"]["source_snapshot_sha256"],
            "tree":self.manager.fingerprint(self.manager.integration_path),"delivery_target":digest(None),
            "evidence":digest({"checks":result["checks"],"reviews":result["reviews"],
                "validated":result["artifacts"]["validated_fingerprint"],
                "required_checks":result["artifacts"]["required_checks"]})}
        candidate=await Candidates(self.engine).capture("runtime-1")
        self.assertEqual(candidate["identity"],identity)
        self.assertEqual(candidate["digest"],digest(identity))
        self.assertEqual(self.store.get("runtime-1"),original)
        self.assertNotIn("observation",original["checks"][0])

    async def test_recovery_records_link_to_generated_steering(self):
        result=self.store.get("runtime-1")
        result.update(status="needs_attention",errors=[{"message":"Combined checks failed; repair and validate again"}])
        self.store.save(result)
        with patch.object(self.engine,"control",return_value=result):
            self.engine.recover_run("runtime-1","repair_candidate")
        events=self.store.events("runtime-1")
        steering=next(event for event in events if event["kind"] == "steering")
        recovery=next(event for event in events if event["kind"] == "recovery_requested")
        self.assertEqual(recovery["data"]["steering_sequence"],steering["sequence"])

    async def verified(self):
        outcome=SimpleNamespace(stdout="checked",stderr="",exit_code=0,failure=None)
        with patch.object(self.engine,"checkpoint",new=AsyncMock()), \
             patch.object(self.engine,"_ensure_environment",new=AsyncMock(return_value=({},None))), \
             patch.object(self.engine,"_command",new=AsyncMock(return_value=outcome)), \
             patch.object(self.engine,"_provider",new=AsyncMock(return_value=self.verdict)):
            await self.engine._verify("runtime-1",self.spec,self.manager,self.spec.checks)

    async def integrate_and_complete(self):
        with patch.object(self.engine,"checkpoint",new=AsyncMock()):
            await self.engine._integrate("runtime-1",self.spec,self.manager)
        result=self.store.get("runtime-1")
        result["status"]="completed"
        self.store.save(result)

    async def test_empty_commit_after_verification_blocks_integration(self):
        await self.verified()
        git(self.manager.integration_path,"commit","--allow-empty","-qm","Unverified Git state")
        with self.assertRaisesRegex(ValueError,"workspace or Git state changed"):
            await self.integrate_and_complete()
        self.assertFalse(self.store.get("runtime-1")["artifacts"].get("verified_only",False))

    async def test_empty_commit_after_integration_blocks_first_candidate_capture(self):
        await self.verified()
        await self.integrate_and_complete()
        git(self.manager.integration_path,"commit","--allow-empty","-qm","Unverified Git state")
        with self.assertRaisesRegex(ValueError,"workspace or Git state changed"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_binary_content_mutation_blocks_first_candidate_capture(self):
        await self.verified()
        await self.integrate_and_complete()
        (self.manager.integration_path / "app.py").write_bytes(b"\x00\xffunverified")
        with self.assertRaisesRegex(ValueError,"workspace or Git state changed"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_unchanged_observations_survive_integration_and_candidate_capture(self):
        await self.verified()
        await self.integrate_and_complete()
        candidate=await Candidates(self.engine).capture("runtime-1")
        self.assertTrue(all(gate["status"] == "passed" for gate in candidate["gates"]))
        result=self.store.get("runtime-1")
        self.assertEqual(result["artifacts"]["verified_workspace_binding"]["workspace_state_sha256"],fingerprint(self.manager.integration_path))

    async def test_changed_saved_result_evidence_cannot_reuse_journal_identity(self):
        await self.verified()
        await self.integrate_and_complete()
        result=self.store.get("runtime-1")
        result["checks"][0]["output"]="Changed after verification"
        self.store.save(result)
        with self.assertRaisesRegex(ValueError,"changed from its recorded observation"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_candidate_identity_assembly_rejects_concurrent_git_change(self):
        await self.verified()
        await self.integrate_and_complete()
        original=self.manager.fingerprint
        def changed(path):
            if Path(path).resolve() == self.manager.integration_path.resolve():
                git(path,"commit","--allow-empty","-qm","Changed during identity assembly")
            return original(path)
        candidates=Candidates(self.engine)
        with patch.object(candidates,"manager",return_value=self.manager), \
             patch.object(self.manager,"fingerprint",side_effect=changed):
            with self.assertRaisesRegex(ValueError,"while its approval identity was captured"):
                await candidates.capture("runtime-1")

    async def test_modern_evidence_cannot_downgrade_to_legacy_when_metadata_is_removed(self):
        await self.verified()
        await self.integrate_and_complete()
        result=self.store.get("runtime-1")
        for row in [*result["checks"],*result["reviews"]]:
            row.pop("observation",None)
            row.pop("schema_version",None)
        self.store.save(result)
        with self.assertRaisesRegex(ValueError,"incomplete workspace provenance"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_changed_prompt_before_first_candidate_capture_is_refused(self):
        await self.verified()
        await self.integrate_and_complete()
        result=self.store.get("runtime-1")
        result["spec"]["prompt"]="New unchecked goal"
        self.store.save(result)
        with self.assertRaisesRegex(ValueError,"request or check contract changed"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_changed_check_argv_before_first_candidate_capture_is_refused(self):
        await self.verified()
        await self.integrate_and_complete()
        result=self.store.get("runtime-1")
        result["spec"]["checks"][0]["argv"]=["python3","different-check.py"]
        self.store.save(result)
        with self.assertRaisesRegex(ValueError,"request or check contract changed"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_changed_required_checks_before_first_candidate_capture_is_refused(self):
        await self.verified()
        await self.integrate_and_complete()
        result=self.store.get("runtime-1")
        result["artifacts"]["required_checks"]=[]
        self.store.save(result)
        with self.assertRaisesRegex(ValueError,"request or check contract changed"):
            await Candidates(self.engine).capture("runtime-1")

    async def test_legitimate_failed_task_resolution_keeps_original_verified_contract(self):
        result=self.store.get("runtime-1")
        result["tasks"]=[{"id":"fix","title":"Original task","provider":"claude","prompt":"Original criterion",
            "files":["app.py"],"acceptance":["Original criterion"],"dependencies":[],"attempts":1,"status":"failed"},
            {"id":"replacement","title":"Replacement","provider":"claude","prompt":"Preserve value",
             "files":["app.py"],"acceptance":["value remains 1"],"dependencies":[],"attempts":1,"status":"completed"}]
        self.store.save(result)
        await self.verified()
        with patch.object(self.engine,"_provider",new=AsyncMock(return_value=self.verdict)):
            await self.engine._action("runtime-1",self.spec,self.manager,
                CoordinatorAction(id="resolve",action="resolve_task",task_ids=["fix"],selected_task="replacement"))
        await self.integrate_and_complete()
        candidate=await Candidates(self.engine).capture("runtime-1")
        self.assertTrue(all(gate["status"] == "passed" for gate in candidate["gates"]))
        result=self.store.get("runtime-1")
        self.assertEqual(result["tasks"][0]["status"],"resolved")
        self.assertEqual(result["reviews"][-1]["task_id"],"resolution-fix")


if __name__ == "__main__":
    unittest.main()
