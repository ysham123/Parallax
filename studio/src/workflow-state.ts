export const workflowLabels: Record<string, string> = {
  queued: "Queued",
  preparing: "Preparing candidate",
  awaiting_approval: "Awaiting approval",
  applying: "Applying approved change",
  applied: "Applied",
  rejected: "Candidate declined",
  cancelled: "Stopped",
  interrupted: "Ready to resume",
  needs_attention: "Needs attention",
  superseded: "Superseded by revision",
  approved: "Approved for delivery",
  published: "Draft PR published",
};
export function workflowGroup(
  status: string,
  decisionAction?: string,
): "approval" | "delivery" | "running" | "attention" | "finished" {
  if (status === "awaiting_approval") return "approval";
  if (
    status === "approved" ||
    (status === "needs_attention" && decisionAction === "approve")
  )
    return "delivery";
  if (["queued", "preparing", "applying"].includes(status)) return "running";
  if (["interrupted", "needs_attention"].includes(status)) return "attention";
  return "finished";
}
export function workflowStep(status: string): number {
  if (status === "applied" || status === "published") return 3;
  if (status === "rejected") return 1;
  if (status === "applying" || status === "approved") return 2;
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
    Array.isArray(candidate.gates) &&
    candidate.gates.length === 3 &&
    candidate.gates.every((g) => g.status === "passed")
  );
}

export type WorkflowAuthority = {
  actor: string;
  role: string;
  team: boolean;
  reviewers_by_project?: Record<string, string[]>;
};
export function workflowAccess(
  authority: WorkflowAuthority | null,
  paired: boolean,
) {
  // Older local runtimes have no account authority. Paired workers must report it
  // before any task or delivery control becomes available.
  if (!authority) return { deliver: !paired, review: !paired };
  return {
    deliver: ["owner", "developer"].includes(authority.role),
    review: ["owner", "developer", "reviewer"].includes(authority.role),
  };
}

export function workflowReviewAccess(
  authority: WorkflowAuthority | null,
  paired: boolean,
  teamWorkspace: boolean,
  schemaVersion?: string,
): boolean {
  if (!authority && teamWorkspace) return false;
  return (
    workflowAccess(authority, paired).review ||
    (!authority && !teamWorkspace && schemaVersion !== "2.0")
  );
}

// A queue projection is not authorization. Actual approval still binds the
// candidate digest, current evidence, online state and server-side permissions.
export function workflowInReviewInbox(
  workflow: {
    status: string;
    requester?: string;
    reviewer?: string;
    schema_version?: string;
  },
  authority: WorkflowAuthority | null,
  paired: boolean,
  teamWorkspace: boolean,
): boolean {
  if (
    workflow.status !== "awaiting_approval" ||
    !workflowReviewAccess(
      authority,
      paired,
      teamWorkspace,
      workflow.schema_version,
    )
  )
    return false;
  if (teamWorkspace || authority?.team)
    return (
      !!authority &&
      !!workflow.requester &&
      workflow.requester !== authority.actor &&
      (!workflow.reviewer || workflow.reviewer === authority.actor)
    );
  return true;
}

export function workflowCanResume(
  status: string,
  runStatus?: string,
  approved = false,
): boolean {
  return (
    !approved &&
    ["interrupted", "needs_attention"].includes(status) &&
    (!runStatus ||
      ["completed", "paused", "interrupted", "needs_attention"].includes(
        runStatus,
      ))
  );
}

const operationIds = new Map<string, string>();
export function githubBindingsForProject<
  T extends { project: string; worker?: string },
>(bindings: T[], project: string, worker?: string): T[] {
  return bindings.filter(
    (binding) =>
      binding.project === project && (!worker || binding.worker === worker),
  );
}

export function workflowOperationId(
  scope: string,
  action: string,
  digest: string,
): string {
  const key = `parallax-operation:${JSON.stringify([scope, action, digest])}`;
  const remembered = operationIds.get(key);
  if (remembered) return remembered;
  let saved: string | null = null;
  try {
    saved = window.sessionStorage.getItem(key);
  } catch {
    /* Use memory for this tab. */
  }
  const id =
    saved && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(saved)
      ? saved
      : crypto.randomUUID();
  operationIds.set(key, id);
  try {
    window.sessionStorage.setItem(key, id);
  } catch {
    /* A retry in this tab still reuses its ID. */
  }
  return id;
}
