import { useEffect, useRef, useState } from "react";
import { relayApi, messageOf } from "./api";

export type ExecutionMachine = {
  id: string;
  name: string;
  online: boolean;
  platform: string;
  workspaces: string[];
  last_seen: number;
};

export function ExecutionMachines({
  machines,
  selected,
  onSelect,
  refresh,
}: {
  machines: ExecutionMachine[];
  selected: string;
  onSelect: (id: string) => void;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [pair, setPair] = useState<{ code: string; expires_in: number } | null>(
    null,
  );
  const [expires, setExpires] = useState(0);
  const [now, setNow] = useState(Date.now());
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
            "button:not([disabled]), select",
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
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      document.removeEventListener("keydown", keys, true);
      window.clearInterval(timer);
      previous?.focus();
    };
  }, [open]);
  async function createPair() {
    setBusy(true);
    setError("");
    try {
      const value = await relayApi<{ code: string; expires_in: number }>(
        "/executors/pair",
        { method: "POST" },
      );
      setPair(value);
      setExpires(Date.now() + value.expires_in * 1000);
      setNow(Date.now());
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      await relayApi("/executors/" + encodeURIComponent(id), {
        method: "DELETE",
      });
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }
  const current = machines.find((m) => m.id === selected);
  return (
    <>
      <label className="execution-picker">
        <span className="sr-only">Execution machine</span>
        <select
          aria-label="Execution machine"
          value={selected}
          onChange={(e) => onSelect(e.target.value)}
        >
          <option value="railway">Railway</option>
          {machines.map((machine) => (
            <option key={machine.id} value={machine.id}>
              {machine.name}
              {machine.online ? "" : " · Offline"}
            </option>
          ))}
          {selected !== "railway" && !current && (
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
      {selected !== "railway" && !current?.online && (
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
              Studio controls the run. Your chosen machine owns project files,
              CLI sign-ins, checks, and integration.
            </p>
            <div className="machine-list">
              <article>
                <div>
                  <strong>Railway</strong>
                  <small>Hosted projects and CLI connections</small>
                </div>
                <span>Cloud</span>
              </article>
              {machines.map((machine) => (
                <article key={machine.id}>
                  <div>
                    <strong>{machine.name}</strong>
                    <small>
                      {machine.platform === "darwin"
                        ? "macOS"
                        : machine.platform}{" "}
                      · {machine.online ? "Connected" : "Offline"}
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
                  </div>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => void revoke(machine.id)}
                  >
                    Disconnect
                  </button>
                </article>
              ))}
            </div>
            <section className="pair-machine">
              <h3>Connect a local worker</h3>
              <p>
                Install Parallax on the machine, then run this command with a
                project you approve. It connects outward over HTTPS; no inbound
                port or provider credentials are shared.
              </p>
              <code>
                parallax worker --url {location.origin} --workspace
                /absolute/path/to/project
              </code>
              <p>
                Paste the one-time code into the worker’s hidden prompt. Anyone
                with access to this private Studio can operate that approved
                project. Disconnect revokes future commands; an offline machine
                receives the revocation when it reconnects.
              </p>
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void createPair()}
              >
                {busy ? "Working…" : "Generate pairing code"}
              </button>
              {pair && (
                <div className="pair-code" role="status">
                  {expires > now ? (
                    <>
                      <code>{pair.code}</code>
                      <small>
                        Expires in {Math.ceil((expires - now) / 1000)} seconds ·
                        usable once
                      </small>
                    </>
                  ) : (
                    <p>Code expired. Generate a fresh code.</p>
                  )}
                </div>
              )}
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
