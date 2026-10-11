"""Adversarial hosted authorization tests; isolated temporary accounts and state."""
from uuid import uuid4

from test_accounts import HostedFixture, user, ORIGIN


class RevocationBoundaryTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.headers = {"Origin": ORIGIN}
        self.owner = self.signed_in(user(8101, "revocation-owner"))
        self.member = self.signed_in(user(8102, "revocation-member"))
        self.team = self.owner.post("/api/workspaces", json={"name": "Revocation team"}, headers=self.headers).json()["id"]
        self.switch(self.owner)

    def switch(self, client):
        response = client.post(f"/api/workspaces/{self.team}/switch", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def invite(self, role="developer"):
        response = self.owner.post("/api/workspaces/invitations", json={"role": role}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def accept(self, client, token):
        return client.post("/api/invitations/accept", json={"token": token}, headers=self.headers)

    def test_consumed_invitation_cannot_restore_a_removed_member(self):
        token = self.invite()
        self.assertEqual(self.accept(self.member, token).status_code, 200)
        # An immediate retry remains idempotent while the membership is active.
        self.assertEqual(self.accept(self.member, token).status_code, 200)
        self.switch(self.member)
        actor = self.member.get("/api/session").json()["account"]["id"]
        removed = self.owner.delete(f"/api/workspaces/members/{actor}", headers=self.headers)
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.member.get("/api/session").status_code, 401)
        # Reauthentication is legitimate, but the old invitation is consumed.
        self.member = self.signed_in(user(8102, "revocation-member"))
        replay = self.accept(self.member, token)
        self.assertEqual(replay.status_code, 410, replay.text)
        self.assertEqual(self.member.post(f"/api/workspaces/{self.team}/switch", headers=self.headers).status_code, 400)
        # A fresh owner-issued invitation can deliberately restore access.
        self.assertEqual(self.accept(self.member, self.invite()).status_code, 200)

    def test_invitation_from_disabled_owner_cannot_admit_new_members(self):
        token = self.invite()
        actor = self.owner.get("/api/session").json()["account"]["id"]
        with self.store.connect() as db:
            db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (actor,))
        response = self.accept(self.member, token)
        self.assertEqual(response.status_code, 410, response.text)

    def test_pairing_code_is_invalidated_when_issuer_loses_owner_role(self):
        token = self.invite()
        self.assertEqual(self.accept(self.member, token).status_code, 200)
        self.switch(self.member)
        actor = self.member.get("/api/session").json()["account"]["id"]
        promoted = self.owner.patch(f"/api/workspaces/members/{actor}", json={"role": "owner"}, headers=self.headers)
        self.assertEqual(promoted.status_code, 200, promoted.text)
        code = self.member.post("/api/executors/pair", headers=self.headers).json()["code"]
        demoted = self.owner.patch(f"/api/workspaces/members/{actor}", json={"role": "reviewer"}, headers=self.headers)
        self.assertEqual(demoted.status_code, 200, demoted.text)
        response = self.browser().post("/api/worker/connect", json={"code": code, "name": "Unauthorized pending machine", "platform": "darwin", "workspaces": ["/project"]})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.owner.get("/api/executors").json(), [])

    def test_pairing_code_is_invalidated_when_issuer_session_ends(self):
        code = self.owner.post("/api/executors/pair", headers=self.headers).json()["code"]
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        self.app.state.accounts.end_session(principal.session)
        response = self.browser().post("/api/worker/connect", json={"code": code, "name": "Expired authorization", "platform": "darwin", "workspaces": ["/project"]})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.app.state.executors.workers(self.team), [])

    def test_shared_recipe_update_cannot_create_a_chosen_or_foreign_id(self):
        worker = self.pair(self.owner, workspaces=("/project",))
        self.app.state.executors.features(worker["id"], ["workflow-v2"])
        self.assertEqual(self.owner.post("/api/workspaces/projects", json={"worker": worker["id"], "path": "/project"}, headers=self.headers).status_code, 200)
        route = f"/api/executors/{worker['id']}/proxy/workflow-templates"
        identifier = str(uuid4())
        # An attacker can know a UUID from a second workspace they belong to.
        with self.store.connect() as db:
            db.execute("INSERT INTO team_recipes VALUES(?,?,1,?,?)", ("another-workspace", identifier, '{"name":"Private recipe"}', "another-actor"))
        response = self.owner.put(route + "/" + identifier, json={"name": "Chosen collision"}, headers=self.headers)
        self.assertEqual(response.status_code, 404, response.text)
        created = self.owner.post(route, json={"name": "Authorized recipe"}, headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)
        updated = self.owner.put(route + "/" + created.json()["id"], json={"name": "Second version"}, headers=self.headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)

    def test_reviewer_map_respects_project_grants_and_disabled_accounts(self):
        self.assertEqual(self.accept(self.member, self.invite("reviewer")).status_code, 200)
        self.switch(self.member)
        actor = self.member.get("/api/session").json()["account"]["id"]
        owner = self.owner.get("/api/session").json()["account"]["id"]
        worker = self.pair(self.owner, workspaces=("/shared", "/restricted"))
        for path, members in (("/shared", []), ("/restricted", [owner])):
            response = self.owner.post("/api/workspaces/projects", json={"worker": worker["id"], "path": path, "members": members}, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        authority = self.app.state.accounts.teams.context(principal, worker["id"])
        self.assertIn(actor, authority["reviewers_by_project"]["/shared"])
        self.assertNotIn(actor, authority["reviewers_by_project"]["/restricted"])
        self.assertIn(owner, authority["reviewers_by_project"]["/restricted"])
        member = self.app.state.accounts.principal(self.member.cookies.get("parallax_session"))
        self.assertNotIn("/restricted", self.app.state.accounts.teams.context(member, worker["id"])["reviewers_by_project"])
        with self.store.connect() as db:
            db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (actor,))
        refreshed = self.app.state.accounts.teams.reauthorize(authority, worker["id"], "GET", "/api/workflows")
        self.assertNotIn(actor, refreshed["reviewers_by_project"]["/shared"])
