import { useEffect, useState } from "react";
import { api, messageOf } from "./api";
import type { RunResult } from "./types";
type RecoveryInfo = {
  category: string | null;
  message?: string;
  actions: { id: string; label: string; detail: string }[];
};
export function Recovery({
  run,
  onUpdate,
  onConfigure,
}: {
  run: RunResult;
  onUpdate: (run: RunResult) => void;
  onConfigure: () => void;
}) {
  const [info, setInfo] = useState<RecoveryInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    setInfo(null);
    setInspecting(false);
    setError("");
    void api<RecoveryInfo>(`/runs/${run.run_id}/recovery`, {
      signal: abort.signal,
    })
      .then(setInfo)
      .catch((e) => {
        if (!abort.signal.aborted) setError(messageOf(e));
      });
    return () => abort.abort();
  }, [run.run_id, run.status, run.errors.length]);
  if (!["needs_attention", "interrupted"].includes(run.status)) return null;
  async function recover(action: string) {
    setBusy(true);
    setError("");
    try {
      onUpdate(
        await api<RunResult>(`/runs/${run.run_id}/recover`, {
          method: "POST",
          body: JSON.stringify({ action }),
        }),
      );
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="recovery-panel">
      <span className="eyebrow">PRESERVED WORK</span>
      <h2>{info?.category?.replaceAll("_", " ") || "Recovery"}</h2>
      <p>{info?.message || "Loading the available recovery options…"}</p>
      {info?.actions.map((action) => (
        <div key={action.id}>
          <p className="readiness-note">{action.detail}</p>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() =>
              action.id === "fix_configuration"
                ? onConfigure()
                : action.id === "inspect_conflict"
                  ? (() => {
                      setInspecting(true);
                      document
                        .getElementById("candidate-evidence")
                        ?.scrollIntoView({ behavior: "auto" });
                    })()
                  : void recover(action.id)
            }
          >
            {busy ? "Reconciling…" : action.label}
          </button>
        </div>
      ))}
      {error && (
        <p role="alert" className="readiness-error">
          {error}
        </p>
      )}
      <details
        id="candidate-evidence"
        open={inspecting}
        onToggle={(e) => setInspecting(e.currentTarget.open)}
      >
        <summary>Retained candidate and failure evidence</summary>
        <pre>{run.diff || "No patch recorded yet."}</pre>
        {run.errors.map((e, i) => (
          <p key={i}>{String(e.message || e.code || "")}</p>
        ))}
      </details>
    </section>
  );
}
