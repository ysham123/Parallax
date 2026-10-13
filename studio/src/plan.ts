export type PlanStatus = {
  licensing: boolean;
  plan: "unlimited" | "free" | "pro";
  used: number;
  limit: number | null;
  resets_at?: string;
  key_hint?: string | null;
  upgrade_url?: string;
};

/** Plain-language plan line for Settings. Usage counts new tasks only. */
export function planSummary(status: PlanStatus): {
  title: string;
  detail: string;
} {
  const tasks = (n: number) => `${n} ${n === 1 ? "task" : "tasks"}`;
  if (status.plan === "pro")
    return {
      title: "Pro plan",
      detail: `Unlimited tasks.${status.key_hint ? ` License key ${status.key_hint}.` : ""} ${tasks(status.used)} started this month.`,
    };
  if (status.plan === "unlimited")
    return { title: "Unlimited", detail: "This build has no plan limits." };
  const limit = status.limit ?? 0;
  const left = Math.max(0, limit - status.used);
  const reset =
    status.resets_at && Number.isFinite(Date.parse(status.resets_at))
      ? // The allowance resets at 00:00 UTC; a local date can show the day before.
        new Date(status.resets_at).toLocaleDateString([], {
          month: "long",
          day: "numeric",
          timeZone: "UTC",
        })
      : "next month";
  return {
    title: "Free plan",
    detail:
      left > 0
        ? `${tasks(status.used)} of ${limit} used this month; ${left} left. Resets ${reset}. Retries, recovery, approval and delivery never count.`
        : `All ${limit} free tasks are used this month. Existing tasks stay available; new tasks resume ${reset} or with Pro.`,
  };
}
