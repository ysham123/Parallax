export const workflowLabels: Record<string, string> = {
  queued: "Queued",
  preparing: "Preparing candidate",
  awaiting_approval: "Ready for your approval",
  applying: "Applying approved change",
  applied: "Applied",
  rejected: "Candidate declined",
  cancelled: "Stopped",
  interrupted: "Ready to resume",
  needs_attention: "Needs attention",
};
export function workflowGroup(
  status: string,
): "approval" | "running" | "attention" | "finished" {
  if (status === "awaiting_approval") return "approval";
  if (["queued", "preparing", "applying"].includes(status)) return "running";
  if (["interrupted", "needs_attention"].includes(status)) return "attention";
  return "finished";
}
export function workflowStep(status: string): number {
  if (status === "applied") return 3;
  if (status === "rejected") return 1;
  if (status === "applying") return 2;
  if (status === "awaiting_approval") return 1;
  return 0;
}

export function canApprove(
  status: string,
  candidate?: { digest: string; gates: { status: string }[] },
  decision?: unknown,
): boolean {
  return (
    status === "awaiting_approval" &&
    !decision &&
    !!candidate &&
    /^[a-f0-9]{64}$/.test(candidate.digest) &&
    candidate.gates.length === 3 &&
    candidate.gates.every((g) => g.status === "passed")
  );
}
