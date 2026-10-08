import { useEffect, useRef, useState } from "react";
import { relayApi, messageOf } from "./api";
import { PairingCode } from "./Onboarding";
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
}: {
  machines: ExecutionMachine[];
  selected: string;
  onSelect: (id: string) => void;
  refresh: () => Promise<void>;
  hostedExecution: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const close = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
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
      {selected !== HOSTED_EXECUTOR && !current?.online && (
        <span className="machine-offline" role="status">
          Offline · saved evidence
        </span>
      )}
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
                <span className="eyebrow">EXECUTION</span>
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
            <div className="machine-list">
              {hostedExecution && (
                <article>
                  <div>
                    <strong>Railway</strong>
                    <small>Hosted projects and CLI connections · operator only</small>
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
                        mirrored evidence from Parallax. Its local history
                        stays on the machine.
                      </p>
                    )}
                  </div>
                  {confirming === machine.id ? (
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
                  )}
                </article>
              ))}
              {!machines.length && !hostedExecution && (
                <article>
                  <div>
                    <strong>No machines yet</strong>
                    <small>Pair one below to start a run.</small>
                  </div>
                </article>
              )}
            </div>
            <section className="pair-machine">
              <h3>Connect another machine</h3>
              <p>
                From a Parallax checkout on that machine, run this with a
                project you approve. It connects outward over HTTPS; no inbound
                port is opened and provider credentials stay on the machine.
              </p>
              <pre className="machine-command">
                <code>{command}</code>
              </pre>
              <p>
                {hostedExecution
                  ? "Anyone signed in to the operator workspace can operate approved projects on its machines."
                  : "Only your account can see or operate machines in this workspace."}{" "}
                Disconnect revokes future commands; an offline machine receives
                the revocation when it reconnects.
              </p>
              <PairingCode />
            </section>
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
