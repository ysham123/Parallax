/** Keep the public website independent of sign-in while preserving older callback links. */
export function publicWebsite(pathname: string, search: string): boolean {
  if (pathname !== "/") return false;
  const query = new URLSearchParams(search);
  return !["invite", "workspace", "github_connected", "auth_error"].some(
    (key) => query.has(key),
  );
}
