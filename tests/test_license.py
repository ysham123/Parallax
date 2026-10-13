"""Plan gate: free monthly allowance, Pro keys, offline grace, and nothing gated but new tasks."""
import json
import os
import stat
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from parallax import license as plan
from parallax.license import FREE_TASKS_PER_MONTH, License, PlanLimitReached
from parallax.models import RunResult, RunSpec, Participant
from parallax.store import Store

NOW = 1_791_900_000.0  # mid-October 2026


def seed_runs(store, count, *, started=NOW, mode="build"):
    for _ in range(count):
        spec = RunSpec(workspace="/tmp", prompt="x", mode=mode, team=[Participant(provider="claude"), Participant(provider="grok", role="reviewer")])
        result = RunResult(run_id=str(uuid.uuid4()), status="completed", spec=spec).model_dump()
        result["artifacts"] = {"started_at": started}
        store.save(result)


def api(status="granted", code=200, calls=None, expires_at=None):
    def handler(request):
        if calls is not None:
            calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        if code != 200:
            return httpx.Response(code, json={"detail": "nope"})
        if request.url.path.endswith("/activate"):
            return httpx.Response(200, json={"id": "act-1"})
        return httpx.Response(200, json={"status": status, "expires_at": expires_at})
    return httpx.MockTransport(handler)


class LicenseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        patcher = patch.dict(os.environ, {"PARALLAX_LICENSE_ORG": "org-test"})
        patcher.start(); self.addCleanup(patcher.stop)
        self.clock = [NOW]

    def plan(self, transport=None):
        return License(self.store, transport=transport or api(), clock=lambda: self.clock[0])

    async def test_builds_without_an_organization_are_unlimited(self):
        with patch.dict(os.environ, {"PARALLAX_LICENSE_ORG": ""}):
            seed_runs(self.store, 20)
            gate = self.plan()
            await gate.ensure_can_start("build")
            self.assertEqual(gate.status()["plan"], "unlimited")

    async def test_free_allowance_counts_this_months_build_and_compare_runs_only(self):
        seed_runs(self.store, FREE_TASKS_PER_MONTH - 1)
        seed_runs(self.store, 10, started=NOW - 40 * 24 * 3600)  # last month
        seed_runs(self.store, 10, mode="review")
        gate = self.plan()
        await gate.ensure_can_start("build")
        seed_runs(self.store, 1, mode="compare")
        with self.assertRaisesRegex(PlanLimitReached, "free plan includes 5 tasks"):
            await gate.ensure_can_start("build")
        # Read-only consultation is never gated.
        await gate.ensure_can_start("review")
        status = gate.status()
        self.assertEqual((status["plan"], status["used"], status["limit"]), ("free", 5, 5))

    async def test_pro_key_unlocks_and_is_stored_privately(self):
        calls = []
        seed_runs(self.store, 50)
        gate = self.plan(api(calls=calls))
        status = await gate.activate("POLAR-KEY-1234")
        self.assertEqual(status["plan"], "pro")
        self.assertEqual(status["key_hint"], "…1234")
        await gate.ensure_can_start("build")
        self.assertEqual([name for name, _ in calls], ["activate", "validate"])
        self.assertEqual(calls[1][1], {"key": "POLAR-KEY-1234", "organization_id": "org-test", "activation_id": "act-1"})
        mode = stat.S_IMODE(os.stat(Path(self.temp.name) / "license.json").st_mode)
        self.assertEqual(mode, 0o600)

    async def test_activation_not_required_still_validates(self):
        calls = []
        def handler(request):
            calls.append(request.url.path.rsplit("/", 1)[-1])
            if request.url.path.endswith("/activate"):
                return httpx.Response(403, json={"detail": "no activation limit"})
            return httpx.Response(200, json={"status": "granted"})
        status = await self.plan(httpx.MockTransport(handler)).activate("POLAR-KEY-5678")
        self.assertEqual(status["plan"], "pro")
        self.assertEqual(calls, ["activate", "validate"])

    async def test_rejected_revoked_and_expired_keys_fall_back_to_free(self):
        with self.assertRaisesRegex(ValueError, "not accepted"):
            await self.plan(api(code=404)).activate("BAD-KEY-0000")
        with self.assertRaisesRegex(ValueError, "not active"):
            await self.plan(api(status="revoked")).activate("REVOKED-KEY-1")
        with self.assertRaisesRegex(ValueError, "not active"):
            await self.plan(api(expires_at="2026-01-01T00:00:00Z")).activate("EXPIRED-KEY-1")
        with self.assertRaisesRegex(ValueError, "does not look like"):
            await self.plan().activate("short")
        self.assertEqual(self.plan().status()["plan"], "free")

    async def test_offline_grace_then_free(self):
        seed_runs(self.store, 10)
        gate = self.plan()
        await gate.activate("POLAR-KEY-1234")
        def offline(request):
            raise httpx.ConnectError("offline")
        offline_gate = self.plan(httpx.MockTransport(offline))
        self.clock[0] = NOW + 10 * 24 * 3600
        await offline_gate.ensure_can_start("build")  # within 14-day grace
        self.clock[0] = NOW + 15 * 24 * 3600
        with self.assertRaises(PlanLimitReached):
            await offline_gate.ensure_can_start("build")

    async def test_daily_revalidation_picks_up_revocation(self):
        seed_runs(self.store, 10)
        await self.plan().activate("POLAR-KEY-1234")
        self.clock[0] = NOW + 25 * 3600
        with self.assertRaises(PlanLimitReached):
            await self.plan(api(status="revoked")).ensure_can_start("build")

    async def test_deactivate_removes_the_key(self):
        await self.plan().activate("POLAR-KEY-1234")
        gate = self.plan(); gate.deactivate()
        self.assertFalse((Path(self.temp.name) / "license.json").exists())
        self.assertEqual(gate.status()["plan"], "free")


class EngineGateTests(unittest.IsolatedAsyncioTestCase):
    """The engine refuses only new tasks; retries of a recorded request are returned unchanged."""
    async def asyncSetUp(self):
        from test_workflows import WorkflowTests
        self.fixture = WorkflowTests()
        await WorkflowTests.asyncSetUp(self.fixture)
        self.addCleanup(self.fixture.temp.cleanup)
        self.addAsyncCleanup(WorkflowTests.asyncTearDown, self.fixture)
        patcher = patch.dict(os.environ, {"PARALLAX_LICENSE_ORG": "org-test"})
        patcher.start(); self.addCleanup(patcher.stop)

    async def test_workflow_start_is_refused_at_the_limit_but_its_retry_is_not(self):
        service = self.fixture.service
        request = self.fixture.request()
        with patch.object(service, "_launch", AsyncMock()):
            first = await service.start(request)
            seed_runs(self.fixture.store, FREE_TASKS_PER_MONTH, started=time.time())
            # The same request is a retry: returned, not counted or refused.
            self.assertEqual((await service.start(request))["id"], first["id"])
            with self.assertRaises(PlanLimitReached):
                await service.start(self.fixture.request())
        with self.fixture.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
