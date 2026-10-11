"""Exact-candidate approval over the existing verified workspace transaction."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .receipt import build_receipt, save_receipt
from .store import now
from .evidence import bind_current_observations
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
        binding=bind_current_observations(self.store,result,manager.integration_path)
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
            "delivery_target": digest(artifacts.get("authority",{}).get("github_target")),
            "evidence": digest({"checks":result["checks"], "reviews":result["reviews"],
                "validated":artifacts.get("validated_fingerprint"), "required_checks":artifacts.get("required_checks")})}
        if binding is not None:
            from .workspaces import fingerprint
            if fingerprint(manager.integration_path) != binding["workspace_state_sha256"]:
                raise ValueError("Candidate workspace changed while its approval identity was captured")
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

    def publication_tree(self, manager, target, previous=None):
        import base64
        metadata = manager.prepare()
        baseline_tree = manager._oid(manager.workspace, metadata["snapshot_commit"] + "^{tree}")
        if baseline_tree != target["base_tree"]:
            raise ValueError("Captured project tree does not match the remote baseline. Keep dirty tasks for local delivery")
        commit = metadata["integration_commit"]
        old = manager._tree(previous or metadata["snapshot_commit"])
        new = manager._tree(commit)
        additions, deletions = [], []
        size = 0
        for name in sorted(old.keys() | new.keys()):
            if old.get(name) == new.get(name): continue
            if name.startswith('.github/workflows/'):
                raise ValueError("Workflow-file changes are excluded from this pilot; use local delivery")
            if name not in new:
                deletions.append({"path":name}); continue
            mode, oid = new[name]
            if mode == '120000' or mode != (old.get(name) or ('100644',))[0]:
                raise ValueError("GitHub delivery does not support symlink or executable-mode changes; use local delivery")
            content = manager._git(manager.workspace,'cat-file','blob',oid).stdout
            size += len(content)
            if size > 4*1024*1024: raise ValueError("Candidate is too large for pilot GitHub delivery; use local delivery")
            additions.append({"path":name,"contents":base64.b64encode(content).decode()})
        return {"tree":manager._oid(manager.workspace,commit+'^{tree}'),"baseline":target["base_commit"],"baseline_tree":baseline_tree,
            "repository":target["full_name"],"base":target["base"],"additions":additions,"deletions":deletions}

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
                transaction = metadata.get("apply_transaction", {})
                if transaction.get("state") not in {None, "rolled_back"} or metadata.get("recovery_error"):
                    raise ValueError("Interrupted application needs inspection before it can be retried.")
                # A crash before the first write, or a fully verified rollback,
                # can retry the same saved decision. The exact source, candidate
                # and evidence are checked again below before any filesystem write.
            current = await self.engine._workspace_call(self._capture, result, manager)
            if current["digest"] != expected_digest:
                raise ValueError("The approved candidate or its evidence changed. Prepare a new candidate.")
            result["artifacts"]["application"] = {"state":"applying", "digest":expected_digest,
                "decision_id":decision_id, "approved_at":application.get("approved_at", now()), "policy":POLICY}
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
        save_receipt(result,journal_observations=self.store.observations(result["run_id"]))
        self.store.save(result)
        self.store.event(result["run_id"], "candidate_applied", {"changed_files":changed_files})
        return result
