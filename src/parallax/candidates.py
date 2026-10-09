"""Exact-candidate approval over the existing verified workspace transaction."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .receipt import build_receipt, save_receipt
from .store import now
from .workspaces import WorkspaceManager, WorkspaceError

POLICY = "verified-change-v1"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Candidates:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store

    def manager(self, result):
        path = self.store.home / "runs" / result["run_id"]
        if Path(result["artifacts"]["directory"]).resolve() != path.resolve():
            raise ValueError("Candidate is outside managed run storage")
        manager = WorkspaceManager(Path(result["spec"]["workspace"]), path)
        if not manager.load():
            raise ValueError("The saved candidate is missing. Start a new workflow.")
        return manager

    def _capture(self, result, manager):
        artifacts = result["artifacts"]
        if result["status"] != "completed" or not artifacts.get("verified_only") or artifacts.get("integration_applied"):
            raise ValueError("A completed, unapplied verified candidate is required")
        receipt = build_receipt(result)
        gates = [gate for gate in receipt["gates"] if gate["id"] in {"current_verification", "independent_review", "project_checks"}]
        if len(gates) != 3 or any(gate["status"] != "passed" for gate in gates):
            raise ValueError("The candidate has not passed every verification gate")
        destination = manager.check_destination()
        if not destination["ok"] or destination["revalidate"]:
            raise ValueError("The project changed since verification. Prepare a new candidate before approval.")
        if manager.diff() != result["diff"]:
            raise ValueError("The candidate changed since verification")
        source = manager.fingerprint(manager.workspace)
        if source != artifacts.get("source_snapshot_sha256"):
            raise ValueError("Project files or staging changed since verification")
        identity = {"run_id": result["run_id"], "policy": POLICY, "spec": digest(result["spec"]),
            "patch": digest(result["diff"]), "source": source,
            "tree": manager.fingerprint(manager.integration_path),
            "evidence": digest({"checks":result["checks"], "reviews":result["reviews"],
                "validated":artifacts.get("validated_fingerprint"), "required_checks":artifacts.get("required_checks")})}
        return {"digest": digest(identity), "identity": identity, "gates": gates,
            "changed_files": result["changed_files"], "check_count": len(result["checks"]),
            "summary": result.get("summary", ""), "captured_at": now()}

    async def capture(self, run_id):
        def inspect():
            result = self.store.get(run_id)
            if result["artifacts"].get("application", {}).get("state") == "applying":
                raise ValueError("Application needs reconciliation before the candidate can be inspected")
            try:
                return self._capture(result, self.manager(result))
            except (WorkspaceError, OSError) as exc:
                raise ValueError(f"Saved candidate cannot be verified: {exc}. Prepare a new workflow.") from exc
        return await self.engine._workspace_call(inspect)

    async def apply(self, run_id, expected_digest, decision_id):
        if run_id in self.engine.jobs:
            raise ValueError("This run is still settling. Try again shortly.")
        result = self.store.get(run_id)
        self.store.claim(result["spec"]["workspace"], run_id)
        try:
            application = result["artifacts"].get("application", {})
            if application and (application.get("digest") != expected_digest or application.get("decision_id") != decision_id):
                raise ValueError("This candidate already has a different application decision")
            if application.get("state") == "blocked":
                raise ValueError("This application was blocked. Inspect the project and prepare a new candidate.")
            if result["artifacts"].get("integration_applied"):
                if not application:
                    raise ValueError("Changes were already applied outside this workflow")
                return result
            manager = await self.engine._workspace_call(self.manager, result)
            # WorkspaceManager reconciles a durable apply transaction under the project lock.
            metadata = manager.prepare()
            if application.get("state") == "applying":
                if metadata.get("applied"):
                    return self._finish(result, metadata.get("applied_changed_files", []), metadata.get("preservation", {}))
                raise ValueError("Interrupted application was not replayed. Inspect the project and start a new workflow.")
            current = await self.engine._workspace_call(self._capture, result, manager)
            if current["digest"] != expected_digest:
                raise ValueError("The approved candidate or its evidence changed. Prepare a new candidate.")
            result["artifacts"]["application"] = {"state":"applying", "digest":expected_digest,
                "decision_id":decision_id, "approved_at":now(), "policy":POLICY}
            self.store.save(result)
            self.store.event(run_id, "application_approved", {"candidate":expected_digest,"decision_id":decision_id})
            applied = await self.engine._workspace_call(manager.apply)
            if not applied["ok"]:
                result["artifacts"]["application"]["state"] = "blocked"
                self.store.save(result)
                raise ValueError(applied.get("error") or "Candidate application was blocked")
            return self._finish(result, applied.get("changed_files", []), applied.get("preservation", {}))
        finally:
            self.store.release(run_id)

    def _finish(self, result, changed_files, preservation):
        result["artifacts"]["integration_applied"] = True
        result["artifacts"]["preservation"] = preservation
        result["artifacts"]["application"]["state"] = "applied"
        result["artifacts"]["application"]["applied_at"] = now()
        result["changed_files"] = changed_files
        save_receipt(result)
        self.store.save(result)
        self.store.event(result["run_id"], "candidate_applied", {"changed_files":changed_files})
        return result
