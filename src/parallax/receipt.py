"""Small, shareable verification records, backed by recorded runtime evidence.

This is an evidence receipt, not a signature or a guarantee of correctness.
Exports intentionally omit prompts, raw sessions, endpoints and command output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from .store import now


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build_receipt(result: dict, *, final: bool = False) -> dict:
    spec = result["spec"]
    artifacts = result.get("artifacts", {})
    patch = result.get("diff", "")
    current = "validated_fingerprint" in artifacts and artifacts["validated_fingerprint"] == patch
    checks = result.get("checks", [])
    checks_pass = bool(checks) and all(check.get("ok") is True for check in checks)
    reviews = result.get("reviews", [])
    combined = [review for review in reviews if review.get("task_id") == "integration"]
    contributors = {task["provider"] for task in result.get("tasks", [])
                    if task.get("status") == "completed"
                    and (spec["mode"] != "compare" or task["id"] == artifacts.get("selected_task"))}
    independent = bool(combined and combined[-1].get("ok") is True
                       and combined[-1].get("provider") not in contributors)
    applied = artifacts.get("integration_applied") is True
    verified = artifacts.get("verified_only") is True
    preservation = artifacts.get("preservation", {})
    preserved = all(preservation.get(key) is True for key in ("staging", "head", "branch", "unrelated_files"))
    consultation = spec["mode"] == "review"
    def gate(identifier, label, status, detail):
        return {"id": identifier, "label": label, "status": status, "detail": detail}
    gates = [
        gate("current_verification", "Verified candidate", "not_requested" if consultation else "passed" if current else "unknown",
             "Recorded verification matches this patch." if current else "No current combined verification is recorded."),
        gate("independent_review", "Independent combined review", "not_requested" if consultation else "passed" if current and independent else "failed" if combined and not combined[-1].get("ok") else "unknown",
             "A provider outside the implementing team approved the candidate." if current and independent else "Approval must refer to the current candidate."),
        gate("project_checks", "Project checks", "not_requested" if consultation else "passed" if current and checks_pass else "failed" if checks and not checks_pass else "unknown",
             f"{len(checks)} recorded command(s); current candidate verified." if current and checks_pass else "Passing command output is required before integration."),
        gate("integration", "Applied to project", "passed" if applied else "not_requested" if consultation or not spec.get("integrate", True) else "unknown",
             "Runtime recorded successful application." if applied else "Verified patch retained; application disabled." if verified else "No successful application is recorded."),
        gate("preservation", "Staging and unrelated files preserved", "passed" if applied and preserved else "not_requested" if consultation or not spec.get("integrate", True) else "unknown",
             "Git staging, HEAD, branch and unrelated files matched during recorded application or recovery." if preserved else "This run has no explicit preservation record."),
    ]
    def participant(value):
        return {key: value.get(key) for key in ("provider", "transport", "model", "effort", "role")}
    requested = {"mode": spec["mode"], "coordinator": participant(spec["coordinator"]),
                 "team": [participant(member) for member in spec["team"]],
                 "limits": spec["limits"], "integrate": spec.get("integrate", True)}
    effective = []
    for session in result.get("sessions", []):
        settings = session.get("effective_settings", {})
        item = {"provider": session.get("provider"), "transport": session.get("transport", "cli"),
                "model": settings.get("model"), "effort": settings.get("effort")}
        if item not in effective:
            effective.append(item)
    hashes = {"patch_sha256": _digest(patch),
              "spec_sha256": _digest(json.dumps(spec, sort_keys=True, separators=(",", ":")))}
    if artifacts.get("source_snapshot_sha256"):
        hashes["source_snapshot_sha256"] = artifacts["source_snapshot_sha256"]
    def safe_check(check,index):
        return {"id":f"check-{index+1}","ok":check.get("ok") is True,"exit_code":check.get("exit_code"),"elapsed_seconds":check.get("elapsed_seconds"),
                "environment":{"private":check.get("environment",{}).get("private"),"python_venv":check.get("environment",{}).get("python_venv"),"sandbox":check.get("environment",{}).get("sandbox"),"manifest_sha256":check.get("environment",{}).get("manifest_sha256",{})}}
    baseline=artifacts.get("baseline_checks",[])
    return {"contract_version": "1.1", "run_id": result["run_id"], "generated_at": now(),
            "record_state": "final" if final else "snapshot",
            "outcome": "applied" if applied else "verified" if verified else "partial",
            "gates": gates, "artifacts": hashes, "changed_files": result.get("changed_files", []),
            "requested": requested, "effective": effective,
            "checks": [{"id": f"check-{index + 1}", "ok": check.get("ok") is True,
                        "exit_code": check.get("exit_code"), "elapsed_seconds": check.get("elapsed_seconds")}
                       for index, check in enumerate(checks)],
            "baseline": {"recorded":artifacts.get("baseline_complete",False),"snapshot_sha256":artifacts.get("baseline_snapshot_sha256"),"checks":[safe_check(c,i) for i,c in enumerate(baseline)]},
            "final_checks": [safe_check(c,i) for i,c in enumerate(checks)],
            "reviews": [{key: review.get(key) for key in ("provider", "task_id", "ok")} for review in reviews],
            "limitations": ["Evidence covers recorded checks and reviews; it does not prove correctness.",
                            "Manifest hashes identify declared setup; unpinned dependencies may resolve differently.",
                            "This local record is not signed. Its hashes identify the patch and run specification.",
                            "Export omits prompts, raw sessions, endpoints, absolute workspace paths and command output."]}


def save_receipt(result: dict) -> dict:
    record = build_receipt(result, final=True)
    target = Path(result["artifacts"]["directory"]) / "verification.json"
    temporary = target.with_suffix(".json.tmp")
    data = json.dumps(record, indent=2, sort_keys=True) + "\n"
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    result["artifacts"]["verification_record"] = str(target)
    result["artifacts"]["verification_record_sha256"] = _digest(data)
    return record


def get_receipt(store, run_id: str) -> dict:
    result = store.get(run_id)
    # Never follow an artifact path supplied by a provider or an imported result.
    target = store.home / "runs" / run_id / "verification.json"
    if target.is_symlink() or not target.resolve().is_relative_to((store.home / "runs").resolve()):
        raise ValueError("Verification record path is outside managed run storage")
    if result.get("artifacts", {}).get("verification_record_sha256") and target.is_file():
        data = target.read_text()
        if _digest(data) != result["artifacts"]["verification_record_sha256"]:
            raise ValueError("Verification record changed; preserved run evidence remains available")
        record = json.loads(data)
        if record["artifacts"]["patch_sha256"] != _digest(result.get("diff", "")):
            raise ValueError("Verification record does not match the saved patch")
        if record["artifacts"]["spec_sha256"] != _digest(json.dumps(result["spec"],sort_keys=True,separators=(",", ":"))):
            raise ValueError("Verification record does not match the saved run specification")
        return record
    return build_receipt(result)
