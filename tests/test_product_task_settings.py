"""Exercise product task overrides across authenticated HTTP and durable relay boundaries.

The identity provider is mocked. The app, validation, SQLite queues, authorization,
and worker dispatch are real; no provider, network, or GitHub publication is used.
"""
import asyncio
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException

from parallax.executors import ExecutorHub, encode
from parallax.server import create_app
from parallax.store import Store

from test_accounts import HostedFixture, ORIGIN, user
import test_workflows as fixtures


FEATURES = ["workflow-v2", "workflow-task-settings-v1"]


class TaskSettingsRelayTests(HostedFixture):
    def setUp(self):
        super().setUp()
        self.client = self.signed_in(user(9720, "settings-owner"))
        self.worker = self.pair(self.client)
        self.hub = self.app.state.executors
        self.hub.features(self.worker["id"], FEATURES)
        self.principal = self.app.state.accounts.principal(self.client.cookies.get("parallax_session"))
        self.headers = {"Origin": ORIGIN}
        self.route = f"/api/executors/{self.worker['id']}/proxy/workflows"

    def body(self):
        return {"request_id": str(uuid4()), "schema_version": "2.0", "workspace": "/project",
                "prompt": "Fix an explicit bounded bug", "task_settings": {
                    "schema_version": "1.0", "instructions": "Keep the public API stable",
                    "checks": [{"name": "regression", "argv": ["python", "-B", "check.py"], "timeout": 30}]}}

    def seed_queue(self, body=None):
        identifier = str(uuid4())
        authority = {"version": "2.0", "workspace": self.principal.workspace,
                     "actor": self.principal.account["id"], "role": "owner", "team": False,
                     "projects": ["/project"]}
        payload = {"method": "POST", "path": "/api/workflows", "query": "", "body": body or self.body(),
                   "authority": authority, "expires_at": time.time() + 60,
                   "requester": {"session": self.principal.session, "workspace": self.principal.workspace,
                                 "actor": self.principal.account["id"]}}
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)",
                       (identifier, self.worker["id"], encode(payload), time.time()))
        return identifier, payload

    def post_and_reply(self, path, body, reply_body=None, reply_status=200):
        """The authenticated browser actually queues; the paired worker replies."""
        route = f"/api/executors/{self.worker['id']}/proxy/{path}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.post, route, json=body, headers=self.headers)
            deadline = time.monotonic() + 3
            command = None
            while time.monotonic() < deadline:
                with self.store.connect() as db:
                    command = db.execute("SELECT id FROM worker_commands WHERE worker=? AND response IS NULL ORDER BY created DESC LIMIT 1",
                                         (self.worker["id"],)).fetchone()
                if command:
                    break
                if pending.done():
                    response = pending.result()
                    self.fail(f"Expected an actual queued request, received {response.status_code}: {response.text}")
                time.sleep(.005)
            self.assertIsNotNone(command, "An authenticated request must actually enter the durable queue")
            bearer = {"Authorization": "Bearer " + self.worker["token"]}
            worker_client = self.browser()
            dispatch = worker_client.get("/api/worker/next", headers=bearer)
            self.assertEqual(dispatch.status_code, 200, dispatch.text)
            selected = next((item for item in dispatch.json() if item["id"] == command["id"]), None)
            self.assertIsNotNone(selected, dispatch.text)
            reply = worker_client.post("/api/worker/reply", headers=bearer, json={"id": command["id"],
                "status": reply_status, "content_type": "application/json", "body": reply_body or {"id": body.get("request_id", "cancelled")}})
            self.assertEqual(reply.status_code, 200, reply.text)
            response = pending.result(timeout=4)
        self.assertEqual(response.status_code, reply_status, response.text)
        return response.json()

    def effective_parent(self, overrides=True):
        body = self.body()
        if not overrides:
            body.pop("task_settings")
        # Simulate the dangerous downgraded response shape: the actual worker
        # reply includes no new fields. Requirements must come from the queue.
        response = self.post_and_reply("workflows", body, {"id": body["request_id"], "schema_version": "2.0",
            "workspace": "/project", "template_details": {"instructions": "Original recipe instructions"}})
        self.assertNotIn("task_settings", response)
        return body["request_id"]

    def downgrade_and_restart(self):
        self.hub.features(self.worker["id"], ["workflow-v2"])
        with self.store.connect() as db:
            db.execute("DELETE FROM worker_cache WHERE worker=?", (self.worker["id"],))
            db.execute("DELETE FROM worker_commands WHERE worker=?", (self.worker["id"],))
            db.execute("DELETE FROM worker_command_dispatch WHERE id NOT IN (SELECT id FROM worker_commands)")
        self.hub = ExecutorHub(Store(self.store.home), accounts=self.app.state.accounts)

    def request_direct(self, path, body):
        # Allow durable admission under concurrent suite load. A 10ms budget can
        # expire before queueing, which tests of unanswered worker recovery must
        # distinguish from a request that was actually admitted.
        return asyncio.run(self.hub.request(self.worker["id"], "POST", "/api/" + path, "", body,
                                            workspace=self.principal.workspace, timeout=.5,
                                            authority={"version": "2.0", "workspace": self.principal.workspace,
                                                "actor": self.principal.account["id"], "role": "owner", "team": False,
                                                "projects": ["/project"]},
                                            requester={"session": self.principal.session, "workspace": self.principal.workspace,
                                                "actor": self.principal.account["id"]}))

    def test_prior_v2_worker_refuses_overrides_before_queueing(self):
        self.hub.features(self.worker["id"], ["workflow-v2"])
        with patch.object(self.hub, "request", AsyncMock()) as queue:
            response = self.client.post(self.route, json=self.body(), headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Update", response.text)
        queue.assert_not_awaited()

    def test_unchanged_tasks_remain_compatible_with_prior_v2_worker(self):
        self.hub.features(self.worker["id"], ["workflow-v2"])
        for null_settings in (False, True):
            with self.subTest(null_settings=null_settings):
                body = self.body()
                if null_settings:
                    body["task_settings"] = None
                else:
                    body.pop("task_settings")
                with patch.object(self.hub, "request", AsyncMock(return_value={"status": 200, "body": {"id": body["request_id"]}})) as queue:
                    response = self.client.post(self.route, json=body, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(queue.await_args.args[4], body)

    def test_supported_relay_preserves_exact_settings_and_uses_authenticated_actor(self):
        body = self.body()
        body["task_settings"]["instructions"] = "<script>not HTML</script>\nKeep $HOME literal"
        body["task_settings"]["checks"][0]["argv"] += ["a b", "$(do-not-run)"]
        forged = encode({"version": "2.0", "workspace": "foreign", "actor": "invented", "role": "reviewer", "team": True})
        with patch.object(self.hub, "request", AsyncMock(return_value={"status": 200, "body": {"id": body["request_id"]}})) as queue:
            response = self.client.post(self.route, json=body, headers={**self.headers, "X-Parallax-Authority": forged})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(queue.await_args.args[4], body)
        context = queue.await_args.kwargs["authority"]
        self.assertEqual(context["actor"], self.principal.account["id"])
        self.assertEqual(context["workspace"], self.principal.workspace)
        self.assertEqual(context["role"], "owner")
        self.assertFalse(context["team"])
        self.assertEqual(queue.await_args.kwargs["requester"]["session"], self.principal.session)

    def test_foreign_account_cannot_queue_settings_on_known_worker(self):
        stranger = self.signed_in(user(9721, "settings-stranger"))
        with patch.object(self.hub, "request", AsyncMock()) as queue:
            response = stranger.post(self.route, json=self.body(), headers=self.headers)
        self.assertEqual(response.status_code, 404, response.text)
        queue.assert_not_awaited()

    def test_worker_downgrade_is_rechecked_after_restart_before_first_dispatch(self):
        identifier, _ = self.seed_queue()
        self.hub.features(self.worker["id"], ["workflow-v2"])
        restarted = ExecutorHub(Store(self.store.home), accounts=self.app.state.accounts)
        self.assertEqual(restarted.pending(self.worker["id"]), [])
        self.assertFalse(restarted.dispatched(self.worker["id"], identifier))
        with self.store.connect() as db:
            response = json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()[0])
        self.assertEqual(response["status"], 409)
        self.assertIn("Update", response["body"]["detail"])

    def test_dispatched_override_receipt_survives_downgrade_and_recovery(self):
        identifier, payload = self.seed_queue()
        first = self.hub.pending(self.worker["id"])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["body"], payload["body"])
        self.hub.features(self.worker["id"], ["workflow-v2"])
        restarted = ExecutorHub(Store(self.store.home), accounts=self.app.state.accounts)
        self.assertEqual(restarted.pending(self.worker["id"]), [])
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT response FROM worker_commands WHERE id=?", (identifier,)).fetchone()[0])
        restarted.features(self.worker["id"], FEATURES)
        self.assertEqual(restarted.pending(self.worker["id"]), first)
        result = {"status": 200, "body": {"id": payload["body"]["request_id"]}, "content_type": "application/json"}
        self.assertEqual(restarted.complete(self.worker["id"], identifier, result), {"ok": True})
        self.assertEqual(restarted.pending(self.worker["id"]), [])

    def test_inherited_actions_refuse_after_cache_loss_old_reply_and_relay_restart(self):
        parent = self.effective_parent()
        self.downgrade_and_restart()
        followup = self.body()
        followup.pop("task_settings")
        followup["parent_workflow_id"] = parent
        operations = [("workflows", followup),
            (f"workflows/{parent}/revise", {"request_id": str(uuid4()), "candidate_digest": "a" * 64, "correction": "Clarify intent"}),
            (f"workflows/{parent}/resume", {}),
            *[(f"workflows/{parent}/{action}", {"request_id": str(uuid4()), "candidate_digest": "a" * 64})
              for action in ("approve", "apply", "publication-preview", "begin-publication")]]
        for path, body in operations:
            with self.subTest(path=path):
                with self.assertRaises(HTTPException) as error:
                    self.request_direct(path, body)
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn("Update", error.exception.detail)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands WHERE worker=?", (self.worker["id"],)).fetchone()[0], 0)

    def test_cancellation_stays_available_for_a_new_feature_lineage_on_an_old_worker(self):
        parent = self.effective_parent()
        self.downgrade_and_restart()
        response = self.post_and_reply(f"workflows/{parent}/cancel", {}, {"id": parent, "status": "cancelled"})
        self.assertEqual(response["status"], "cancelled")

    def test_child_feature_stamp_survives_omitted_fields_and_consumed_responses(self):
        parent = self.effective_parent()
        child = self.body()
        child.pop("task_settings")
        child["parent_workflow_id"] = parent
        self.post_and_reply("workflows", child)
        revision = {"request_id": str(uuid4()), "candidate_digest": "a" * 64, "correction": "Clarify the saved candidate"}
        # The relay performs a read-only lookup before a revision. Use the hub
        # directly for this operation to isolate propagation from that lookup.
        async def queue_revision():
            request = asyncio.create_task(self.hub.request(self.worker["id"], "POST", f"/api/workflows/{parent}/revise", "", revision,
                workspace=self.principal.workspace, timeout=2))
            await asyncio.sleep(.01)
            commands = self.hub.pending(self.worker["id"])
            self.assertEqual(len(commands), 1)
            self.hub.complete(self.worker["id"], commands[0]["id"], {"status": 200, "body": {"id": revision["request_id"]}, "content_type": "application/json"})
            return await request
        asyncio.run(queue_revision())
        self.downgrade_and_restart()
        for identifier in (child["request_id"], revision["request_id"]):
            with self.subTest(identifier=identifier):
                with self.assertRaises(HTTPException) as error:
                    self.request_direct(f"workflows/{identifier}/resume", {})
                self.assertEqual(error.exception.status_code, 409)

    def test_same_request_id_cannot_strip_an_existing_feature_requirement(self):
        parent = self.effective_parent()
        self.downgrade_and_restart()
        collision = self.body()
        collision.pop("task_settings")
        collision["request_id"] = parent
        with self.assertRaises(HTTPException) as error:
            self.request_direct("workflows", collision)
        self.assertEqual(error.exception.status_code, 409)

    def test_unmodified_legacy_lineage_is_still_usable_on_an_older_v2_worker(self):
        parent = self.effective_parent(overrides=False)
        self.downgrade_and_restart()
        followup = self.body()
        followup.pop("task_settings")
        followup["parent_workflow_id"] = parent
        response = self.post_and_reply("workflows", followup)
        self.assertEqual(response["id"], followup["request_id"])

    def test_feature_lineage_is_scoped_to_the_machine_even_with_same_workflow_uuid(self):
        original_worker = self.worker
        identifier = self.effective_parent()
        second = self.pair(self.client, name="Separate older worker")
        self.hub.features(second["id"], ["workflow-v2"])
        self.worker = second
        body = self.body()
        body.pop("task_settings")
        body["request_id"] = identifier
        response = self.post_and_reply("workflows", body)
        self.assertEqual(response["id"], identifier)
        self.worker = original_worker
        self.downgrade_and_restart()
        with self.assertRaises(HTTPException) as error:
            self.request_direct(f"workflows/{identifier}/resume", {})
        self.assertEqual(error.exception.status_code, 409)

    def test_revocation_removes_durable_feature_lineage(self):
        self.effective_parent()
        with self.store.connect() as db:
            self.assertGreater(db.execute("SELECT COUNT(*) FROM worker_workflow_features WHERE worker=?", (self.worker["id"],)).fetchone()[0], 0)
        self.hub.revoke(self.worker["id"], self.principal.workspace)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_workflow_features WHERE worker=?", (self.worker["id"],)).fetchone()[0], 0)

    def test_workspace_purge_removes_durable_feature_lineage(self):
        self.effective_parent()
        self.hub.purge_workspace(self.principal.workspace)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_workflow_features WHERE worker=?", (self.worker["id"],)).fetchone()[0], 0)

    def test_expired_pending_queue_retains_the_unknown_override_requirement(self):
        body = self.body()
        with self.assertRaises(HTTPException) as timeout:
            self.request_direct("workflows", body)
        self.assertEqual(timeout.exception.status_code, 504)
        # No answer establishes whether the worker saved the task before losing
        # connectivity. Expiring the request must not permit unsafe old recovery.
        with self.store.connect() as db:
            db.execute("UPDATE worker_commands SET created=? WHERE worker=?", (time.time() - 90000, self.worker["id"]))
        self.hub.pending(self.worker["id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands WHERE worker=?", (self.worker["id"],)).fetchone()[0], 0)
        self.downgrade_and_restart()
        with self.assertRaises(HTTPException) as blocked:
            self.request_direct(f"workflows/{body['request_id']}/resume", {})
        self.assertEqual(blocked.exception.status_code, 409)

    def test_failed_override_id_collision_does_not_upgrade_an_existing_legacy_record(self):
        identifier = self.effective_parent(overrides=False)
        collision = self.body()
        collision["request_id"] = identifier
        response = self.post_and_reply("workflows", collision,
            {"detail": "This start request was already used with different inputs"}, reply_status=400)
        self.assertIn("different inputs", response["detail"])
        self.downgrade_and_restart()
        with self.assertRaises(HTTPException) as allowed_but_unanswered:
            self.request_direct(f"workflows/{identifier}/resume", {})
        self.assertEqual(allowed_but_unanswered.exception.status_code, 504,
                         "The old unchanged workflow remains executable; a failed override must not permanently stamp it")
        with self.store.connect() as db:
            queued = json.loads(db.execute("SELECT request FROM worker_commands WHERE worker=?", (self.worker["id"],)).fetchone()[0])
        self.assertEqual(queued["path"], f"/api/workflows/{identifier}/resume")

    def test_ambiguous_worker_error_retains_the_requirement_until_matching_recovery(self):
        body = self.body()
        response = self.post_and_reply("workflows", body,
            {"detail": "The workflow may have been saved before the response failed"}, reply_status=500)
        self.assertIn("may have been saved", response["detail"])
        self.downgrade_and_restart()
        with self.assertRaises(HTTPException) as blocked:
            self.request_direct(f"workflows/{body['request_id']}/resume", {})
        self.assertEqual(blocked.exception.status_code, 409)
        self.hub.features(self.worker["id"], FEATURES)
        recovered = self.post_and_reply("workflows", body, {"id": body["request_id"]})
        self.assertEqual(recovered["id"], body["request_id"])
        self.downgrade_and_restart()
        with self.assertRaises(HTTPException) as still_bound:
            self.request_direct(f"workflows/{body['request_id']}/resume", {})
        self.assertEqual(still_bound.exception.status_code, 409)


