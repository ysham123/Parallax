"""Native relay/worker failure boundaries; providers and HTTPS are simulated."""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from parallax.executors import ExecutorHub, MAX_MESSAGE, PERSONAL_LIMITS, encode
from parallax.models import RunResult, RunSpec
from parallax.store import Store, now
from parallax.teams import ProjectMembersInput
from parallax.worker import WorkerRuntime, WORKER_FEATURES, evidence_batches, run_worker, serialized
from test_accounts import HostedFixture, ORIGIN, SESSION_COOKIE, user
from test_engine import FakeRegistry


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.spec = RunSpec(workspace=str(self.project), prompt="Synthetic transport", mode="review")

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_record(self, size=0):
        return RunResult(run_id=str(uuid4()), status="completed", spec=self.spec, diff="x"*size).model_dump()

    def event(self, sequence, message="small"):
        return {"schema_version": "1.1", "run_id": str(uuid4()), "sequence": sequence,
                "timestamp": now(), "kind": "synthetic", "data": {"message": message}}

    async def test_exact_json_byte_batches_preserve_three_large_runs_and_escaped_events(self):
        runs = [self.run_record(3*1024**2) for _ in range(3)]
        events = [self.event(n, '"\\\n\u00e9\U0001f642'*1000) for n in range(1, 8)]
        before = serialized({"runs": runs, "events": events})
        batches, problems = evidence_batches(runs, events)
        self.assertGreater(len(batches), 1)
        self.assertEqual(problems, [])
        self.assertTrue(all(len(serialized(batch).encode()) <= MAX_MESSAGE for batch in batches))
        self.assertEqual([r for b in batches for r in b["runs"]], runs)
        self.assertEqual([e for b in batches for e in b["events"]], events)
        self.assertEqual(before, serialized({"runs": runs, "events": events}))

    async def test_single_oversize_run_remains_exact_and_diagnosis_is_durable_without_spam(self):
        large, small = self.run_record(MAX_MESSAGE), self.run_record()
        self.store.save(large)
        self.store.save(small)
        runtime = WorkerRuntime(self.store, [self.project], registry=FakeRegistry())
        try:
            runs, events = runtime.snapshot({}, 0)
            batches, problems = evidence_batches(runs, events)
            self.assertEqual([p["run_id"] for p in problems], [large["run_id"]])
            self.assertEqual([r["run_id"] for b in batches for r in b["runs"]], [small["run_id"]])
            runtime.record_problems(problems)
            runtime.record_problems(problems)
            self.assertEqual(runtime.transport_status()["status"], "local_evidence_only")
            self.assertEqual(len(self.store.events(large["run_id"])), 1)
            self.assertEqual(self.store.get(large["run_id"])["diff"], large["diff"])
        finally:
            await runtime.client.aclose()
        reopened = WorkerRuntime(Store(self.store.home), [self.project], registry=FakeRegistry())
        try:
            self.assertEqual(reopened.transport_status()["problem_count"], 1)
        finally:
            await reopened.client.aclose()

    async def test_large_event_keeps_replay_gap_and_does_not_forward_later_sequence(self):
        events = [self.event(1), self.event(2, "x"*MAX_MESSAGE), self.event(3)]
        batches, problems = evidence_batches([], events)
        self.assertEqual([e["sequence"] for b in batches for e in b["events"]], [1])
        self.assertEqual(problems[0]["key"], "2")
        self.assertEqual(len(events[1]["data"]["message"]), MAX_MESSAGE)

    async def test_large_run_http_reply_is_actionable_and_local_record_is_unchanged(self):
        value = self.run_record(MAX_MESSAGE)
        self.store.save(value)
        runtime = WorkerRuntime(self.store, [self.project], registry=FakeRegistry())
        try:
            reply = await runtime.dispatch({"id": str(uuid4()), "method": "GET", "path": "/api/runs/"+value["run_id"],
                                            "query": "", "body": None, "expires_at": time.time()+60})
            self.assertEqual(reply["status"], 413)
            self.assertEqual(reply["body"]["code"], "evidence_exceeds_transport_limit")
            self.assertTrue(reply["body"]["full_evidence_available_locally"])
            self.assertEqual(self.store.get(value["run_id"])["diff"], value["diff"])
            runtime.record_problems([])
            self.assertEqual(runtime.transport_status()["status"], "local_evidence_only")
            restarted = WorkerRuntime(Store(self.store.home), [self.project], registry=FakeRegistry())
            try:
                self.assertEqual(restarted.transport_status()["problem_count"], 1)
            finally:
                await restarted.client.aclose()
        finally:
            await runtime.client.aclose()

    async def test_team_approval_of_untransferable_candidate_fails_before_decision(self):
        value = self.run_record(MAX_MESSAGE)
        self.store.save(value)
        runtime = WorkerRuntime(self.store, [self.project], registry=FakeRegistry())
        identifier = str(uuid4())
        workflow = {"id": identifier, "spec": {"workspace": str(self.project)}, "run_id": value["run_id"],
                    "authority": {"workspace": "test-team", "team": True}, "requester": "other-human",
                    "template": {"id": "test", "version": 1, "name": "test", "instructions": "Inspect"}, "prompt": "Inspect"}
        workflow["spec"] = self.spec.model_dump()
        with self.store.connect() as db:
            db.execute("INSERT INTO workflows VALUES(?,?,?)", (identifier, json.dumps(workflow), now()))
        context = {"version": "2.0", "workspace": "test-team", "team": True, "actor": "reviewer",
                   "role": "reviewer", "projects": [str(self.project)]}
        try:
            with patch.object(runtime.app.state.workflows, "approve", AsyncMock()) as approve:
                response = await runtime.client.post("/api/workflows/"+identifier+"/approve",
                    headers={"X-Parallax-Authority": encode(context)}, json={"request_id": str(uuid4()), "candidate_digest": "a"*64})
                self.assertEqual(response.status_code, 413, response.text)
                approve.assert_not_awaited()
                response = await runtime.client.post("/api/workflows/"+identifier+"/approve",
                    headers={"X-Parallax-Authority": encode({**context, "workspace": "foreign-team"})},
                    json={"request_id": str(uuid4()), "candidate_digest": "a"*64})
                self.assertEqual(response.status_code, 404)
                approve.assert_not_awaited()
        finally:
            await runtime.client.aclose()

    async def worker_loop(self, handle, snapshot):
        state = self.root / "connection"
        state.mkdir()
        (state / "worker-connection.json").write_text(encode({"id": str(uuid4()), "token": "synthetic-token",
            "url": "https://relay.example.invalid", "workspaces": [str(self.project)]}))
        original_client, original_sleep = httpx.AsyncClient, asyncio.sleep
        def client(**kwargs):
            if kwargs.get("base_url") == "https://relay.example.invalid":
                kwargs["transport"] = httpx.MockTransport(handle)
            return original_client(**kwargs)
        async def short_sleep(seconds):
            await original_sleep(.002)
        with patch("parallax.worker.httpx.AsyncClient", side_effect=client), \
             patch("parallax.worker.asyncio.sleep", side_effect=short_sleep), \
             patch.object(WorkerRuntime, "snapshot", snapshot):
            with self.assertRaises(PermissionError):
                await asyncio.wait_for(run_worker("https://relay.example.invalid", state, [self.project], name="Synthetic"), 5)

    async def test_400_413_507_evidence_refusals_do_not_block_control_or_acknowledge(self):
        value = self.run_record(100)
        event = self.event(1)
        evidence, polls, cursors, snapshots = [], [], [], []
        def snapshot(runtime, hashes, cursor):
            cursors.append(cursor)
            snapshots.append(dict(hashes))
            return [value], [event]
        def handle(request):
            if request.url.path.endswith("heartbeat"):
                return httpx.Response(200, json={"ok": True})
            if request.url.path.endswith("next"):
                polls.append(request.url.path)
                return httpx.Response(401 if len(evidence) >= 3 and len(polls) >= 3 else 200, json=[])
            evidence.append(json.loads(request.content))
            return httpx.Response([400, 413, 507][min(len(evidence)-1, 2)], json={"detail": "synthetic refusal"})
        await self.worker_loop(handle, snapshot)
        self.assertGreaterEqual(len(polls), 3)
        self.assertEqual(set(cursors), {0})
        self.assertTrue(all(not saved for saved in snapshots))
        self.assertTrue(all(batch["events"][0]["sequence"] == 1 for batch in evidence))

    async def test_hanging_evidence_upload_does_not_block_heartbeat_or_control(self):
        polls, uploads = [], []
        async def handle(request):
            if request.url.path.endswith("sync"):
                uploads.append(request.url.path)
                await asyncio.Event().wait()
            if request.url.path.endswith("heartbeat"):
                return httpx.Response(200, json={"ok": True})
            polls.append(request.url.path)
            return httpx.Response(401 if len(polls) >= 3 and uploads else 200, json=[])
        await self.worker_loop(handle, lambda runtime, hashes, cursor: ([self.run_record(100)], []))
        self.assertTrue(uploads)
        self.assertGreaterEqual(len(polls), 3)

    async def test_worker_reserved_control_slot_runs_with_four_waiting_dispatches(self):
        commands = [{"id": str(uuid4()), "method": "GET", "path": "/api/context", "query": "", "body": None,
                     "expires_at": time.time()+60} for _ in range(4)]
        cancel = {"id": str(uuid4()), "method": "POST", "path": "/api/runs/"+str(uuid4())+"/cancel", "body": None,
                  "query": "", "expires_at": time.time()+60}
        started, cancelled = [], asyncio.Event()
        async def dispatch(runtime, command):
            started.append(command["id"])
            if command["id"] == cancel["id"]:
                cancelled.set()
                return {"status": 200, "body": {}, "content_type": "application/json"}
            await asyncio.Event().wait()
        def handle(request):
            if request.url.path.endswith("next"):
                return httpx.Response(401 if cancelled.is_set() else 200, json=commands+[cancel])
            return httpx.Response(200, json={"ok": True})
        with patch.object(WorkerRuntime, "dispatch", dispatch):
            await self.worker_loop(handle, lambda runtime, hashes, cursor: ([], []))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(started), 5)

    async def test_older_relay_heartbeat_falls_back_to_empty_sync_and_keeps_polling(self):
        routes, fallback = [], []
        def handle(request):
            routes.append(request.url.path)
            if request.url.path.endswith("heartbeat"):
                return httpx.Response(404)
            if request.url.path.endswith("sync"):
                fallback.append(json.loads(request.content))
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, json={"detail": "end test"})
        await self.worker_loop(handle, lambda runtime, hashes, cursor: ([], []))
        self.assertEqual(routes[:3], ["/api/worker/heartbeat", "/api/worker/sync", "/api/worker/next"])
        self.assertEqual(fallback[0]["runs"], [])
        self.assertEqual(fallback[0]["events"], [])


class RelayTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state")
        self.hub = ExecutorHub(self.store)
        self.worker = self.hub.connect(self.hub.pair("personal")["code"], "Synthetic", {"workspaces": ["/approved"], "features": WORKER_FEATURES})

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    def seed_read(self, stamp=None):
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (str(uuid4()), self.worker["id"],
                encode({"method": "GET", "path": "/api/context", "query": "", "body": None, "expires_at": time.time()+60}), stamp or time.time()-1))

    async def test_reserved_cancel_admission_survives_full_normal_queue_and_rate_bucket(self):
        for _ in range(PERSONAL_LIMITS.pending_commands):
            self.seed_read()
        with self.store.connect() as db:
            db.executemany("INSERT INTO rate_events VALUES(?,?)", [("relay:personal", time.time()) for _ in range(PERSONAL_LIMITS.relayed_per_window)])
        path = "/api/runs/"+str(uuid4())+"/cancel"
        request = asyncio.create_task(self.hub.request(self.worker["id"], "POST", path, "", None, workspace="personal", timeout=2))
        for _ in range(100):
            await asyncio.sleep(.002)
            commands = self.hub.pending(self.worker["id"])
            if commands and commands[0]["path"] == path:
                break
        self.assertEqual(commands[0]["path"], path)
        self.hub.complete(self.worker["id"], commands[0]["id"], {"status": 200, "body": {"ok": True}, "content_type": "application/json"})
        self.assertEqual((await request)["status"], 200)

    async def test_legacy_queued_cancel_is_prioritized_before_eight_unanswered_reads(self):
        for _ in range(8):
            self.seed_read()
        path = "/api/runs/"+str(uuid4())+"/cancel"
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (str(uuid4()), self.worker["id"],
                encode({"method": "POST", "path": path, "query": "", "body": None, "expires_at": time.time()+60}), time.time()))
        self.assertEqual(self.hub.pending(self.worker["id"])[0]["path"], path)

    async def test_contended_admission_is_off_loop_expires_and_does_not_queue_late(self):
        locked, release = threading.Event(), threading.Event()
        def hold():
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                locked.set()
                release.wait(2)
        holder = threading.Thread(target=hold)
        holder.start()
        await asyncio.to_thread(locked.wait)
        started = time.monotonic()
        request = asyncio.create_task(self.hub.request(self.worker["id"], "GET", "/api/context", "", None, workspace="personal", timeout=.04))
        ticks = 0
        try:
            for _ in range(5):
                await asyncio.sleep(.01)
                ticks += 1
            with self.assertRaises(HTTPException) as error:
                await request
            self.assertEqual(error.exception.status_code, 504)
            self.assertLess(time.monotonic()-started, .2)
        finally:
            release.set()
            await asyncio.to_thread(holder.join)
            await asyncio.sleep(.04)
        self.assertEqual(ticks, 5)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_commands").fetchone()[0], 0)

    async def test_personal_revocation_remains_a_purge(self):
        workflow = str(uuid4())
        cached = {"id": workflow, "title": "Saved task", "workspace": "/approved", "status": "approved",
                  "requester": "recorded-human", "approval": {"actor": "different-human", "candidate_digest": "a"*64},
                  "comments": [{"message": "PRIVATE_SOURCE_SENTINEL"}], "prompt": "PRIVATE_SOURCE_SENTINEL"}
        with self.store.connect() as db:
            self.hub._cache(db, self.worker["id"], "/api/workflows/"+workflow,
                            {"status": 200, "body": cached, "content_type": "application/json"})
        path = "/api/workflows/"+workflow+"/apply"
        request = asyncio.create_task(self.hub.request(self.worker["id"], "POST", path, "", {"request_id": str(uuid4()), "candidate_digest": "a"*64},
            workspace="personal", timeout=2, authority={"team": False, "actor": "delivery-human"}))
        for _ in range(100):
            await asyncio.sleep(.002)
            commands = self.hub.pending(self.worker["id"])
            if commands:
                break
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        self.hub.revoke(self.worker["id"], "personal")
        with self.assertRaises(HTTPException):
            self.hub.authenticate(self.worker["token"])
        with self.assertRaises(HTTPException):
            self.hub.worker(self.worker["id"], "personal")
        items = self.hub.archives("personal")["items"]
        self.assertEqual(items, [])
        self.assertNotIn("PRIVATE_SOURCE_SENTINEL", serialized(items))
        self.assertEqual(self.hub.archives("foreign")["items"], [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_cache").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_operation_receipts").fetchone()[0], 0)


class ArchiveAuthorizationTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def test_archive_prefers_detail_metadata_to_brief_history_and_remains_immutable(self):
        owner = self.signed_in(user(76201, "archive-detail-owner"))
        headers = {"Origin": ORIGIN}
        team = owner.post("/api/workspaces", headers=headers, json={"name": "Archive fidelity"}).json()["id"]
        owner.post("/api/workspaces/"+team+"/switch", headers=headers)
        actor = owner.get("/api/session").json()["account"]["id"]
        machine = self.pair(owner)
        bound = owner.post("/api/workspaces/projects", headers=headers,
                           json={"worker": machine["id"], "path": "/project", "members": [actor]})
        self.assertEqual(bound.status_code, 200, bound.text)
        identifier, without_detail, run_id = str(uuid4()), str(uuid4()), str(uuid4())
        summary = {"id": identifier, "workspace": "/project", "title": "Awaiting approval",
                   "status": "awaiting_approval", "requester": actor, "run_id": run_id}
        unknown = {**summary, "id": without_detail, "title": "No captured digest"}
        detail = {**summary, "candidate": {"digest": "a"*64}, "reviewer": "recorded-reviewer",
                  "delivery": {"local": "pending", "github": "pending"},
                  "comments": [{"message": "PRIVATE_DETAIL_CANARY"}], "prompt": "PRIVATE_DETAIL_CANARY"}
        hub = self.app.state.executors
        with self.store.connect() as db:
            hub._cache(db, machine["id"], "/api/workflows",
                       {"status": 200, "body": [summary, unknown], "content_type": "application/json"})
            hub._cache(db, machine["id"], "/api/workflows/"+identifier,
                       {"status": 200, "body": detail, "content_type": "application/json"})
        revoked = owner.delete("/api/executors/"+machine["id"], headers=headers)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        response = owner.get("/api/executors/archives")
        self.assertEqual(response.status_code, 200, response.text)
        archived = {v["id"]: v for v in response.json()["items"]}
        self.assertEqual(archived[identifier]["candidate_digest"], "a"*64)
        self.assertEqual(archived[identifier]["run_id"], run_id)
        self.assertEqual(archived[identifier]["reviewer"], "recorded-reviewer")
        self.assertEqual(archived[identifier]["delivery"], detail["delivery"])
        self.assertIsNone(archived[without_detail]["candidate_digest"])
        self.assertNotIn("PRIVATE_DETAIL_CANARY", response.text)
        # A repeated internal archive pass must not replace a record captured
        # at revocation, even if a fixture subsequently supplies newer detail.
        with self.store.connect() as db:
            hub._cache(db, machine["id"], "/api/workflows/"+identifier,
                       {"status": 200, "body": {**detail, "candidate": {"digest": "b"*64}}, "content_type": "application/json"})
            hub._archive_worker(db, machine["id"], team)
            db.execute("DELETE FROM worker_cache WHERE worker=?", (machine["id"],))
            self.assertEqual(db.execute("SELECT revoked FROM worker_scope WHERE worker=?", (machine["id"],)).fetchone()[0], 1)
        self.assertEqual(owner.get("/api/executors/archives").json()["items"], response.json()["items"])

    def test_archive_uses_newer_summary_state_without_losing_same_run_digest(self):
        owner = self.signed_in(user(76301, "archive-latest-owner"))
        headers = {"Origin": ORIGIN}
        team = owner.post("/api/workspaces", headers=headers, json={"name": "Newest archive state"}).json()["id"]
        owner.post("/api/workspaces/"+team+"/switch", headers=headers)
        machine = self.pair(owner)
        bound = owner.post("/api/workspaces/projects", headers=headers,
                           json={"worker": machine["id"], "path": "/project", "members": []})
        self.assertEqual(bound.status_code, 200, bound.text)
        identifier, changed_run, run_id = str(uuid4()), str(uuid4()), str(uuid4())
        older = {"id": identifier, "workspace": "/project", "title": "Older detail", "run_id": run_id,
                 "updated_at": "2026-10-10T10:00:00+00:00", "status": "awaiting_approval",
                 "requester": "older-requester", "reviewer": "older-reviewer", "candidate": {"digest": "a"*64},
                 "delivery": {"local": "pending", "github": "pending"}}
        newer = {**older, "title": "Latest summary", "updated_at": "2026-10-11T10:00:00+00:00",
                 "status": "approved", "requester": "recorded-requester", "reviewer": "recorded-reviewer",
                 "approval": {"actor": "approving-reviewer", "action": "approve", "at": "2026-10-11T10:00:00+00:00"},
                 "delivery": {"local": "applied", "github": "published"}}
        newer.pop("candidate")
        other_detail = {**older, "id": changed_run}
        other_summary = {**newer, "id": changed_run, "run_id": str(uuid4())}
        hub = self.app.state.executors
        with self.store.connect() as db:
            for value in (older, other_detail):
                hub._cache(db, machine["id"], "/api/workflows/"+value["id"],
                           {"status": 200, "body": value, "content_type": "application/json"})
            hub._cache(db, machine["id"], "/api/workflows",
                       {"status": 200, "body": [newer, other_summary], "content_type": "application/json"})
        self.assertEqual(owner.delete("/api/executors/"+machine["id"], headers=headers).status_code, 200)
        items = {v["id"]: v for v in owner.get("/api/executors/archives").json()["items"]}
        record = items[identifier]
        for key in ("title", "updated_at", "status", "requester", "reviewer", "delivery"):
            self.assertEqual(record[key], newer[key])
        self.assertEqual(record["approval"]["actor"], "approving-reviewer")
        self.assertEqual(record["candidate_digest"], "a"*64)
        self.assertIsNone(items[changed_run]["candidate_digest"])

    def test_live_stream_closes_cleanly_when_worker_or_current_authorization_is_lost(self):
        for number, loss in enumerate(("worker", "member", "project", "session")):
            with self.subTest(loss=loss):
                owner = self.signed_in(user(76401+number*2, "stream-owner-"+loss))
                reviewer = self.signed_in(user(76402+number*2, "stream-reviewer-"+loss))
                headers = {"Origin": ORIGIN}
                team = owner.post("/api/workspaces", headers=headers, json={"name": "Stream "+loss}).json()["id"]
                owner.post("/api/workspaces/"+team+"/switch", headers=headers)
                invitation = owner.post("/api/workspaces/invitations", headers=headers, json={"role": "reviewer"}).json()
                reviewer.post("/api/invitations/accept", headers=headers, json={"token": invitation["token"]})
                reviewer.post("/api/workspaces/"+team+"/switch", headers=headers)
                actor = reviewer.get("/api/session").json()["account"]["id"]
                owner_actor = owner.get("/api/session").json()["account"]["id"]
                machine = self.pair(owner)
                hub = self.app.state.executors
                hub.features(machine["id"], WORKER_FEATURES)
                bound = owner.post("/api/workspaces/projects", headers=headers,
                                   json={"worker": machine["id"], "path": "/project", "members": [actor]}).json()[0]
                run_id = str(uuid4())
                with self.store.connect() as db:
                    hub._cache(db, machine["id"], "/api/runs/"+run_id,
                               {"status": 200, "body": {"run_id": run_id, "spec": {"workspace": "/project"}}, "content_type": "application/json"})
                hub.sync(machine["id"], [], [{"run_id": run_id, "sequence": 1, "timestamp": now(), "kind": "status", "data": {"message": "permitted before revocation"}}])
                principal = self.app.state.accounts.principal(owner.cookies.get(SESSION_COOKIE))
                reviewer_principal = self.app.state.accounts.principal(reviewer.cookies.get(SESSION_COOKIE))
                changed = []
                original_sleep = asyncio.sleep
                async def revoke_before_next_poll(seconds):
                    if seconds != 1:
                        return await original_sleep(seconds)
                    self.assertFalse(changed, "The stream did not end on its next authorization check")
                    changed.append(loss)
                    hub.sync(machine["id"], [], [{"run_id": run_id, "sequence": 2, "timestamp": now(), "kind": "status", "data": {"message": "AFTER_REVOKE_CANARY"}}])
                    if loss == "worker":
                        hub.revoke(machine["id"], team, authority={"actor": owner_actor, "session": principal.session})
                    elif loss == "member":
                        self.app.state.accounts.teams.remove(principal, actor)
                    elif loss == "project":
                        self.app.state.accounts.teams.update_project_members(principal, bound["id"],
                            ProjectMembersInput(request_id=str(uuid4()), members=[owner_actor]))
                    else:
                        self.app.state.accounts.end_session(reviewer_principal.session)
                    await original_sleep(0)
                with patch("parallax.server.asyncio.sleep", side_effect=revoke_before_next_poll):
                    response = reviewer.get("/api/executors/"+machine["id"]+"/proxy/runs/"+run_id+"/events")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('"sequence": 1', response.text)
                self.assertNotIn("AFTER_REVOKE_CANARY", response.text)
                self.assertEqual(changed, [loss])
                with self.store.connect() as db:
                    retained = db.execute("SELECT COUNT(*) FROM worker_events WHERE worker=?", (machine["id"],)).fetchone()[0]
                self.assertEqual(retained, 0 if loss == "worker" else 2)

    def test_archive_reads_recheck_workspace_membership_and_project_grants(self):
        owner = self.signed_in(user(76101, "archive-owner"))
        reviewer = self.signed_in(user(76102, "archive-reviewer"))
        outsider = self.signed_in(user(76103, "archive-outsider"))
        headers = {"Origin": ORIGIN}
        team = owner.post("/api/workspaces", headers=headers, json={"name": "Archive team"}).json()["id"]
        owner.post("/api/workspaces/"+team+"/switch", headers=headers)
        invitation = owner.post("/api/workspaces/invitations", headers=headers, json={"role": "reviewer"}).json()
        reviewer.post("/api/invitations/accept", headers=headers, json={"token": invitation["token"]})
        reviewer.post("/api/workspaces/"+team+"/switch", headers=headers)
        actor = reviewer.get("/api/session").json()["account"]["id"]
        owner_actor = owner.get("/api/session").json()["account"]["id"]
        machine = self.pair(owner, workspaces=("/shared", "/restricted"))
        self.app.state.executors.features(machine["id"], WORKER_FEATURES)
        bindings, workflows = {}, {}
        for path, members in (("/shared", [actor]), ("/restricted", [owner_actor])):
            bound = owner.post("/api/workspaces/projects", headers=headers, json={"worker": machine["id"], "path": path, "members": members})
            self.assertEqual(bound.status_code, 200, bound.text)
            bindings[path] = next(v["id"] for v in bound.json() if v["path"] == path)
            identifier = str(uuid4())
            workflows[path] = identifier
            with self.store.connect() as db:
                self.app.state.executors._cache(db, machine["id"], "/api/workflows/"+identifier,
                    {"status": 200, "body": {"id": identifier, "workspace": path, "title": path,
                     "requester": owner_actor, "status": "approved", "prompt": "SECRET_ARCHIVE_CANARY"}, "content_type": "application/json"})
        principal = self.app.state.accounts.principal(owner.cookies.get(SESSION_COOKIE))
        context = self.app.state.accounts.teams.context(principal, machine["id"])
        async def dispatch_once():
            request = asyncio.create_task(self.app.state.executors.request(machine["id"], "POST",
                "/api/workflows/"+workflows["/shared"]+"/apply", "", {"request_id": str(uuid4()), "candidate_digest": "a"*64},
                workspace=team, timeout=2, authority=context))
            try:
                for _ in range(100):
                    await asyncio.sleep(.002)
                    commands = self.app.state.executors.pending(machine["id"])
                    if commands:
                        self.assertEqual(commands[0]["authority"]["actor"], owner_actor)
                        return
                self.fail("No command reached the first dispatch boundary")
            finally:
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
        asyncio.run(dispatch_once())
        revoked = owner.delete("/api/executors/"+machine["id"], headers=headers)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        response = reviewer.get("/api/executors/archives")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({v["project"] for v in response.json()["items"]}, {"/shared"})
        operation = next(v for v in response.json()["items"] if v["kind"] == "operation")
        self.assertEqual(operation["actor"], owner_actor)
        self.assertEqual(operation["state"], "revoked_pending_reconciliation")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_cache WHERE worker=?", (machine["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_operation_receipts WHERE worker=?", (machine["id"],)).fetchone()[0], 1)
        page = reviewer.get("/api/executors/archives?limit=1").json()
        self.assertTrue(page["has_more"])
        self.assertEqual(len(reviewer.get("/api/executors/archives", params={"cursor": page["next_cursor"], "limit": 1}).json()["items"]), 1)
        self.assertNotIn("SECRET_ARCHIVE_CANARY", response.text)
        self.assertEqual(outsider.get("/api/executors/archives").json()["items"], [])
        change_id = str(uuid4())
        endpoint = "/api/workspaces/projects/"+bindings["/shared"]
        body = {"request_id": change_id, "members": [owner_actor]}
        self.assertEqual(reviewer.patch(endpoint, headers=headers, json=body).status_code, 403)
        self.assertEqual(owner.patch(endpoint, headers=headers, json={**body, "worker": machine["id"]}).status_code, 422)
        changed = owner.patch(endpoint, headers=headers, json=body)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(owner.patch(endpoint, headers=headers, json=body).status_code, 200)
        self.assertEqual(owner.patch(endpoint, headers=headers, json={**body, "members": []}).status_code, 409)
        with self.store.connect() as db:
            recorded = db.execute("SELECT actor,binding FROM project_policy_operations WHERE id=?", (change_id,)).fetchone()
            self.assertEqual(tuple(recorded), (owner_actor, bindings["/shared"]))
            self.assertEqual(db.execute("SELECT revoked FROM worker_scope WHERE worker=?", (machine["id"],)).fetchone()[0], 1)
        self.assertEqual(reviewer.get("/api/executors/archives").json()["items"], [])
        self.assertEqual(owner.delete("/api/workspaces/members/"+actor, headers=headers).status_code, 200)
        self.assertEqual(reviewer.get("/api/executors/archives").status_code, 401)
        self.app.state.accounts.end_session(principal.session)
        with self.assertRaises(HTTPException) as refused:
            self.app.state.accounts.teams.update_project_members(principal, bindings["/shared"],
                ProjectMembersInput(request_id=str(uuid4()), members=[]))
        self.assertEqual(refused.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
