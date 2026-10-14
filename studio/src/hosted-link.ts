/** Only navigate to the runtime's authenticated loopback launch URL. */
export function localStudioUrl(input: string): string {
  let url: URL;
  try {
    url = new URL(input.trim());
  } catch {
    throw new Error("Paste the full Studio URL returned by Parallax.");
  }
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.hash
  ) {
    throw new Error(
      "Use a local Studio URL beginning with http://127.0.0.1 or http://localhost.",
    );
  }
  const token = url.searchParams.get("token");
  if (
    !token ||
    token.length > 512 ||
    url.searchParams.getAll("token").length !== 1
  ) {
    throw new Error(
      "This URL needs a session token. Ask Parallax to open Studio again for a fresh link.",
    );
  }
  if (url.href.length > 8192)
    throw new Error("This Studio URL is too long. Request a fresh link.");
  return url.href;
}