class TaskSettingsHttpTests(unittest.IsolatedAsyncioTestCase):
    check_project = fixtures.WorkflowTests.check_project

    async def asyncSetUp(self):
        await fixtures.WorkflowTests.asyncSetUp(self)
        self.app = create_app(self.store, self.registry, token="test-token", allowed_workspaces=(self.project,))
        self.http_service = self.app.state.workflows
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://localhost",
                                        headers={"Authorization": "Bearer test-token"})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.http_service.close()
        await self.http_service.engine.shutdown()
        await fixtures.WorkflowTests.asyncTearDown(self)

    def body(self):
        return {"request_id": str(uuid4()), "schema_version": "2.0", "workspace": str(self.project),
                "prompt": "Fix addition", "template_id": self.template["id"], "template_version": self.template["version"],
                "task_settings": {"schema_version": "1.0", "instructions": "Preserve only this task's interface",
                                  "checks": [{"name": "one-off", "argv": ["python", "-B", "check.py"], "timeout": 30}]}}

    async def test_http_records_immutable_effective_settings_without_changing_recipe_and_retries(self):
        body = self.body()
        original = self.http_service.template(self.template["id"], self.template["version"])
        with patch.object(self.http_service, "_launch", AsyncMock()):
            created = await self.client.post("/api/workflows", json=body)
            self.assertEqual(created.status_code, 200, created.text)
            first = created.json()
            read = await self.client.get("/api/workflows/" + first["id"])
            self.assertEqual(read.status_code, 200, read.text)
            self.assertEqual(read.json()["task_settings"]["instructions"], body["task_settings"]["instructions"])
            self.assertEqual(read.json()["spec"]["checks"][0]["name"], "one-off")
            self.assertEqual(self.http_service.template(self.template["id"], self.template["version"]), original)
            retry = await self.client.post("/api/workflows", json=body)
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json()["id"], first["id"])
            changed = json.loads(json.dumps(body))
            changed["task_settings"]["checks"][0]["argv"].append("different")
            conflict = await self.client.post("/api/workflows", json=changed)
            self.assertEqual(conflict.status_code, 400, conflict.text)
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(len(self.http_service.listing()), 1)

    async def test_unknown_settings_and_check_fields_fail_validation_without_work(self):
        for field in ("settings", "check"):
            with self.subTest(field=field):
                body = self.body()
                if field == "settings":
                    body["task_settings"]["provider_secret"] = "untrusted"
                else:
                    body["task_settings"]["checks"][0]["shell"] = True
                response = await self.client.post("/api/workflows", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.http_service.listing(), [])
        self.assertEqual(self.registry.calls, [])

    async def test_legacy_contract_refuses_overrides_with_clear_update_error(self):
        body = self.body()
        body["schema_version"] = "1.0"
        response = await self.client.post("/api/workflows", json=body)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertRegex(response.text, "[Vv]ersion|2.0|[Uu]pdate")
        self.assertEqual(self.http_service.listing(), [])
        self.assertEqual(self.registry.calls, [])
