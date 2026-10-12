"""Legacy run permissions at the team relay and first-dispatch boundary.

HostedFixture uses temporary state, an in-process ASGI client and mocked GitHub.
No worker process, provider, real repository or network service is invoked.
"""
import json
import time
from uuid import uuid4

from fastapi import HTTPException

from parallax.accounts import SESSION_COOKIE
from parallax.executors import encode
from test_accounts import HostedFixture, ORIGIN, user


class LegacyTeamAuthorizationTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.headers = {"Origin": ORIGIN}
        self.owner = self.signed_in(user(8201, "legacy-run-owner"))
        self.member = self.signed_in(user(8202, "legacy-run-member"))
        response = self.owner.post("/api/workspaces", json={"name": "Legacy boundary"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.team = response.json()["id"]
        self.switch(self.owner)
        invite = self.owner.post("/api/workspaces/invitations", json={"role": "developer"}, headers=self.headers)
        self.assertEqual(invite.status_code, 200, invite.text)
        joined = self.member.post("/api/invitations/accept", json={"token": invite.json()["token"]}, headers=self.headers)
        self.assertEqual(joined.status_code, 200, joined.text)
        self.switch(self.member)
        self.owner_principal = self.principal(self.owner)
        self.member_principal = self.principal(self.member)
        self.teams = self.app.state.accounts.teams
        self.hub = self.app.state.executors
        self.worker = self.pair(self.owner, workspaces=("/approved",))
        bound = self.owner.post("/api/workspaces/projects", json={"worker": self.worker["id"], "path": "/approved"}, headers=self.headers)
        self.assertEqual(bound.status_code, 200, bound.text)
        self.hub.features(self.worker["id"], ["workflow-v2"])
        self.run = str(uuid4())

    def switch(self, client):
        response = client.post(f"/api/workspaces/{self.team}/switch", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def principal(self, client):
        return self.app.state.accounts.principal(client.cookies.get(SESSION_COOKIE))

    def context_for_role(self, role):
        if role == "owner":
            principal = self.owner_principal
        else:
            self.teams.change_role(self.owner_principal, self.member_principal.account["id"], role)
            principal = self.member_principal
        return self.teams.context(principal, self.worker["id"])

    def assert_denied(self, context, path):
        with self.assertRaises(HTTPException) as failure:
            self.teams.reauthorize(context, self.worker["id"], "POST", path)
        self.assertEqual(failure.exception.status_code, 403)

    def queue_steering(self, context):
        identifier = str(uuid4())
        command = {"method": "POST", "path": f"/api/runs/{self.run}/steer", "query": "",
                   "body": {"message": "Preserve the original acceptance criteria"},
                   "authority": context, "expires_at": time.time() + 60}
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)",
                       (identifier, self.worker["id"], encode(command), time.time()))
        return identifier

    def test_legacy_start_control_and_recovery_are_denied_for_every_team_role(self):
        # These personal-run endpoints are transport-allowed, but team members
        # must use the versioned workflow lifecycle, including its controls.
        paths = ["/api/runs"] + [f"/api/runs/{self.run}/{operation}" for operation in
                                  ("pause", "stop", "cancel", "resume", "recover", "feedback")]
        for role in ("owner", "developer", "reviewer"):
            context = self.context_for_role(role)
            for path in paths:
                with self.subTest(role=role, path=path):
                    self.assert_denied(context, path)

    def test_legacy_steering_is_allowed_only_for_owner_and_developer(self):
        path = f"/api/runs/{self.run}/steer"
        for role in ("owner", "developer"):
            with self.subTest(role=role):
                authorized = self.teams.reauthorize(self.context_for_role(role), self.worker["id"], "POST", path)
                self.assertEqual(authorized["role"], role)
                self.assertEqual(authorized["projects"], ["/approved"])
        self.assert_denied(self.context_for_role("reviewer"), path)

    def test_reviewer_cannot_use_a_forged_owner_context_to_steer(self):
        context = self.context_for_role("reviewer")
        self.assert_denied({**context, "role": "owner"}, f"/api/runs/{self.run}/steer")

    def test_queued_developer_steering_is_dispatched_with_current_authority(self):
        context = self.context_for_role("developer")
        identifier = self.queue_steering(context)
        commands = self.hub.pending(self.worker["id"])
        self.assertEqual([command["id"] for command in commands], [identifier])
        self.assertEqual(commands[0]["authority"]["actor"], context["actor"])
        self.assertEqual(commands[0]["authority"]["role"], "developer")
        self.assertTrue(self.hub.dispatched(self.worker["id"], identifier))

    def test_queued_steering_is_rejected_after_developer_becomes_reviewer(self):
        context = self.context_for_role("developer")
        identifier = self.queue_steering(context)
        self.teams.change_role(self.owner_principal, self.member_principal.account["id"], "reviewer")
        self.assertEqual(self.hub.pending(self.worker["id"]), [])
        self.assertFalse(self.hub.dispatched(self.worker["id"], identifier))
        with self.store.connect() as db:
            request, response = db.execute("SELECT request,response FROM worker_commands WHERE id=?", (identifier,)).fetchone()
            self.assertEqual(json.loads(request)["authority"]["role"], "developer")
            denied = json.loads(response)
            self.assertEqual(denied["status"], 403)
            self.assertEqual(denied["body"]["detail"], "Reviewers may inspect, comment and approve")
            self.assertIsNone(db.execute("SELECT 1 FROM worker_operation_receipts WHERE id=?", (identifier,)).fetchone())
