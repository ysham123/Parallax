"""Runtime-owned references to immutable check and review observations.

Observation content never includes a candidate digest or human labels. The
append-only journal is authoritative; result arrays and receipts are views.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from uuid import UUID, uuid4, uuid5

READONLY_SCHEME = "readonly-workspace-state-v1"
MANAGED_SCHEME = "managed-workspace-state-v1"
CONTENT_SCHEME = "canonical-json-sha256-v1"
LEGACY_NAMESPACE = UUID("c4b05847-214b-4cc1-b10b-0dfb65e4a9cf")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def content_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def phase_attempt(phase: str, task_id=None, worker_attempt=None) -> dict:
    return {"phase_attempt_id": str(uuid4()), "phase": phase,
            **({"task_id": task_id} if task_id is not None else {}),
            **({"worker_attempt": worker_attempt} if worker_attempt is not None else {})}


def _content(kind: str, evidence: dict, metadata: dict) -> dict:
    # These fields are generated only by this runtime. In particular an agent
    # cannot inject an observation, approval decision or evaluation label.
    observation = {key: value for key, value in metadata.items()
                   if key not in {"id", "content_sha256"}}
    payload = {key: value for key, value in evidence.items()
               if key not in {"observation", "candidate_digest", "labels"}}
    return {"kind": kind, "observation": observation, "evidence": payload}


def record_observation(store, run_id: str, kind: str, evidence: dict, attempt: dict,
                       *, before=None, after=None, patch=None, requirements=None,
                       check_spec=None) -> dict:
    if kind not in {"check", "review"}:
        raise ValueError("Unsupported evidence observation kind")
    metadata = {"schema_version": "1.0", "id": str(uuid4()), **attempt,
                "content_scheme": CONTENT_SCHEME,
                "provenance": {"scheme": READONLY_SCHEME, "before_sha256": before,
                               "after_sha256": after,
                               "unchanged": before == after if before is not None and after is not None else None}}
    if patch is not None:
        metadata["patch_sha256"] = text_digest(patch)
    if requirements is not None:
        metadata["requirements_sha256"] = content_digest(requirements)
        if isinstance(requirements, dict) and isinstance(requirements.get("request"), str):
            metadata["request_sha256"] = text_digest(requirements["request"])
    if check_spec is not None:
        metadata["check_spec_sha256"] = content_digest(check_spec)
    metadata["content_sha256"] = content_digest(_content(kind, evidence, metadata))
    payload = copy.deepcopy({key: value for key, value in evidence.items()
                             if key not in {"observation", "candidate_digest", "labels"}})
    store.event(run_id, "evidence_observation", {"kind": kind, "observation": metadata,
                                               "evidence": payload}, attempt.get("task_id"))
    return {**payload, "observation": metadata}


def observation_from_event(run_id: str, event: dict) -> dict | None:
    data = event["data"]
    if event["kind"] == "evidence_observation":
        if not isinstance(data, dict) or data.get("kind") not in {"check", "review"}:
            raise ValueError("Malformed evidence observation")
        metadata, evidence = data.get("observation"), data.get("evidence")
        if not isinstance(metadata, dict) or not isinstance(evidence, dict):
            raise ValueError("Malformed evidence observation")
        try:
            UUID(metadata["id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Malformed evidence observation identity") from exc
        if not SHA256.fullmatch(metadata.get("content_sha256", "")):
            raise ValueError("Malformed evidence observation digest")
        if content_digest(_content(data["kind"], evidence, metadata)) != metadata["content_sha256"]:
            raise ValueError("Evidence observation content changed")
        return {"kind": data["kind"], "observation": copy.deepcopy(metadata),
                "evidence": copy.deepcopy(evidence), "sequence": event["sequence"],
                "timestamp": event["timestamp"], "legacy": False}
    if event["kind"] not in {"check", "review"} or not isinstance(data, dict):
        return None
    # New rows have their own journal record. Never reinterpret a copied event
    # as a second, weaker anchor for the same observation.
    if "observation" in data:
        return None
    identifier = str(uuid5(LEGACY_NAMESPACE, f"{run_id}:{event['sequence']}"))
    metadata = {"schema_version": "1.0", "id": identifier,
                "phase_attempt_id": str(uuid5(LEGACY_NAMESPACE, f"legacy:{run_id}:{event['sequence']}")),
                "phase": data.get("phase", "legacy"), "content_scheme": CONTENT_SCHEME,
                "provenance": None}
    if event.get("task_id") is not None:
        metadata["task_id"] = event["task_id"]
    metadata["content_sha256"] = content_digest(_content(event["kind"], data, metadata))
    return {"kind": event["kind"], "observation": metadata, "evidence": copy.deepcopy(data),
            "sequence": event["sequence"], "timestamp": event["timestamp"], "legacy": True}


def safe_observation(value) -> dict | None:
    """Whitelist only scalar identities; never export untrusted nested content."""
    if not isinstance(value, dict):
        return None
    try:
        identifier = str(UUID(value["id"]))
        attempt = str(UUID(value["phase_attempt_id"]))
    except (KeyError, ValueError, TypeError):
        return None
    digest = value.get("content_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return None
    out = {"schema_version": "1.0", "id": identifier, "content_sha256": digest,
           "phase_attempt_id": attempt, "content_scheme": CONTENT_SCHEME}
    if value.get("phase") in {"baseline", "final", "alternative", "task", "consultation", "legacy"}:
        out["phase"] = value["phase"]
    # Task identifiers are local labels, not arbitrary paths or command output.
    task = value.get("task_id")
    if isinstance(task, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", task):
        out["task_id"] = task
    if type(value.get("worker_attempt")) is int and value["worker_attempt"] >= 1:
        out["worker_attempt"] = value["worker_attempt"]
    if type(value.get("reviewer_attempt")) is int and value["reviewer_attempt"] >= 1:
        out["reviewer_attempt"] = value["reviewer_attempt"]
    for key in ("patch_sha256", "requirements_sha256", "check_spec_sha256", "request_sha256", "check_specs_sha256", "required_checks_sha256"):
        if isinstance(value.get(key), str) and SHA256.fullmatch(value[key]):
            out[key] = value[key]
    provenance = value.get("provenance")
    if isinstance(provenance, dict) and provenance.get("scheme") in {READONLY_SCHEME, MANAGED_SCHEME}:
        safe = {"scheme": provenance["scheme"]}
        for key in ("before_sha256", "after_sha256"):
            if isinstance(provenance.get(key), str) and SHA256.fullmatch(provenance[key]):
                safe[key] = provenance[key]
        if type(provenance.get("unchanged")) is bool:
            safe["unchanged"] = provenance["unchanged"]
        out["provenance"] = safe
    else:
        out["provenance"] = None
    return out


def bind_current_observations(store, result: dict, workspace) -> dict | None:
    """Check new provenance at an effect/approval boundary; retain legacy gates.

    This is the existing exact-candidate requirement, not an additional review
    policy. Old evidence has no observation contract and keeps its old checks.
    New evidence must still describe the actual bytes *and* Git inputs that the
    recorded checks and independent review observed.
    """
    from .workspaces import fingerprint
    checks = result.get("checks", [])
    combined = [row for row in result.get("reviews", []) if row.get("task_id") == "integration"]
    review = combined[-1] if combined else None
    modern = any(row.get("schema_version") == "1.2" or row.get("observation") is not None for row in checks)
    modern = modern or bool(review and review.get("observation") is not None)
    artifacts = result.get("artifacts", {})
    modern = modern or "current_verification_attempt" in artifacts or "verified_workspace_binding" in artifacts
    if not modern:
        return None
    attempt = artifacts.get("current_verification_attempt", {})
    phase = attempt.get("phase_attempt_id") if isinstance(attempt, dict) else None
    try:
        UUID(phase)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Current evidence has no recorded final verification attempt") from exc
    if attempt.get("phase") != "final" or not checks or review is None:
        raise ValueError("Current checks and independent review are required for this candidate")
    spec = result.get("spec", {})
    request = spec.get("prompt")
    configured = spec.get("checks")
    if not isinstance(request, str) or not isinstance(configured, list) or len(configured) != len(checks):
        raise ValueError("The verified request or check contract changed; verify it again")
    contract = {"request_sha256":text_digest(request),"check_specs_sha256":content_digest(configured),
                "required_checks_sha256":content_digest(artifacts.get("required_checks", []))}
    actual = fingerprint(workspace)
    recorded = {row["observation"]["id"]: row for row in store.observations(result["run_id"])}
    identifiers = []
    for kind, row in [*(("check", row) for row in checks), ("review", review)]:
        metadata = row.get("observation")
        if not isinstance(metadata, dict):
            raise ValueError("Current evidence has incomplete workspace provenance")
        journal = recorded.get(metadata.get("id"))
        if (journal is None or journal["kind"] != kind or journal["observation"] != metadata
                or content_digest(_content(kind, row, metadata)) != metadata.get("content_sha256")):
            raise ValueError("Current evidence changed from its recorded observation")
        if any(metadata.get(key) != value for key, value in contract.items()):
            raise ValueError("The verified request or check contract changed; verify it again")
        provenance = metadata.get("provenance")
        if (metadata.get("phase") != "final" or metadata.get("phase_attempt_id") != phase
                or not isinstance(provenance, dict) or provenance.get("scheme") != READONLY_SCHEME
                or provenance.get("unchanged") is not True
                or provenance.get("before_sha256") != actual or provenance.get("after_sha256") != actual):
            raise ValueError("Candidate workspace or Git state changed since checks and review; verify it again")
        if kind == "review" and metadata.get("patch_sha256") != text_digest(result.get("diff", "")):
            raise ValueError("Independent review does not describe this candidate patch")
        identifiers.append(metadata["id"])
    previous = result.get("artifacts", {}).get("verified_workspace_binding")
    if previous is not None and (not isinstance(previous, dict) or previous.get("scheme") != READONLY_SCHEME
            or previous.get("workspace_state_sha256") != actual or previous.get("phase_attempt_id") != phase):
        raise ValueError("Candidate workspace changed after its verified integration boundary")
    return {"scheme":READONLY_SCHEME,"workspace_state_sha256":actual,"phase_attempt_id":phase,
            "observation_ids":identifiers}
