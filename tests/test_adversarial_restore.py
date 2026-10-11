"""Cold restore of disposable worker and relay data; no live credentials or network."""
import hashlib
from pathlib import Path
import shutil
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from parallax.engine import Engine
from parallax.server import create_app
from parallax.store import Store
from parallax.workflows import ApprovalRequest, Workflows
import test_workflows as workflows
from test_accounts import HostedFixture, KEY, ORIGIN, user


def manifest(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def restore_cold(directory):
    """Replace an offline, temporary state tree from a separate full backup.

    Restore to the original location: saved candidate metadata intentionally
    contains absolute paths. This is not a migration or a live SQLite copy.
    """
    backup = directory.parent / (directory.name + "-cold-backup")
    before = manifest(directory)
    shutil.copytree(directory, backup)
    assert manifest(backup) == before
    shutil.rmtree(directory)
    shutil.copytree(backup, directory)
    assert manifest(directory) == before


class WorkerColdRestoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflows.WorkflowTests.asyncSetUp
    asyncTearDown = workflows.WorkflowTests.asyncTearDown
    check_project = workflows.WorkflowTests.check_project
    request = workflows.WorkflowTests.request
    settle = workflows.WorkflowTests.settle

    async def test_full_worker_backup_recovers_candidate_approval_and_consumed_budget(self):
        value = await self.service.start(self.request().model_copy(update={"schema_version": "2.0"}))
        value = await self.settle(value["id"])
        self.assertEqual(value["status"], "awaiting_approval", value.get("error"))
        candidate = value["candidate"]["digest"]
        operation = ApprovalRequest(request_id=uuid4(), candidate_digest=candidate)
        with patch.object(self.service, "_launch", AsyncMock(side_effect=RuntimeError("offline before resume"))):
            with self.assertRaisesRegex(RuntimeError, "offline before resume"):
                await self.service.approve(value["id"], operation)
        recorded = self.store.get(value["run_id"])
        self.assertGreater(recorded["artifacts"]["runtime_seconds"], 0)
        budget = {key: recorded["artifacts"].get(key) for key in ("runtime_seconds", "coordinator_turns")}
        await self.service.close()
        await self.engine.shutdown()

        restore_cold(self.store.home)
        self.store = Store(self.root / "state")
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.registry = workflows.FakeRegistry()
        self.engine = Engine(self.store, self.registry)
        self.engine.recover()
        self.service = Workflows(self.engine, self.check_project)
        await self.service.recover()
        restored_run = self.store.get(value["run_id"])
        self.assertEqual({key: restored_run["artifacts"].get(key) for key in budget}, budget)
        self.assertEqual(self.service.get(value["id"])["candidate"]["digest"], candidate)
        await self.service.approve(value["id"], operation)
        approved = await self.settle(value["id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approval"]["id"], str(operation.request_id))
        self.assertEqual(approved["delivery"]["local"], "pending")
        self.assertEqual(self.registry.calls, [])
        self.assertIn("return a-b", (self.project / "maths.py").read_text())
        self.assertEqual(workflows.git(self.project, "diff", "--cached"), self.staging)


class RelayColdRestoreTests(HostedFixture, unittest.IsolatedAsyncioTestCase):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    async def test_full_relay_backup_preserves_isolation_grants_and_revocations(self):
        owner = self.signed_in(user(7101, "restore-owner"))
        reviewer = self.signed_in(user(7102, "restore-reviewer"))
        outsider = self.signed_in(user(7103, "restore-outsider"))
        headers = {"Origin": ORIGIN}
        old_worker = self.pair(owner)
        team_response = owner.post("/api/workspaces", json={"name": "Cold restore team"}, headers=headers)
        self.assertEqual(team_response.status_code, 200, team_response.text)
        team = team_response.json()["id"]
        self.assertEqual(owner.post("/api/workspaces/" + team + "/switch", headers=headers).status_code, 200)
        invitation = owner.post("/api/workspaces/invitations", json={"role": "reviewer"}, headers=headers).json()
        self.assertEqual(reviewer.post("/api/invitations/accept", json={"token": invitation["token"]}, headers=headers).status_code, 200)
        self.assertEqual(reviewer.post("/api/workspaces/" + team + "/switch", headers=headers).status_code, 200)
        worker = self.pair(owner, workspaces=("/approved-restore-project",))
        self.assertEqual(owner.post("/api/workspaces/projects", json={"worker": worker["id"], "path": "/approved-restore-project"}, headers=headers).status_code, 200)
        # Capture three independent sessions, then revoke the old personal
        # worker and remove the reviewer before the cold snapshot.
        cookies = {name: client.cookies.get("parallax_session") for name, client in
                   (("owner", owner), ("reviewer", reviewer), ("outsider", outsider))}
        actor = reviewer.get("/api/session").json()["account"]["id"]
        self.assertEqual(owner.delete("/api/workspaces/members/" + actor, headers=headers).status_code, 200)
        personal = next(value for value in owner.get("/api/workspaces").json() if value["kind"] == "personal")
        self.assertEqual(owner.post("/api/workspaces/" + personal["id"] + "/switch", headers=headers).status_code, 200)
        self.assertEqual(owner.delete("/api/executors/" + old_worker["id"], headers=headers).status_code, 200)
        self.assertEqual(owner.post("/api/workspaces/" + team + "/switch", headers=headers).status_code, 200)
        cookies["owner"] = owner.cookies.get("parallax_session")
        for client in (owner, reviewer, outsider): client.close()
        await self.app.state.workflows.close()
        await self.app.state.engine.shutdown()
        restore_cold(self.store.home)
        self.store = Store(self.root / "state")
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.app = create_app(self.store, token=KEY, deployment=self.deployment,
                              http_transport=httpx.MockTransport(self.github))
        fresh = {name: self.browser() for name in cookies}
        for name, client in fresh.items(): client.cookies.set("parallax_session", cookies[name])
        self.assertEqual(fresh["owner"].get("/api/session").json()["workspace"]["id"], team)
        self.assertEqual(fresh["reviewer"].get("/api/session").status_code, 401)
        self.assertEqual(fresh["outsider"].get("/api/executors/" + worker["id"] + "/proxy/runs").status_code, 404)
        grants = fresh["owner"].get("/api/workspaces/projects").json()
        self.assertEqual([(grant["worker"], grant["path"]) for grant in grants], [(worker["id"], "/approved-restore-project")])
        self.assertEqual(self.browser().get("/api/worker/next", headers={"Authorization": "Bearer " + old_worker["token"]}).status_code, 401)
        self.assertEqual(self.browser().get("/api/worker/next", headers={"Authorization": "Bearer " + worker["token"]}).status_code, 200)
        await self.app.state.workflows.close()
        await self.app.state.engine.shutdown()
