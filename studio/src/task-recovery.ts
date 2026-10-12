/**
 * Plain-language recovery guidance for a stopped task. Guidance only: it names
 * which existing action applies and never offers an operation of its own.
 */
export type RecoveryCategory =
  | "environment"
  | "provider_permission"
  | "provider_quota"
  | "rejected_review"
  | "failed_checks"
  | "destination_conflict"
  | "interrupted"
  | "configuration"
  | "runtime";

export type RecoveryRead = {
  category: string | null;
  message?: string;
  actions?: { id: string; label: string; detail: string }[];
};

export type RecoveryGuidance = {
  title: string;
  explanation: string;
  next: string;
};

const KNOWN: RecoveryCategory[] = [
  "environment",
  "provider_permission",
  "provider_quota",
  "rejected_review",
  "failed_checks",
  "destination_conflict",
  "interrupted",
  "configuration",
  "runtime",
];

export function recoveryCategory(value: unknown): RecoveryCategory {
  return KNOWN.includes(value as RecoveryCategory)
    ? (value as RecoveryCategory)
    : "runtime";
}

export function recoveryGuidance(
  category: RecoveryCategory,
  context: {
    resumable: boolean;
    candidate: boolean;
    machine?: string;
    canAct?: boolean;
  },
): RecoveryGuidance {
  const guidance = categoryGuidance(category, context);
  if (context.canAct !== false) return guidance;
  return {
    ...guidance,
    next: `A developer on this project can act: ${guidance.next.charAt(0).toLowerCase()}${guidance.next.slice(1)}`,
  };
}

function categoryGuidance(
  category: RecoveryCategory,
  context: { resumable: boolean; candidate: boolean; machine?: string },
): RecoveryGuidance {
  const where = context.machine ? `on ${context.machine}` : "on the machine";
  const fresh = "start a new task from the current project";
  const revise = context.candidate
    ? "Request a revision of the saved candidate, or " + fresh
    : "Start a new task from the current project";
  switch (category) {
    case "provider_permission":
      return {
        title: "An agent could not sign in or was denied access",
        explanation:
          "A provider CLI reported missing sign-in, a permission denial or a sandbox refusal.",
        next: context.resumable
          ? `Sign in to the provider ${where}, then resume the task.`
          : `Sign in to the provider ${where}, then ${fresh}.`,
      };
    case "provider_quota":
      return {
        title: "An agent ran out of provider capacity",
        explanation:
          "A provider reported its plan or account quota was used up. Parallax stopped instead of retrying work that could not succeed until capacity returns.",
        next: context.resumable
          ? `Wait for the provider to restore capacity, or sign in another independent provider ${where}, then resume the task. Time already used stays recorded.`
          : `Wait for the provider to restore capacity, or sign in another independent provider ${where}, then ${fresh}.`,
      };
    case "environment":
      return {
        title: "The project environment could not be prepared",
        explanation:
          "Dependencies, the toolchain or a required check command were unavailable in the isolated copy.",
        next: `Fix the project setup ${where}, check readiness in the composer, then ${fresh}.`,
      };
    case "failed_checks":
      return {
        title: "Required checks did not pass",
        explanation:
          "The candidate's final checks failed or could not complete. Required checks are never relaxed to let work through.",
        next: `${revise}. The failing output is in Checks.`,
      };
    case "rejected_review":
      return {
        title: "The independent review rejected the candidate",
        explanation:
          "The reviewer recorded findings that the candidate did not resolve.",
        next: `${revise}. The findings are in Reviews.`,
      };
    case "destination_conflict":
      return {
        title: "The project changed while work was running",
        explanation:
          "Files in the destination changed after the baseline was captured, so the result cannot be applied safely.",
        next: `Inspect the retained diff, then ${fresh}.`,
      };
    case "interrupted":
      return {
        title: "Execution was interrupted",
        explanation:
          "The runtime or machine stopped before the task finished. Saved processes and partial work were kept.",
        next: context.resumable
          ? "Resume the task. Parallax reconciles saved work before continuing."
          : `This execution cannot resume. ${fresh.charAt(0).toUpperCase() + fresh.slice(1)}.`,
      };
    case "configuration":
      return {
        title: "A limit or setting stopped the task",
        explanation:
          "An execution budget, model or effort setting prevented the task from continuing.",
        next: `Adjust the limits or settings and ${fresh}. Time already used stays recorded.`,
      };
    default:
      return {
        title: "The task stopped unexpectedly",
        explanation:
          "The runtime recorded an error it could not classify further.",
        next: context.resumable
          ? "Inspect the activity log, then resume the task."
          : `Inspect the activity log, then ${fresh}.`,
      };
  }
}

/** "12 of 45 minutes used", or null when either side is unrecorded. */
export function budgetUsed(
  runtimeSeconds: unknown,
  limitMinutes: unknown,
): string | null {
  if (
    typeof runtimeSeconds !== "number" ||
    !Number.isFinite(runtimeSeconds) ||
    runtimeSeconds < 0 ||
    typeof limitMinutes !== "number" ||
    !Number.isFinite(limitMinutes) ||
    limitMinutes <= 0
  )
    return null;
  const used = Math.ceil(runtimeSeconds / 60);
  return `${used} of ${limitMinutes} minute${limitMinutes === 1 ? "" : "s"} used`;
}
