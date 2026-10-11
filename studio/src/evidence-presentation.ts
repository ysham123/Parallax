import type { Data, EvidenceObservation } from "./types";

export type EvidenceState =
  | "passed"
  | "failed"
  | "unavailable"
  | "skipped"
  | "unrecorded";
export type EvidencePresentation = {
  state: EvidenceState;
  label: string;
  detail: string;
};
const object = (value: unknown): Data =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Data)
    : {};
const string = (value: unknown) => (typeof value === "string" ? value : "");
const errorOf = (row: Data) => {
  const error = object(row.error);
  return {
    code: string(error.code) || string(row.error),
    message: string(error.message),
  };
};
export function checkPresentation(row: Data): EvidencePresentation {
  const error = errorOf(row);
  const status = string(row.status);
  if (["skipped", "not_requested"].includes(status))
    return {
      state: "skipped",
      label: "Skipped",
      detail: error.message || "This command was not run.",
    };
  if (
    [
      "check_unavailable",
      "cancelled",
      "interrupted",
      "process_termination_failed",
    ].includes(error.code) ||
    ["unavailable", "interrupted", "cancelled"].includes(status)
  )
    return {
      state: "unavailable",
      label: "Unavailable",
      detail:
        error.message ||
        string(row.output) ||
        error.code ||
        "No usable command result was recorded.",
    };
  if (row.ok === false || status === "failed" || error.code)
    return {
      state: "failed",
      label: "Failed",
      detail:
        error.message || error.code || "The recorded command did not pass.",
    };
  if (
    row.ok === true ||
    status === "passed" ||
    row.exit_code === 0 ||
    row.returncode === 0
  )
    return {
      state: "passed",
      label: "Passed",
      detail:
        "The recorded command passed; coverage is limited to that command.",
    };
  if (typeof row.exit_code === "number" || typeof row.returncode === "number")
    return {
      state: "failed",
      label: "Failed",
      detail: "The recorded command returned a non-zero exit code.",
    };
  return {
    state: "unrecorded",
    label: "Unrecorded",
    detail: "No command outcome was recorded.",
  };
}
export function reviewPresentation(row: Data): EvidencePresentation {
  const error = errorOf(row);
  if (observationOf(row)?.provenance?.unchanged === false)
    return {
      state: "unavailable",
      label: "Unavailable",
      detail: "The review workspace changed during this observation.",
    };
  if (
    error.code === "readonly_changed" ||
    error.code === "provider_failed" ||
    error.code === "provider_unavailable"
  )
    return {
      state: "unavailable",
      label: "Unavailable",
      detail: error.message || error.code,
    };
  if (row.verdict === "rejected")
    return {
      state: "failed",
      label: "Changes requested",
      detail:
        error.message || "The reviewer explicitly rejected this candidate.",
    };
  if (
    error.code ||
    row.verdict === "unavailable" ||
    ["invalid", "unavailable", "no_verdict"].includes(string(row.status))
  )
    return {
      state: "unavailable",
      label: "Unavailable",
      detail:
        error.message ||
        error.code ||
        "No usable independent verdict was recorded.",
    };
  if (row.ok === true || row.verdict === "approved")
    return {
      state: "passed",
      label: "Reviewed",
      detail:
        "A positive review was recorded; this is separate from human approval.",
    };
  if (row.ok === false)
    return {
      state: "failed",
      label: "Changes requested",
      detail: "A negative review was recorded.",
    };
  return {
    state: "unrecorded",
    label: "Unrecorded",
    detail: "No independent verdict was recorded.",
  };
}
export function gatePresentation(gate: {
  status: string;
  detail?: string;
}): EvidencePresentation {
  const state: EvidenceState =
    gate.status === "passed"
      ? "passed"
      : gate.status === "failed"
        ? "failed"
        : gate.status === "unavailable"
          ? "unavailable"
          : ["skipped", "not_requested"].includes(gate.status)
            ? "skipped"
            : "unrecorded";
  return {
    state,
    label: {
      passed: "Passed",
      failed: "Failed",
      unavailable: "Unavailable",
      skipped: "Skipped",
      unrecorded: "Unrecorded",
    }[state],
    detail: gate.detail || "No additional gate evidence was recorded.",
  };
}
export function observationOf(row: Data): EvidenceObservation | null {
  const value = object(row.observation);
  return typeof value.id === "string" &&
    /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.id) &&
    typeof value.content_sha256 === "string" &&
    /^[a-f0-9]{64}$/.test(value.content_sha256)
    ? (value as unknown as EvidenceObservation)
    : null;
}
export function bindingPresentation(row: Data): string {
  const observation = observationOf(row);
  if (!observation) return "Artifact binding unrecorded";
  if (observation.provenance?.unchanged === false)
    return "Workspace changed during this observation; evidence cannot establish acceptance";
  if (observation.provenance?.unchanged !== true)
    return "Workspace provenance unrecorded; stability is unknown";
  return "Recorded workspace fingerprint; not a Git tree ID";
}
export function checkCounts(rows: Data[]) {
  const counts = {
    passed: 0,
    failed: 0,
    unavailable: 0,
    skipped: 0,
    unrecorded: 0,
  };
  for (const row of rows) counts[checkPresentation(row).state]++;
  return counts;
}
export function currentVerificationAttempt(artifacts: Data): string | null {
  const attempt = object(artifacts.current_verification_attempt);
  return attempt.phase === "final" &&
    typeof attempt.phase_attempt_id === "string"
    ? attempt.phase_attempt_id
    : null;
}
export function currentFinalChecks(
  rows: Data[],
  phaseAttempt: string | null,
): Data[] {
  return phaseAttempt
    ? rows.filter(
        (row) =>
          observationOf(row)?.phase === "final" &&
          observationOf(row)?.phase_attempt_id === phaseAttempt,
      )
    : [];
}
export function finalReview(
  rows: Data[],
  checks: Data[],
  phaseAttempt: string | null,
): Data | undefined {
  if (
    !phaseAttempt ||
    !checks.length ||
    checks.some((row) => observationOf(row)?.phase_attempt_id !== phaseAttempt)
  )
    return undefined;
  return rows
    .filter(
      (row) =>
        row.task_id === "integration" &&
        observationOf(row)?.phase === "final" &&
        observationOf(row)?.phase_attempt_id === phaseAttempt,
    )
    .at(-1);
}
export function nullableNumber(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}
