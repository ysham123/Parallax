"""Plan and usage gate: a free monthly task allowance, unlimited with a Pro license key.

Licensing is active only when a seller organization is configured (``PARALLAX_LICENSE_ORG``
or ``ORGANIZATION_ID`` below). Development builds without one are unlimited.

The gate counts new Build and Compare runs started this calendar month (UTC) from the
local store. Retries of the same request and resumes reuse an existing run, so they never
count. Recovery, approval and delivery never start a run and are never gated.

The license key is stored only in the private state directory and is sent only to the
license API. Nothing about the project, prompts or code leaves the machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Set at release time to the seller's Polar organization ID. None keeps every build unlimited.
ORGANIZATION_ID: str | None = None
API = "https://api.polar.sh/v1/customer-portal/license-keys"
UPGRADE_URL = "https://github.com/ysham123/Parallax#pricing"
FREE_TASKS_PER_MONTH = 5
REVALIDATE_SECONDS = 24 * 3600
OFFLINE_GRACE_SECONDS = 14 * 24 * 3600
GATED_MODES = {"build", "compare"}


class PlanLimitReached(ValueError):
    """A new task would exceed the free plan's monthly allowance."""


def upgrade_url() -> str:
    return os.environ.get("PARALLAX_UPGRADE_URL", "").strip() or UPGRADE_URL


def organization() -> str | None:
    value = os.environ.get("PARALLAX_LICENSE_ORG", ORGANIZATION_ID or "")
    return value.strip() or None


def month_start(now: float | None = None) -> float:
    moment = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def next_month_start(now: float | None = None) -> datetime:
    moment = datetime.fromtimestamp(month_start(now), timezone.utc)
    return moment.replace(year=moment.year + 1, month=1) if moment.month == 12 else moment.replace(month=moment.month + 1)


class License:
    def __init__(self, store, *, transport: httpx.AsyncBaseTransport | None = None, clock=time.time):
        self.store = store
        self.path = Path(store.home) / "license.json"
        self.transport = transport
        self.clock = clock

    # Saved state ---------------------------------------------------------
    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value))
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    # Usage ---------------------------------------------------------------
    def tasks_this_month(self) -> int:
        start = month_start(self.clock())
        count = 0
        with self.store.connect() as db:
            for (raw,) in db.execute("SELECT result FROM runs"):
                try:
                    result = json.loads(raw)
                except ValueError:
                    continue
                started = (result.get("artifacts") or {}).get("started_at")
                mode = (result.get("spec") or {}).get("mode")
                if isinstance(started, (int, float)) and started >= start and mode in GATED_MODES:
                    count += 1
        return count

    # Plan ----------------------------------------------------------------
    def pro(self) -> bool:
        """A key counts while recently validated, or within the offline grace period."""
        saved = self._load()
        if saved.get("status") != "granted":
            return False
        expires = saved.get("expires_at")
        if isinstance(expires, (int, float)) and expires <= self.clock():
            return False
        last = saved.get("validated_at")
        return isinstance(last, (int, float)) and self.clock() - last <= OFFLINE_GRACE_SECONDS

    def status(self) -> dict:
        org = organization()
        used = self.tasks_this_month()
        if org is None:
            return {"licensing": False, "plan": "unlimited", "used": used, "limit": None}
        saved = self._load()
        plan = "pro" if self.pro() else "free"
        return {"licensing": True, "plan": plan, "used": used,
                "limit": None if plan == "pro" else FREE_TASKS_PER_MONTH,
                "resets_at": next_month_start(self.clock()).isoformat(),
                "key_hint": ("…" + saved["key"][-4:]) if plan == "pro" and isinstance(saved.get("key"), str) else None,
                "validated_at": saved.get("validated_at") if plan == "pro" else None,
                "upgrade_url": upgrade_url()}

    async def refresh(self) -> None:
        """Revalidate a saved key at most daily. Network failure keeps the grace period running."""
        saved = self._load()
        if not organization() or not saved.get("key"):
            return
        if self.clock() - (saved.get("validated_at") or 0) < REVALIDATE_SECONDS:
            return
        try:
            await self._validate(saved)
        except LicenseUnavailable:
            pass

    async def ensure_can_start(self, mode: str) -> None:
        if mode not in GATED_MODES or organization() is None:
            return
        await self.refresh()
        if self.pro():
            return
        used = self.tasks_this_month()
        if used >= FREE_TASKS_PER_MONTH:
            reset = next_month_start(self.clock())
            raise PlanLimitReached(f"The free plan includes {FREE_TASKS_PER_MONTH} tasks a month and {used} have started. "
                                   f"Upgrade to Pro at {upgrade_url()} or wait until {reset:%B} {reset.day}. "
                                   "Existing tasks stay available.")

    # License API ---------------------------------------------------------
    async def activate(self, key: str) -> dict:
        org = organization()
        if org is None:
            raise ValueError("This build has no license configured; it is already unlimited")
        key = key.strip()
        if not 8 <= len(key) <= 256 or any(ch.isspace() for ch in key):
            raise ValueError("That does not look like a license key")
        label = "parallax-" + hashlib.sha256((platform.node() + str(Path.home())).encode()).hexdigest()[:12]
        # Activation is only required for keys with an activation limit; validation decides acceptance.
        try:
            body = await self._post("activate", {"key": key, "organization_id": org, "label": label})
        except ValueError:
            body = {}
        saved = {"key": key, "activation_id": body.get("id") if isinstance(body.get("id"), str) else None}
        await self._validate(saved)
        if not self.pro():
            raise ValueError("The license key is not active")
        return self.status()

    def deactivate(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    async def _validate(self, saved: dict) -> None:
        payload = {"key": saved["key"], "organization_id": organization()}
        if saved.get("activation_id"):
            payload["activation_id"] = saved["activation_id"]
        body = await self._post("validate", payload)
        expires = body.get("expires_at")
        expiry = None
        if isinstance(expires, str):
            try:
                expiry = datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp()
            except ValueError:
                expiry = None
        status = body.get("status") if body.get("status") in {"granted", "revoked", "disabled"} else "invalid"
        self._save({**saved, "status": status, "expires_at": expiry, "validated_at": self.clock()})

    async def _post(self, action: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False, transport=self.transport,
                                         headers={"User-Agent": "Parallax"}) as client:
                response = await client.post(f"{API}/{action}", json=payload)
        except httpx.HTTPError:
            raise LicenseUnavailable("The license service could not be reached") from None
        if response.status_code in {400, 403, 404, 422}:
            raise ValueError("The license key was not accepted")
        if response.status_code != 200:
            raise LicenseUnavailable("The license service could not be reached")
        try:
            body = response.json()
        except ValueError:
            raise LicenseUnavailable("The license service returned an unreadable response") from None
        if not isinstance(body, dict):
            raise LicenseUnavailable("The license service returned an unreadable response")
        return body


class LicenseUnavailable(Exception):
    """The license API could not be reached; the offline grace period applies."""
