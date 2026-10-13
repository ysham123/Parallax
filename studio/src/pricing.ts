/**
 * Public pricing comes only from the build-time PARALLAX_PRICING setting.
 * Without a valid setting the homepage shows no pricing at all, so no price is
 * ever published by default.
 */
export type Pricing = {
  freeTasks: number;
  monthly: string;
  yearly?: string;
  checkoutUrl: string;
  founding?: string;
};

const PRICE = /^[$€£]\d{1,5}(?:\.\d{2})?$/;

export function parsePricing(raw: unknown): Pricing | null {
  let value: unknown = raw;
  if (typeof raw === "string") {
    if (!raw.trim()) return null;
    try {
      value = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  const freeTasks = v.freeTasks;
  if (!Number.isInteger(freeTasks) || (freeTasks as number) < 1 || (freeTasks as number) > 1000) return null;
  if (typeof v.monthly !== "string" || !PRICE.test(v.monthly)) return null;
  if (v.yearly !== undefined && (typeof v.yearly !== "string" || !PRICE.test(v.yearly))) return null;
  if (typeof v.checkoutUrl !== "string") return null;
  try {
    if (new URL(v.checkoutUrl).protocol !== "https:") return null;
  } catch {
    return null;
  }
  if (v.founding !== undefined && (typeof v.founding !== "string" || !v.founding.trim() || v.founding.length > 160)) return null;
  return {
    freeTasks: freeTasks as number,
    monthly: v.monthly,
    ...(v.yearly ? { yearly: v.yearly as string } : {}),
    checkoutUrl: v.checkoutUrl,
    ...(v.founding ? { founding: (v.founding as string).trim() } : {}),
  };
}
