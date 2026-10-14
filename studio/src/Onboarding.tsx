import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { relayApi, messageOf } from "./api";
import { Mark, ThemeToggle } from "./PublicChrome";
import { WorkerSetupGuide } from "./WorkerSetupGuide";
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
      <pre aria-label={label} tabIndex={0}>
        <code>{text}</code>
      </pre>
      <button
        type="button"
        className="onb-copy"
        onClick={async () => {
          setState("idle");
          try {
            await navigator.clipboard.writeText(text);
            setState("copied");
            window.setTimeout(() => setState("idle"), 2000);
          } catch {
            setState("failed");
          }
        }}
      >
        {state === "copied"
          ? "Copied"
          : state === "failed"
            ? "Retry copy"
            : "Copy"}
      </button>
      <span
        className={state === "failed" ? "onb-copy-status" : "sr-only"}
        role="status"
      >
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
  const generateButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const inflight = useRef(false);
  useEffect(() => {
    if (busy) {
      const moved = (event: FocusEvent) => {
        if (
          event.target !== generateButton.current &&
          event.target !== document.body
        )
          restoreFocus.current = false;
      };
      document.addEventListener("focusin", moved);
      return () => document.removeEventListener("focusin", moved);
    }
    const active = document.activeElement;
    if (
      restoreFocus.current &&
      generateButton.current &&
      (!active ||
        active === document.body ||
        active === generateButton.current ||
        active.isConnected === false)
    )
      generateButton.current.focus();
    restoreFocus.current = false;
  }, [busy]);
  useEffect(
    () => () => {
      restoreFocus.current = false;
    },
    [],
  );
  useEffect(() => {
    if (!pair) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pair]);
  const remaining = pair
    ? Math.max(0, Math.ceil((pair.expires - now) / 1000))
    : 0;
  async function generate() {
    if (inflight.current) return;
    inflight.current = true;
    restoreFocus.current = document.activeElement === generateButton.current;
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
      inflight.current = false;
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
        ref={generateButton}
        type="button"
        className="pub-primary"
        onClick={() => void generate()}
        aria-disabled={busy}
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
  const setupRegion = useRef<HTMLDivElement | null>(null);
  const transferFocus = useRef(false);
  const openStudio = useRef<HTMLButtonElement>(null);
  const setupRef = useCallback((node: HTMLDivElement | null) => {
    if (!node && setupRegion.current?.contains(document.activeElement))
      transferFocus.current = true;
    setupRegion.current = node;
  }, []);
  useEffect(() => {
    if (connected && transferFocus.current) {
      openStudio.current?.focus();
      transferFocus.current = false;
    }
  }, [connected?.id]);
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
          {connected
            ? connected.online
              ? "Your machine is connected"
              : "Reconnect your machine"
            : canManageMachines
              ? "Connect a machine"
              : "Waiting for your team’s machine"}
        </h1>
        <p className="pub-lead">
          {connected
            ? connected.online
              ? canManageMachines
                ? "Open Studio to choose an authorized project, inspect your provider and check setup, then start a task. A connected machine does not establish provider quota or task readiness."
                : "Open Studio to inspect your permitted tasks and reviews. Access follows your role and project permissions; connection alone does not establish task readiness."
              : canManageMachines
                ? "Open Studio to reconnect this machine using its existing worker state. Your saved work remains tied to this machine."
                : "Open Studio to check the connection. Ask a workspace Owner to restart this machine's worker with its existing state."
            : canManageMachines
              ? "Agents run on a computer you control, using supported local CLIs or API connections. Connect an existing project to this workspace."
              : "Ask a workspace owner to connect a machine and grant you project access. Your permitted tasks and reviews appear here when it connects."}
        </p>
        {canManageMachines && !connected && (
          <div ref={setupRef}>
            <WorkerSetupGuide
              command={
                <CopyBlock label="Worker command" text={commands.start} />
              }
              pairing={<PairingCode />}
              access="Access follows this workspace's membership and project permissions."
            />
          </div>
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
                ref={openStudio}
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
        {(connected || !canManageMachines) && (
          <p className="onb-muted onb-footnote">
            Execution and provider credentials stay on the machine. This
            workspace receives task evidence that can contain source code, under
            your role and project permissions. Chosen model providers receive
            relevant project context when tasks run. Keep the worker online to
            use Studio and inspect team tasks.
          </p>
        )}
      </main>
    </div>
  );
}
