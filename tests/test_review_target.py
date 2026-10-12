"""Read-only review link previews resolve current membership, machine and project grants."""
import json
from uuid import uuid4
from test_accounts import HostedFixture, user, ORIGIN

UNAVAILABLE = {"detail": "Review link is unavailable"}


class ReviewTargetTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.headers = {"Origin": ORIGIN}
        self.owner = self.signed_in(user(801, "owner-person"))
        self.reviewer = self.signed_in(user(802, "reviewer-person"))
        self.stranger = self.signed_in(user(803, "stranger-person"))
        self.team = self.owner.post("/api/workspaces", json={"name": "Review team"}, headers=self.headers).json()["id"]
        self.switch(self.owner, self.team)
        invite = self.owner.post("/api/workspaces/invitations", json={"role": "reviewer"}, headers=self.headers).json()
        accepted = self.reviewer.post("/api/invitations/accept", json={"token": invite["token"]}, headers=self.headers)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.worker = self.pair(self.owner, workspaces=("/approved", "/other"))["id"]
        self.hub = self.app.state.executors
        self.hub.features(self.worker, ["workflow-v2"])
        bound = self.owner.post("/api/workspaces/projects", json={"worker": self.worker, "path": "/approved"}, headers=self.headers)
        self.assertEqual(bound.status_code, 200, bound.text)
        self.task = str(uuid4())
        self.cache("/api/workflows/" + self.task, {"id": self.task, "title": "Fix addition", "status": "awaiting_approval", "workspace": "/approved"})

    def switch(self, client, workspace):
        response = client.post("/api/workspaces/" + workspace + "/switch", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def cache(self, path, body, status=200):
        with self.store.connect() as db:
            self.hub._cache(db, self.worker, path, {"status": status, "body": body, "content_type": "application/json"})

    def preview(self, client, workspace=None, worker=None, task=None):
        return client.get(f"/api/workspaces/{workspace or self.team}/review-target/{worker or self.worker}/{task or self.task}")

    def assertUnavailable(self, response):
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json(), UNAVAILABLE)

    def test_member_in_another_workspace_gets_a_scoped_preview_without_switching(self):
        before = self.reviewer.get("/api/session").json()["workspace"]["id"]
        response = self.preview(self.reviewer)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["capability"], "review-target-v1")
        self.assertEqual(body["workspace"], {"id": self.team, "name": "Review team", "kind": "team", "role": "reviewer"})
        self.assertEqual(body["worker"]["id"], self.worker)
        self.assertEqual(body["workflow"], {"id": self.task, "title": "Fix addition", "status": "awaiting_approval"})
        self.assertEqual(body["source"], "managed_cache")
        self.assertNotIn("/approved", json.dumps(body))
        self.assertEqual(self.reviewer.get("/api/session").json()["workspace"]["id"], before)

    def test_non_members_and_malformed_links_get_the_same_refusal(self):
        self.assertUnavailable(self.preview(self.stranger))
        self.assertUnavailable(self.preview(self.reviewer, workspace="not-a-uuid"))
        self.assertUnavailable(self.preview(self.reviewer, task="runs"))
        self.assertUnavailable(self.preview(self.reviewer, workspace=str(uuid4())))

    def test_project_grants_are_enforced_for_members_but_owners_keep_access(self):
        bindings = self.owner.get("/api/workspaces/projects").json()
        owner_id = self.owner.get("/api/session").json()["account"]["id"]
        changed = self.owner.patch("/api/workspaces/projects/" + bindings[0]["id"],
                                   json={"members": [owner_id], "request_id": str(uuid4())}, headers=self.headers)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertUnavailable(self.preview(self.reviewer))
        self.assertEqual(self.preview(self.owner).status_code, 200)

    def test_tasks_outside_bound_projects_or_machine_roots_are_refused(self):
        other = str(uuid4())
        self.cache("/api/workflows/" + other, {"id": other, "title": "Unbound", "status": "awaiting_approval", "workspace": "/other"})
        self.assertUnavailable(self.preview(self.reviewer, task=other))
        rogue = str(uuid4())
        self.cache("/api/workflows/" + rogue, {"id": rogue, "title": "Outside roots", "status": "awaiting_approval", "workspace": "/elsewhere"})
        self.assertUnavailable(self.preview(self.reviewer, task=rogue))

    def test_cached_record_must_match_the_requested_task_and_list_cache_is_used(self):
        mismatched = str(uuid4())
        self.cache("/api/workflows/" + mismatched, {"id": str(uuid4()), "title": "Other", "status": "approved", "workspace": "/approved"})
        self.assertUnavailable(self.preview(self.reviewer, task=mismatched))
        self.assertUnavailable(self.preview(self.reviewer, task=str(uuid4())))
        listed = str(uuid4())
        self.cache("/api/workflows", [{"id": listed, "title": "From the list", "status": "approved", "workspace": "/approved"}])
        response = self.preview(self.reviewer, task=listed)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["workflow"]["title"], "From the list")

    def test_foreign_revoked_and_outdated_machines_are_refused(self):
        self.switch(self.owner, self.owner.get("/api/workspaces").json()[0]["id"])
        personal_worker = self.pair(self.owner, name="Personal", workspaces=("/approved",))["id"]
        self.assertUnavailable(self.preview(self.reviewer, worker=personal_worker))
        self.hub.features(self.worker, [])
        self.assertUnavailable(self.preview(self.reviewer))
        self.hub.features(self.worker, ["workflow-v2"])
        self.assertEqual(self.preview(self.reviewer).status_code, 200)
        self.switch(self.owner, self.team)
        revoked = self.owner.delete("/api/executors/" + self.worker, headers=self.headers)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertUnavailable(self.preview(self.reviewer))

    def test_removed_membership_loses_the_preview(self):
        self.assertEqual(self.preview(self.reviewer).status_code, 200)
        reviewer_id = self.reviewer.get("/api/session").json()["account"]["id"]
        self.assertEqual(self.owner.delete("/api/workspaces/members/" + reviewer_id, headers=self.headers).status_code, 200)
        self.assertUnavailable(self.preview(self.reviewer))

    def test_preview_writes_nothing(self):
        tables = ("worker_commands", "sessions", "memberships", "project_bindings", "worker_cache")
        with self.store.connect() as db:
            before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        for client in (self.reviewer, self.stranger, self.owner):
            self.preview(client)
        with self.store.connect() as db:
            after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        self.assertEqual(before, after)
