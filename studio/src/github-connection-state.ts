export type GitHubIdentity = { actor: string; workspace: string };
export type GitHubProject = {
  worker: string;
  path: string;
  machineName: string;
};
type ReturnTarget = {
  identity: GitHubIdentity;
  target: GitHubProject;
  expires: number;
};
const key = "parallax-github-connection-return";

// Navigation context only. Fresh server permission is required before any action.
export function rememberGitHubReturn(
  identity: GitHubIdentity,
  target: GitHubProject,
) {
  try {
    window.sessionStorage.setItem(
      key,
      JSON.stringify({
        identity,
        target,
        expires: Date.now() + 15 * 60 * 1000,
      }),
    );
    return true;
  } catch {
    return false;
  }
}
export function githubReturn(identity: {
  actor?: string;
  workspace: string;
}): ReturnTarget | null {
  try {
    const value = JSON.parse(
      window.sessionStorage.getItem(key) || "null",
    ) as ReturnTarget | null;
    if (
      !value ||
      typeof value.expires !== "number" ||
      !Number.isFinite(value.expires) ||
      value.expires < Date.now() ||
      value.expires > Date.now() + 15 * 60 * 1000 ||
      value.identity.actor !== identity.actor ||
      value.identity.workspace !== identity.workspace ||
      typeof value.target.worker !== "string" ||
      typeof value.target.path !== "string" ||
      typeof value.target.machineName !== "string"
    )
      return null;
    return value;
  } catch {
    return null;
  }
}
export function clearGitHubReturn() {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    /* Optional navigation context. */
  }
}
