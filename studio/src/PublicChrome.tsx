import { useEffect, useRef, useState } from "react";
import { initials, type Session } from "./session";

export function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden="true">
      <ellipse
        cx="20"
        cy="20"
        rx="17"
        ry="8"
        transform="rotate(-42 20 20)"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
      />
      <circle cx="20" cy="20" r="4" fill="currentColor" />
    </svg>
  );
}

function storedTheme(): string {
  try {
    return localStorage.getItem("parallax-theme") || "dark";
  } catch {
    return "dark";
  }
}

/** Applies the theme Studio uses, so the public pages and the workspace always match. */
export function applyStoredTheme() {
  document.documentElement.dataset.theme = storedTheme();
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(storedTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("parallax-theme", theme);
    } catch {
      /* Theme still applies for this tab. */
    }
  }, [theme]);
  const light = theme === "light";
  return (
    <button
      type="button"
      className="pub-icon-button"
      aria-label={light ? "Use dark theme" : "Use light theme"}
      title={light ? "Dark theme" : "Light theme"}
      onClick={() => setTheme(light ? "dark" : "light")}
    >
      {light ? (
        <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
          <path fill="currentColor" d="M6.2 1.3a6.8 6.8 0 1 0 8.5 8.5A5.6 5.6 0 0 1 6.2 1.3Z" />
        </svg>
      ) : (
        <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9 13 13M3 13l1.1-1.1M11.9 4.1 13 3" />
        </svg>
      )}
    </button>
  );
}

export function AccountMenu({
  session,
  onSignOut,
  onDelete,
}: {
  session: Session;
  onSignOut: () => Promise<void>;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") {
          setOpen(false);
          trigger.current?.focus();
        }
        return;
      }
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    root.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const label = session.account ? `@${session.account.login}` : "Operator";
  const github = session.auth === "github";
  const operatorWorkspace = session.workspace.kind === "operator";
  return (
    <div className="account-menu" ref={root}>
      <button
        ref={trigger}
        type="button"
        className="account-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="account-initials" aria-hidden="true">
          {initials(session)}
        </span>
        <span className="account-label">{label}</span>
      </button>
      {open && (
        <div className="account-popover" role="menu" aria-label="Account">
          <div className="account-summary">
            <strong>{session.account?.name || label}</strong>
            <small>
              {operatorWorkspace ? "Operator workspace" : "Personal workspace"}
              {github ? ` · ${label}` : " · access key"}
            </small>
          </div>
          <button
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onSignOut();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Signing out…" : "Sign out"}
          </button>
          {github && !operatorWorkspace && (
            <button
              type="button"
              role="menuitem"
              className="danger"
              onClick={() => {
                setOpen(false);
                onDelete();
              }}
            >
              Delete account…
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function DeleteAccountDialog({
  login,
  onCancel,
  onConfirm,
}: {
  login: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    input.current?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCancel();
      }
      if (event.key === "Tab") {
        const items = Array.from(
          dialog.current?.querySelectorAll<HTMLElement>("button:not([disabled]), input") || [],
        );
        const first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", keys, true);
    return () => {
      document.removeEventListener("keydown", keys, true);
      previous?.focus();
    };
  }, [onCancel]);
  return (
    <div
      className="machine-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <div
        className="machine-dialog account-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-title"
        aria-describedby="delete-description"
        ref={dialog}
      >
        <h2 id="delete-title">Delete your account?</h2>
        <p id="delete-description">
          This removes your workspace, disconnects every machine, and deletes mirrored run evidence
          from Parallax. Project files and local history on your machines are not touched. GitHub
          keeps its record of the authorization until you revoke it in your GitHub settings.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await onConfirm();
            } catch (problem) {
              setError(problem instanceof Error ? problem.message : String(problem));
              setBusy(false);
            }
          }}
        >
          <label htmlFor="confirm-login">
            Type <strong>{login}</strong> to confirm
          </label>
          <input
            id="confirm-login"
            ref={input}
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          {error && (
            <p role="alert" className="machine-error">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <button type="button" className="work-button" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="danger-button" disabled={busy || typed !== login}>
              {busy ? "Deleting…" : "Delete account"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
