/** Callback destinations come only from the runtime's Supabase response. */
export function oauthDestination(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length > 4096 ||
    /[\x00-\x20\\]/.test(value)
  )
    throw new Error("Invalid callback");
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.hash ||
    !(
      url.protocol === "https:" ||
      (url.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))
    )
  )
    throw new Error("Invalid callback");
  return url.href;
}

export function consentIdentifier(search: string): string | null {
  const values = new URLSearchParams(search).getAll("authorization_id");
  return values.length === 1 &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      values[0],
    )
    ? values[0]
    : null;
}
