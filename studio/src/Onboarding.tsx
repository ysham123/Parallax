import { useEffect, useState, type ReactNode } from "react";
import { relayApi, messageOf } from "./api";
import { Mark, ThemeToggle } from "./PublicChrome";
import { PUBLIC_RELEASE, PREVIEW_GUIDES, SOURCE_INSTALL } from "./public-release";
import {
  platformLabel,
  workerCommands,
  type ExecutionMachine,
} from "./session";
import "./public.css";

export function CopyBlock({ label, text }: { label: string; text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <div className="onb-code">
      <pre aria-label={label}>
        <code>{text}</code>
      </pre>
      <button
        type="button"
        className="onb-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setState("copied");
          } catch {
            setState("failed");
          }
          window.setTimeout(() => setState("idle"), 2000);
        }}
      >
        {state === "copied" ? "Copied" : "Copy"}
      </button>
      <span className="sr-only" role="status">
        {state === "copied"
          ? `${label} copied`
          : state === "failed"
            ? "Copy failed. Select the text instead."
            : ""}
      </span>
    </div>
  );
}

export function PairingCode() {
  const [pair, setPair] = useState<{ code: string; expires: number } | null>(
    null,
  );
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!pair) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pair]);
  const remaining = pair
    ? Math.max(0, Math.ceil((pair.expires - now) / 1000))
    : 0;
  async function generate() {
    setBusy(true);
    setError("");
    try {
      const value = await relayApi<{ code: string; expires_in: number }>(
        "/executors/pair",
        {
          method: "POST",
        },
      );
      setPair({
        code: value.code,
        expires: Date.now() + value.expires_in * 1000,
      });
      setNow(Date.now());
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="onb-pair">
      {/* Announced once per state change; the ticking countdown and the code itself are not re-read. */}
      <span className="sr-only" role="status">
        {pair
          ? remaining > 0
            ? "Pairing code generated. It is valid for five minutes and works once."
            : "The pairing code expired."
          : ""}
      </span>
      {pair && remaining > 0 ? (
        <div className="onb-pair-code">
          <code>{pair.code}</code>
          <small aria-live="off">
            Expires in {Math.floor(remaining / 60)}:
            {String(remaining % 60).padStart(2, "0")} · works once
          </small>
        </div>
      ) : (
        pair && (
          <p className="onb-muted">That code expired. Generate a fresh one.</p>
        )
      )}
      <button
        type="button"
        className="pub-primary"
        onClick={() => void generate()}
        disabled={busy}
      >
        {busy
          ? "Generating…"
          : pair
            ? "Generate a new code"
            : "Generate pairing code"}
      </button>
      {error && (
        <p className="pub-alert" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default function Onboarding({
  workspaceName,
  machines,
  loading,
  canManageMachines = true,
  account,
  onOpen,
}: {
  workspaceName: string;
  machines: ExecutionMachine[];
  loading: boolean;
  canManageMachines?: boolean;
  account: ReactNode;
  onOpen: (id: string) => void;
}) {
  const commands = workerCommands(window.location.origin);
  const connected = machines.find((machine) => machine.online) || machines[0];
  return (
    <div className="pub-page onb-page">
      <a className="skip-link" href="#onboarding-main">
        Skip to content
      </a>
      <header className="pub-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark />
          Parallax
          <span className="pub-crumb">{workspaceName}</span>
        </a>
        <nav aria-label="Account">
          <ThemeToggle />
          {account}
        </nav>
      </header>
      <main id="onboarding-main" className="onb-main" tabIndex={-1}>
        <p className="pub-eyebrow">Your workspace</p>
        <h1>
          {canManageMachines
            ? "Connect a machine"
            : "Waiting for your team’s machine"}
        </h1>
        <p className="pub-lead">
          {canManageMachines
            ? "Agents run on a computer you control, using the CLIs you are already signed in to. Connect one to start your first run."
            : "Ask a workspace owner to connect a machine and grant you project access. Your permitted tasks and reviews appear here when it connects."}
        </p>
        {canManageMachines && (
          <ol className="onb-steps">
            <li>
              <h2>Use your supplied pilot worker</h2>
              <p>
                New Studio workflows and team tasks require the versioned
                development preview supplied by your pilot operator. Verify its
                archive digest, extract it into a new folder, and run the worker
                from that folder. Follow the{" "}
                <a href={PREVIEW_GUIDES.setup}>preview setup guide</a>.
              </p>
              <p className="onb-muted">
                If you have not received the preview, ask your operator for it
                before pairing. Public {PUBLIC_RELEASE.version} installation
                commands do not install this worker.
              </p>
            </li>
            <li>
              <h2>Check prerequisites</h2>
              <p>
                macOS or Linux with Python 3.10 or newer, Git 2.38 or newer, and
                two usable independent providers for Build: one to implement
                and another to review. Use supported signed-in CLIs or API
                connections; credentials stay on the machine. Linux also needs
                working bubblewrap and user namespaces. A detected sign-in does
                not establish remaining quota.
              </p>
              <p className="onb-muted">
                Native Grok is unavailable in the preview. Claude Code and
                Antigravity use restricted file tools, with shell and
                content-search tools disabled. Run diagnostics in the supplied
                preview before starting a task.
              </p>
            </li>
            <li>
              <h2>Start a worker for one project</h2>
              <CopyBlock label="Worker command" text={commands.start} />
              <p className="onb-muted">
                Use the absolute path of a Git repository you want agents to
                work in. Repeat
                <code>--workspace</code> to approve more. The first start
                prepares a private Python environment and then asks for a
                pairing code without echoing it.
              </p>
            </li>
            <li>
              <h2>Pair it</h2>
              <p>Generate a code and paste it at the worker’s prompt.</p>
              <PairingCode />
            </li>
          </ol>
        )}
        {canManageMachines && (
          <details className="onb-muted">
            <summary>Install the public local tools separately</summary>
            <p>
              These pinned {PUBLIC_RELEASE.version} commands are for the public
              local tools. For tasks in this workspace, use your supplied pilot
              worker above.
            </p>
            <CopyBlock label="Public local install commands" text={SOURCE_INSTALL} />
          </details>
        )}
        <section className="onb-status" aria-live="polite">
          {connected ? (
            <>
              <div>
                <span
                  className={`onb-dot ${connected.online ? "online" : ""}`}
                  aria-hidden="true"
                />
                <strong>{connected.name}</strong>
                <small>
                  {platformLabel(connected.platform)} ·{" "}
                  {connected.online ? "Connected" : "Offline"} ·{" "}
                  {connected.workspaces.length} approved project
                  {connected.workspaces.length === 1 ? "" : "s"}
                </small>
              </div>
              <button
                type="button"
                className="pub-primary"
                onClick={() => onOpen(connected.id)}
              >
                Open Studio
              </button>
            </>
          ) : (
            <div>
              <span className="onb-dot waiting" aria-hidden="true" />
              <strong>
                {loading
                  ? "Checking for machines…"
                  : "Waiting for a machine to connect"}
              </strong>
              <small>This page updates on its own once the worker pairs.</small>
            </div>
          )}
        </section>
        <p className="onb-muted onb-footnote">
          The worker connects outward over HTTPS. It opens no port and never
          uploads your provider credentials. Run results, diffs, check output,
          and events are mirrored to this workspace so Studio can draw the
          graph. Mirrored task prompts, agent output, session metadata and
          evidence can contain source code. Private checkouts and complete
          provider-session files stay on the machine. Keep the worker online to
          use Studio controls.
        </p>
      </main>
    </div>
  );
}
