"""Task-local requirements stay durable without changing versioned recipes."""
import copy
import sys
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from parallax import authority
from parallax.candidates import digest
from parallax.models import CheckSpec
from parallax.workflows import (
    RevisionRequest, TemplateInput, Workflows,
    WorkflowStart, WorkflowTaskSettings,
)
import test_workflows as workflow_fixtures


class TaskOverridesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflow_fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = workflow_fixtures.WorkflowTests.asyncTearDown
    check_project = workflow_fixtures.WorkflowTests.check_project
    request = workflow_fixtures.WorkflowTests.request
    settle = workflow_fixtures.WorkflowTests.settle

    def task_request(self, **changes):
        return WorkflowStart.model_validate({**self.request().model_dump(), "schema_version":"2.0", **changes})

    async def test_modernization_recipe_is_captured_and_cannot_be_edited_in_place(self):
        recipe=self.service.template("modernize-one-component",1)
        self.assertIn("holdout expectations unchanged",recipe["instructions"])
        self.assertIn("independent compatibility review",recipe["instructions"])
        with patch.object(self.service,"_launch",AsyncMock()):
            started=await self.service.start(self.task_request(template_id=recipe["id"]))
        value=self.service.public(self.service.get(started["id"]))
        self.assertEqual(value["template_details"]["instructions"],recipe["instructions"])
        self.assertEqual(value["task_settings"]["instructions"],recipe["instructions"])
        with self.assertRaisesRegex(ValueError,"personal copy"):
            self.service.save_template(TemplateInput(name="Edited"),recipe["id"])

    async def test_history_summary_does_not_repeat_large_comment_bodies(self):
        with patch.object(self.service,"_launch",AsyncMock()):
            started=await self.service.start(self.task_request())
        value=self.service.get(started["id"])
        value["comments"]=[{"message":"private review detail"*200} for _ in range(50)]
        brief=self.service.public(value,brief=True)
        self.assertEqual(brief["comment_count"],50)
        self.assertNotIn("comments",brief)
        self.assertEqual(self.service.public(value)["comments"],value["comments"])

    async def test_task_overrides_survive_restart_without_creating_or_editing_recipe(self):
        saved_template = copy.deepcopy(self.template)
        settings = WorkflowTaskSettings(instructions="Keep the public add signature.",
            checks=[CheckSpec(name="Task check", argv=[sys.executable,"-B","check.py"], timeout=47)])
        request = self.task_request(task_settings=settings, minutes=19)
        with patch.object(self.service, "_launch", AsyncMock()):
            started = await self.service.start(request)
        expected = started["task_settings"]
        settings.instructions = "Mutated browser object"
        settings.checks[0].name = "Mutated browser check"
        self.assertEqual(self.service.template(saved_template["id"], 1), saved_template)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workflow_templates WHERE id=?", (saved_template["id"],)).fetchone()[0], 1)
        await self.service.close()
        self.service = Workflows(self.engine, self.check_project)
        restored = self.service.public(self.service.get(started["id"]))
        self.assertEqual(restored["task_settings"], expected)
        self.assertEqual(restored["spec"]["checks"], expected["checks"])
        self.assertIn(expected["instructions"], restored["spec"]["prompt"])
        self.assertEqual(restored["spec"]["limits"]["minutes"], 19)
        self.assertEqual(restored["template_details"]["instructions"], saved_template["instructions"])

    async def test_missing_override_inherits_and_explicit_empty_values_replace(self):
        template = self.service.save_template(TemplateInput(name="Instructions", instructions="Recipe instructions",
            checks=self.template["checks"]))
        with patch.object(self.service, "_launch", AsyncMock()):
            inherited = await self.service.start(self.task_request(template_id=template["id"]))
            replaced = await self.service.start(self.task_request(template_id=template["id"],
                task_settings={"instructions":"", "checks":[]}))
        self.assertEqual(inherited["task_settings"]["instructions"], "Recipe instructions")
        self.assertEqual(inherited["spec"]["checks"], template["checks"])
        self.assertEqual(replaced["task_settings"], {"schema_version":"1.0", "instructions":"", "checks":[]})
        self.assertEqual(replaced["spec"]["checks"], [])
        self.assertNotIn("Recipe instructions", replaced["spec"]["prompt"])
        self.assertEqual(self.service.template(template["id"], 1)["instructions"], "Recipe instructions")

    async def test_retry_fingerprint_binds_each_override_and_preserves_identity_and_budget(self):
        request = self.task_request(task_settings={"instructions":"Task only", "checks":self.template["checks"]}, minutes=13)
        with patch.object(self.service, "_launch", AsyncMock()) as launch:
            first = await self.service.start(request)
            second = await self.service.start(request)
            self.assertEqual(first["id"], second["id"])
            launch.assert_awaited_once()
            for changed in (
                {"instructions":"Different", "checks":self.template["checks"]},
                {"instructions":"Task only", "checks":[]},
            ):
                with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "different inputs"):
                    await self.service.start(request.model_copy(update={"task_settings":WorkflowTaskSettings.model_validate(changed)}))
        self.assertEqual(self.service.get(first["id"])["spec"]["limits"]["minutes"], 13)
        self.assertEqual(len(self.service.listing()), 1)

    async def test_legacy_start_request_hash_and_retry_remain_compatible(self):
        request = self.request()
        # Legacy requests had none of these optional fields, so their hashes must not include them.
        old_hash = digest(request.model_dump(mode="json", exclude={"parent_workflow_id","schema_version","github_binding","task_settings","coordinator_turns"}))
        with patch.object(self.service, "_launch", AsyncMock()) as launch:
            first = await self.service.start(request)
            self.assertEqual(self.service.get(first["id"])["request_hash"], old_hash)
            await self.service.start(request)
            launch.assert_awaited_once()

    async def test_fresh_project_followup_inherits_effective_settings_after_recipe_update(self):
        request = self.task_request(task_settings={"instructions":"Task-local acceptance criteria.", "checks":[]})
        with patch.object(self.service, "_launch", AsyncMock()):
            parent = await self.service.start(request)
            self.service.save_template(TemplateInput(name="New recipe", instructions="Different requirements."), self.template["id"])
            child = await self.service.start(WorkflowStart(request_id=uuid4(), schema_version="2.0",
                workspace=str(self.project), parent_workflow_id=parent["id"], prompt="Add another case."))
        self.assertEqual(child["task_settings"], parent["task_settings"])
        self.assertEqual(child["spec"]["checks"], [])
        self.assertIn("Task-local acceptance criteria.", child["spec"]["prompt"])
        self.assertNotIn("Different requirements.", child["spec"]["prompt"])
        self.assertEqual(child["template"]["version"], 1)
        self.assertNotIn("candidate_seed", self.service.get(child["id"]))

    async def test_real_candidate_revision_keeps_effective_checks_and_original_baseline(self):
        request = self.task_request(task_settings={"instructions":"Preserve add(a, b). Explain the fix.",
            "checks":[{"name":"Task-specific addition", "argv":[sys.executable,"-B","check.py"], "timeout":47}]})
        started = await self.service.start(request)
        parent = await self.settle(started["id"])
        self.assertEqual(parent["status"], "awaiting_approval", parent["error"])
        run = self.store.get(parent["run_id"])
        revision_request = RevisionRequest(request_id=uuid4(), candidate_digest=parent["candidate"]["digest"], correction="Explain the addition.")
        self.registry.turn = 0
        original_run = self.registry.run
        async def revised_patch(provider, **kwargs):
            result = await original_run(provider, **kwargs)
            if kwargs["mode"] == "edit":
                (kwargs["workspace"] / "maths.py").write_text("def add(a, b):\n    # Add both operands.\n    return a + b\n")
            return result
        with patch.object(self.registry, "run", side_effect=revised_patch):
            child = await self.service.revise(parent["id"], revision_request)
            child = await self.settle(child["id"])
        self.assertEqual(child["status"], "awaiting_approval", child["error"])
        child_run = self.store.get(child["run_id"])
        self.assertEqual(child["task_settings"], parent["task_settings"])
        self.assertEqual(child["template"], parent["template"])
        self.assertEqual(child["spec"]["checks"], parent["spec"]["checks"])
        self.assertEqual(child["spec"]["limits"], parent["spec"]["limits"])
        self.assertIn(parent["task_settings"]["instructions"], child["spec"]["prompt"])
        self.assertEqual(child_run["artifacts"]["baseline_snapshot_sha256"], run["artifacts"]["baseline_snapshot_sha256"])
        self.assertFalse(child_run["artifacts"]["baseline_checks"][0]["ok"])
        self.assertTrue(child_run["checks"][0]["ok"])
        self.assertEqual(child_run["checks"][0]["name"], "Task-specific addition")
        self.assertNotIn("decision", child)
        self.assertNotEqual(parent["candidate"]["digest"], child["candidate"]["digest"])
        self.assertEqual((await self.service.revise(parent["id"], revision_request))["id"], child["id"])

    async def test_team_task_settings_do_not_bypass_role_project_or_actor_authorization(self):
        context = {"version":"2.0", "team":True, "workspace":"team", "actor":"developer", "role":"developer", "projects":[str(self.project)]}
        token = authority.current.set(context)
        try:
            request = self.task_request(template_id="verified-change", task_settings={"instructions":"Team task", "checks":[]})
            with patch.object(self.service, "_launch", AsyncMock()):
                first = await self.service.start(request)
                self.assertEqual(first["requester"], "developer")
                authority.current.set({**context,"actor":"other"})
                with self.assertRaisesRegex(ValueError, "another actor"):
                    await self.service.start(request)
                authority.current.set({**context,"role":"reviewer"})
                with self.assertRaises(HTTPException) as failure:
                    await self.service.start(request.model_copy(update={"request_id":uuid4()}))
                self.assertEqual(failure.exception.status_code, 403)
                authority.current.set({**context,"workspace":"other-team"})
                with self.assertRaises(KeyError):
                    self.service.get(first["id"])
                authority.current.set(context)
                with self.assertRaisesRegex(ValueError, "Project not approved"):
                    await self.service.start(request.model_copy(update={"request_id":uuid4(),"workspace":str(self.root)}))
        finally:
            authority.current.reset(token)


