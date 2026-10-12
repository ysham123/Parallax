import "./dialogs.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { relayApi, messageOf } from "./api";
import { CopyBlock, PairingCode } from "./Onboarding";
import { WorkerSetupGuide } from "./WorkerSetupGuide";
import {
  HOSTED_EXECUTOR,
  platformLabel,
  workerCommands,
  type ExecutionMachine,
} from "./session";

export type { ExecutionMachine } from "./session";

export function ExecutionMachines({
  machines,
  selected,
  onSelect,
  refresh,
  hostedExecution,
  reconnectSignal = 0,
  teamWorkspace = false,
  canManageMachines = true,
}: {
  machines: ExecutionMachine[];
  selected: string;
  onSelect: (id: string) => void;
  refresh: () => Promise<void>;
  hostedExecution: boolean;
  reconnectSignal?: number;
  teamWorkspace?: boolean;
  canManageMachines?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const close = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const reconnectRegion = useRef<HTMLElement | null>(null);
  const reconnectFocus = useRef(false);
  const reconnectRef = useCallback((node: HTMLElement | null) => {
    if (!node && reconnectRegion.current?.contains(document.activeElement))
      reconnectFocus.current = true;
    reconnectRegion.current = node;
  }, []);
  useEffect(() => {
    if (reconnectSignal) {
      setError("");
      setOpen(true);
    }
  }, [reconnectSignal]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement;
    close.current?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
      }
      if (event.key === "Tab") {
        const items = Array.from(
          dialog.current?.querySelectorAll<HTMLElement>(
            "button:not([disabled]), select, summary, a[href]",
          ) || [],
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
      setConfirming(null);
      previous?.focus();
    };
  }, [open]);
  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      await relayApi("/executors/" + encodeURIComponent(id), {
        method: "DELETE",
      });
      setConfirming(null);
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }
  const current = machines.find((m) => m.id === selected);
  useEffect(() => {
    const active = document.activeElement;
    if (
      open &&
      reconnectFocus.current &&
      (!active || active === document.body || active.isConnected === false)
    )
      close.current?.focus();
    reconnectFocus.current = false;
  }, [open, current?.id, current?.online]);
  const command = workerCommands(location.origin).start;
  return (
    <>
      <label className="execution-picker">
        <span className="sr-only">Execution machine</span>
        <select
          aria-label="Execution machine"
          value={selected}
          onChange={(e) => onSelect(e.target.value)}
        >
          {hostedExecution && <option value={HOSTED_EXECUTOR}>Railway</option>}
          {machines.map((machine) => (
            <option key={machine.id} value={machine.id}>
              {machine.name}
              {machine.online ? "" : " · Offline"}
            </option>
          ))}
          {selected !== HOSTED_EXECUTOR && !current && (
            <option value={selected}>Machine unavailable</option>
          )}
        </select>
      </label>
      <button
        className="work-button"
        onClick={() => {
          setError("");
          setOpen(true);
        }}
      >
        Machines
      </button>
      {open && (
        <div
          className="machine-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            className="machine-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="machines-title"
            ref={dialog}
          >
            <header>
              <div>
                <h2 id="machines-title">Your machines</h2>
              </div>
              <button
                ref={close}
                aria-label="Close machines"
                className="icon-button"
                onClick={() => setOpen(false)}
              >
                ✕
              </button>
            </header>
            <p>
              Studio controls the run. The chosen machine owns project files,
              CLI sign-ins, checks, and integration.
            </p>
            {current && !current.online && (
              <section className="pair-machine" ref={reconnectRef}>
                <h3>Reconnect {current.name}</h3>
                <p>
                  {canManageMachines
                    ? "On that machine, restart"
                    : "Ask a workspace owner to restart"}{" "}
                  the Parallax worker with its original state directory, relay
                  URL and approved project paths. An existing pairing reconnects
                  without a new code. Keep that terminal process running, then
                  check the connection here.
                </p>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => {
                    setError("");
                    void refresh().catch((failure) =>
                      setError(messageOf(failure)),
                    );
                  }}
                >
                  Check machine connection
                </button>
              </section>
            )}
            <div className="machine-list">
              {hostedExecution && (
                <article>
                  <div>
                    <strong>Railway</strong>
                    <small>
                      Hosted projects and CLI connections · operator only
                    </small>
                  </div>
                  <span>Cloud</span>
                </article>
              )}
              {machines.map((machine) => (
                <article key={machine.id}>
                  <div>
                    <strong>{machine.name}</strong>
                    <small>
                      {platformLabel(machine.platform)} ·{" "}
                      {machine.online ? "Connected" : "Offline"}
                    </small>
                    {machine.transport_status?.status ===
                      "local_evidence_only" && (
                      <p className="machine-confirm">
                        Full evidence is retained locally. Some evidence exceeds
                        the relay limit and is unavailable in remote Studio;
                        affected candidates cannot receive remote approval.
                      </p>
                    )}
                    <details>
                      <summary>
                        {machine.workspaces.length} approved project
                        {machine.workspaces.length === 1 ? "" : "s"}
                      </summary>
                      {machine.workspaces.map((path) => (
                        <code key={path}>{path}</code>
                      ))}
                    </details>
                    {confirming === machine.id && (
                      <p className="machine-confirm" role="alert">
                        Disconnecting revokes this machine and deletes its
                        mirrored code and full evidence from Parallax. Read-only
                        receipts remain visible to permitted workspace members;
                        local history stays on the machine.
                      </p>
                    )}
                  </div>
                  {canManageMachines &&
                    (confirming === machine.id ? (
                      <span className="machine-confirm-actions">
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() => setConfirming(null)}
                        >
                          Keep
                        </button>
                        <button
                          className="danger-button"
                          disabled={busy}
                          onClick={() => void revoke(machine.id)}
                        >
                          {busy ? "Disconnecting…" : "Disconnect"}
                        </button>
                      </span>
                    ) : (
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => setConfirming(machine.id)}
                      >
                        Disconnect
                      </button>
                    ))}
                </article>
              ))}
              {!machines.length && !hostedExecution && (
                <article>
                  <div>
                    <strong>No machines yet</strong>
                    <small>
                      {canManageMachines
                        ? "Pair one below to start a run."
                        : "Ask a workspace owner to connect a machine."}
                    </small>
                  </div>
                </article>
              )}
            </div>
            {canManageMachines ? (
              <section className="pair-machine">
                <h3>Connect another machine</h3>
                <WorkerSetupGuide
                  headingLevel={3}
                  command={<CopyBlock label="Worker command" text={command} />}
                  pairing={<PairingCode />}
                  access={
                    hostedExecution
                      ? "Anyone signed in to the operator workspace can operate its approved projects."
                      : teamWorkspace
                        ? "Members' access follows their role and project permissions."
                        : "Only your account can see or operate this workspace's machines."
                  }
                />
              </section>
            ) : (
              <p>Workspace owners manage machine pairing and disconnection.</p>
            )}
            {error && (
              <p role="alert" className="machine-error">
                {error}
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
