/** Keep the public website independent of sign-in while preserving older callback links. */
export function publicWebsite(pathname: string, search: string): boolean {
  if (pathname !== "/") return false;
  const query = new URLSearchParams(search);
  return !["invite", "workspace", "github_connected", "auth_error"].some(
    (key) => query.has(key),
  );
}

/** The local launcher remains usable even when the deployment has a hosted relay. */
export function localStudioLauncher(pathname: string): boolean {
  return pathname === "/local" || pathname === "/local/";
}
