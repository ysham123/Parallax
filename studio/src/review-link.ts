/**
 * Review handoff links carry navigation identifiers only: workspace, machine and
 * task. They hold no token, path or source. Opening one never approves or runs
 * anything; every read still goes through the relay's current authorization.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ReviewTarget = { workspace: string; worker: string; task: string };
export type ReviewSpace = {
  id: string;
  name: string;
  kind: string;
  role: string;
};

export function parseReviewTarget(hash: string): ReviewTarget | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get("review");
  if (!value) return null;
  const parts = value.split(".");
  if (parts.length !== 3 || !parts.every((part) => UUID.test(part)))
    return null;
  const [workspace, worker, task] = parts.map((part) => part.toLowerCase());
  return { workspace, worker, task };
}

export function reviewLink(
  origin: string,
  target: ReviewTarget,
): string | null {
  if (
    ![target.workspace, target.worker, target.task].every((part) =>
      UUID.test(part),
    )
  )
    return null;
  let base: URL;
  try {
    base = new URL(origin);
  } catch {
    return null;
  }
  if (!["https:", "http:"].includes(base.protocol)) return null;
  return `${base.origin}/studio#review=${target.workspace}.${target.worker}.${target.task}`;
}

export type ReviewEntry =
  | { kind: "checking" }
  | { kind: "switch"; space: ReviewSpace }
  | { kind: "unavailable"; reason: "workspace" | "machine" }
  | { kind: "open"; worker: string; task: string };

/**
 * Decides the next step for a review link. Membership comes from the signed-in
 * account's own workspace list and machines from the current workspace's
 * authorized machine list, so nothing here grants access by itself.
 */
export function resolveReviewEntry(
  target: ReviewTarget,
  currentWorkspace: string,
  spaces: ReviewSpace[] | null,
  machines: { id: string }[] | null,
): ReviewEntry {
  if (currentWorkspace.toLowerCase() !== target.workspace) {
    if (spaces === null) return { kind: "checking" };
    const space = spaces.find(
      (item) => item.id.toLowerCase() === target.workspace,
    );
    return space
      ? { kind: "switch", space }
      : { kind: "unavailable", reason: "workspace" };
  }
  if (machines === null) return { kind: "checking" };
  const machine = machines.find(
    (item) => item.id.toLowerCase() === target.worker,
  );
  return machine
    ? { kind: "open", worker: machine.id, task: target.task }
    : { kind: "unavailable", reason: "machine" };
}

export type ReviewPreview = {
  workspace: { id: string; name: string; kind: string; role: string };
  worker: { id: string; name: string; online: boolean };
  workflow: { id: string; title: string | null; status: string | null };
};

/** Accepts a server preview only when it describes exactly the linked target. */
export function matchingPreview(
  target: ReviewTarget,
  value: unknown,
): ReviewPreview | null {
  if (!value || typeof value !== "object") return null;
  const preview = value as Partial<ReviewPreview> & { capability?: unknown };
  if (preview.capability !== "review-target-v1") return null;
  const { workspace, worker, workflow } = preview;
  if (
    !workspace ||
    !worker ||
    !workflow ||
    typeof workspace.id !== "string" ||
    typeof worker.id !== "string" ||
    typeof workflow.id !== "string" ||
    workspace.id.toLowerCase() !== target.workspace ||
    worker.id.toLowerCase() !== target.worker ||
    workflow.id.toLowerCase() !== target.task ||
    typeof workspace.name !== "string" ||
    typeof worker.name !== "string"
  )
    return null;
  return {
    workspace: {
      id: workspace.id,
      name: workspace.name,
      kind: String(workspace.kind || ""),
      role: String(workspace.role || ""),
    },
    worker: {
      id: worker.id,
      name: worker.name,
      online: worker.online === true,
    },
    workflow: {
      id: workflow.id,
      title: typeof workflow.title === "string" ? workflow.title : null,
      status: typeof workflow.status === "string" ? workflow.status : null,
    },
  };
}
