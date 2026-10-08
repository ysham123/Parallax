/** Hosted session state and pure helpers shared by the public entry, onboarding, and Studio. */

export type Session = {
  ok: true;
  mode: "hosted" | "local";
  auth: "account" | "github" | "operator" | "local";
  account: {
    login: string;
    name: string | null;
    avatar_url: string | null;
    email?: string | null;
    provider?: string | null;
  } | null;
  workspace: {
    id: string;
    name: string;
    kind: "personal" | "operator";
    hosted_execution: boolean;
  };
};

export type AuthConfig = {
  github: boolean;
  /** Which service runs sign-in: Supabase (email, GitHub, Google) or the built-in GitHub app. */
  identity?: "supabase" | "github" | null;
  providers?: string[];
  signup: "open" | "allowlist" | "closed";
};

/** Sign-in methods a deployment offers, including runtimes that predate the providers list. */
export function signInMethods(config: AuthConfig | null): string[] {
  if (!config) return [];
  if (Array.isArray(config.providers)) return config.providers;
  return config.github ? ["github"] : [];
}

/** How a person is named in the account menu and asked to confirm deletion. */
export function accountName(account: NonNullable<Session["account"]>): string {
  return account.provider === "github" || !account.email ? `@${account.login}` : account.email;
}

/** What a person types to confirm deleting their account. */
export function deletionConfirmation(account: NonNullable<Session["account"]>): string {
  return account.email || account.login;
}

export type ExecutionMachine = {
  id: string;
  name: string;
  online: boolean;
  platform: string;
  workspaces: string[];
  last_seen: number;
};

export const HOSTED_EXECUTOR = "railway";
export const REPOSITORY = "https://github.com/ysham123/Parallax";

const SIGN_IN_ERRORS: Record<string, string> = {
  unavailable: "That sign-in method is not available on this deployment yet.",
  denied: "Sign-in was cancelled. Nothing was created.",
  expired:
    "That sign-in expired or was opened in a different browser. Start again from this page.",
  failed: "Sign-in could not be confirmed. Try again in a moment.",
  closed: "This deployment is not accepting new accounts right now.",
  not_invited: "This deployment is invite only, and this account is not on the list.",
  capacity: "This deployment has reached its account limit.",
  busy: "Too many attempts. Wait a few minutes and try again.",
  disabled: "This account has been disabled by the deployment operator.",
  credentials: "That email and password don't match an account.",
  unconfirmed: "Confirm your email first. Check your inbox for the link we sent.",
  weak_password: "Use a password of at least 10 characters.",
  invalid_email: "Enter a valid email address.",
  link_expired: "That link has expired or was already used. Request a new one.",
};

/** Read a sign-in error code from the callback redirect, ignoring anything unrecognized. */
export function signInError(search: string): string | null {
  const code = new URLSearchParams(search).get("auth_error");
  return code && Object.prototype.hasOwnProperty.call(SIGN_IN_ERRORS, code) ? code : null;
}

export function signInErrorMessage(code: string): string {
  return Object.prototype.hasOwnProperty.call(SIGN_IN_ERRORS, code)
    ? SIGN_IN_ERRORS[code]
    : SIGN_IN_ERRORS.failed;
}

/** Machine choices are remembered per workspace so one account never inherits another's selection. */
export function executorKey(workspace: string): string {
  return `parallax-executor:${workspace}`;
}

export function chooseMachine(
  machines: ExecutionMachine[],
  stored: string | null,
  hostedExecution: boolean,
): string | null {
  if (stored === HOSTED_EXECUTOR && hostedExecution) return HOSTED_EXECUTOR;
  if (stored && machines.some((machine) => machine.id === stored)) return stored;
  const online = machines.find((machine) => machine.online);
  if (online) return online.id;
  // The operator's hosted runtime is always reachable; prefer it over an offline machine.
  if (hostedExecution) return HOSTED_EXECUTOR;
  return machines.length ? machines[0].id : null;
}

/** The previous release stored one unscoped choice; only the operator workspace may inherit it. */
export function storedMachine(workspace: string): string | null {
  return (
    readStored(executorKey(workspace)) ??
    (workspace === "owner" ? readStored("parallax-executor") : null)
  );
}

export function platformLabel(platform: string): string {
  if (platform === "darwin") return "macOS";
  if (platform === "linux") return "Linux";
  return platform;
}

export function initials(session: Session): string {
  const source = session.account?.name || session.account?.email || session.account?.login || "Operator";
  const parts = source.trim().split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : source.slice(0, 2);
  return letters.toUpperCase();
}

export function workerCommands(origin: string): { install: string; start: string } {
  return {
    install: `git clone ${REPOSITORY}.git\ncd Parallax`,
    start: [
      "python3 scripts/parallax.py worker \\",
      `  --url ${origin} \\`,
      "  --workspace /absolute/path/to/project \\",
      '  --name "My Mac"',
    ].join("\n"),
  };
}

/** Storage can be unavailable (private windows, blocked site data); selection then lasts for the tab only. */
export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* Selection still applies for this tab. */
  }
}

/** Remove remembered machine choices for every workspace on sign-out or account deletion. */
export function forgetMachines(): void {
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key && (key.startsWith("parallax-executor:") || key === "parallax-executor"))
        keys.push(key);
    }
    keys.forEach((key) => window.localStorage.removeItem(key));
  } catch {
    /* Nothing stored. */
  }
}
