import { useEffect, useState, type ReactNode } from "react";
import { relayApi, messageOf } from "./api";
import { Mark, ThemeToggle } from "./PublicChrome";
import { platformLabel, workerCommands, type ExecutionMachine } from "./session";
import "./public.css";

function CopyBlock({ label, text }: { label: string; text: string }) {
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
        {state === "copied" ? `${label} copied` : state === "failed" ? "Copy failed. Select the text instead." : ""}
      </span>
    </div>
  );
}

export function PairingCode() {
  const [pair, setPair] = useState<{ code: string; expires: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!pair) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pair]);
  const remaining = pair ? Math.max(0, Math.ceil((pair.expires - now) / 1000)) : 0;
  async function generate() {
    setBusy(true);
    setError("");
    try {
      const value = await relayApi<{ code: string; expires_in: number }>("/executors/pair", {
        method: "POST",
      });
      setPair({ code: value.code, expires: Date.now() + value.expires_in * 1000 });
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
        {pair ? (remaining > 0 ? "Pairing code generated. It is valid for five minutes and works once." : "The pairing code expired.") : ""}
      </span>
      {pair && remaining > 0 ? (
        <div className="onb-pair-code">
          <code>{pair.code}</code>
          <small aria-live="off">
            Expires in {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")} ·
            works once
          </small>
        </div>
      ) : (
        pair && <p className="onb-muted">That code expired. Generate a fresh one.</p>
      )}
      <button type="button" className="pub-primary" onClick={() => void generate()} disabled={busy}>
        {busy ? "Generating…" : pair ? "Generate a new code" : "Generate pairing code"}
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
  account,
  onOpen,
}: {
  workspaceName: string;
  machines: ExecutionMachine[];
  loading: boolean;
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
        <h1>Connect a machine</h1>
        <p className="pub-lead">
          Agents run on a computer you control, using the CLIs you are already signed in to. Connect
          one to start your first run.
        </p>
        <ol className="onb-steps">
          <li>
            <h2>Check prerequisites</h2>
            <p>
              macOS or Linux with Python 3.10 or newer, Git 2.38 or newer, and at least one signed-in
              CLI: <code>codex</code>, <code>claude</code>, <code>grok</code>, or <code>agy</code>.
              API keys work too and stay on that machine.
            </p>
          </li>
          <li>
            <h2>Get Parallax</h2>
            <CopyBlock label="Install commands" text={commands.install} />
          </li>
          <li>
            <h2>Start a worker for one project</h2>
            <CopyBlock label="Worker command" text={commands.start} />
            <p className="onb-muted">
              Use the absolute path of a Git repository you want agents to work in. Repeat
              <code>--workspace</code> to approve more. The first start prepares a private Python
              environment and then asks for a pairing code without echoing it.
            </p>
          </li>
          <li>
            <h2>Pair it</h2>
            <p>Generate a code and paste it at the worker’s prompt.</p>
            <PairingCode />
          </li>
        </ol>
        <section className="onb-status" aria-live="polite">
          {connected ? (
            <>
              <div>
                <span className={`onb-dot ${connected.online ? "online" : ""}`} aria-hidden="true" />
                <strong>{connected.name}</strong>
                <small>
                  {platformLabel(connected.platform)} · {connected.online ? "Connected" : "Offline"} ·{" "}
                  {connected.workspaces.length} approved project
                  {connected.workspaces.length === 1 ? "" : "s"}
                </small>
              </div>
              <button type="button" className="pub-primary" onClick={() => onOpen(connected.id)}>
                Open Studio
              </button>
            </>
          ) : (
            <div>
              <span className="onb-dot waiting" aria-hidden="true" />
              <strong>{loading ? "Checking for machines…" : "Waiting for a machine to connect"}</strong>
              <small>This page updates on its own once the worker pairs.</small>
            </div>
          )}
        </section>
        <p className="onb-muted onb-footnote">
          The worker connects outward over HTTPS. It opens no port and never uploads your provider
          credentials. Run results, diffs, check output, and events are mirrored to this workspace
          so Studio can draw the graph; project files stay on the machine.
        </p>
      </main>
    </div>
  );
}