class TaskSettingsContractTests(unittest.TestCase):
    def test_strict_additive_contract_rejects_unsafe_unknown_and_coerced_inputs(self):
        valid = {"request_id":str(uuid4()), "schema_version":"2.0", "workspace":"/project", "prompt":"Fix it"}
        bad_settings = [
            {"schema_version":"2.0"}, {"instructions":7}, {"instructions":"x" * 4001},
            {"role":"owner"}, {"checks":"npm test"},
            {"checks":[{"name":"Test", "argv":["npm","test"], "timeout":"30"}]},
            {"checks":[{"name":"Test", "argv":["npm","test"], "timeout":True}]},
            {"checks":[{"name":"Test", "argv":["npm","test"], "cwd":"../secret"}]},
            {"checks":[{"name":"Test", "argv":["npm","test"], "commit":"arbitrary"}]},
            {"checks":[{"name":"Test", "argv":["npm","test"]}] * 65},
        ]
        for settings in bad_settings:
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                WorkflowStart.model_validate({**valid,"task_settings":settings})
        with self.assertRaises(ValidationError):
            WorkflowStart.model_validate({**valid,"schema_version":"1.0","task_settings":{"instructions":"Task"}})
        with self.assertRaises(ValidationError):
            RevisionRequest.model_validate({"request_id":str(uuid4()), "candidate_digest":"a" * 64,
                "correction":"Fix", "task_settings":{"checks":[]}})
