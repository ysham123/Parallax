"""Durable execution intervals, separate from mutable run artifacts."""
from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path


def boot_identity():
    try:
        if sys.platform == "linux":
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if sys.platform == "darwin":
            result = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
                                    capture_output=True, text=True, timeout=2, check=True)
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class ExecutionBudget:
    def __init__(self, store):
        self.store = store
        self.boot = boot_identity()
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_budget (
                run_id TEXT PRIMARY KEY, used REAL NOT NULL, maximum REAL NOT NULL,
                started REAL NOT NULL, boot TEXT, active INTEGER NOT NULL)""")

    def begin(self, run_id, used, maximum):
        used = max(0.0, float(used))
        started = time.monotonic()
        # Durable before any project/provider effect; stale artifact saves cannot
        # delete this interval. One Engine owns the locked runtime state.
        with self.store.connect() as db:
            row = db.execute("SELECT used,active FROM execution_budget WHERE run_id=?", (run_id,)).fetchone()
            if row and row["active"]:
                raise ValueError("Active execution budget requires recovery before resume")
            if row:
                used = max(used, row["used"])
            db.execute("INSERT OR REPLACE INTO execution_budget VALUES(?,?,?,?,?,1)",
                       (run_id, used, maximum, started, self.boot))
        return started, used

    def end(self, run_id, used):
        with self.store.connect() as db:
            db.execute("UPDATE execution_budget SET used=MAX(used,?),active=0 WHERE run_id=?", (used, run_id))

    def recover(self, result):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM execution_budget WHERE run_id=?", (result["run_id"],)).fetchone()
            if not row:
                return False  # Legacy records retain their already saved budget.
            consumed = row["used"]
            if row["active"]:
                elapsed = time.monotonic() - row["started"]
                # On the same boot, monotonic time spans process loss and restart.
                # The unknown interval includes downtime until reconciliation.
                # Reboot/unknown clock cannot safely establish unused allowance.
                same_clock = self.boot and self.boot == row["boot"] and math.isfinite(elapsed) and elapsed >= 0
                consumed = max(consumed, min(row["maximum"], consumed + elapsed)) if same_clock else max(consumed, row["maximum"])
                db.execute("UPDATE execution_budget SET used=?,active=0 WHERE run_id=?", (consumed, result["run_id"]))
            saved = result.setdefault("artifacts", {}).get("runtime_seconds", 0)
            if consumed <= saved:
                return False
            result["artifacts"]["runtime_seconds"] = math.ceil(consumed * 1000) / 1000
            result["artifacts"]["budget_recovery"] = "Unknown active interval charged through recovery; reboot or unavailable clock consumes the remaining allowance."
            return True
