import { useRef, useState } from "react";
import { api, messageOf } from "./api";
import type { Workflow } from "./Workflows";
export function PilotMetrics({ workflow }: { workflow: Workflow | null }) {
  const [seconds, setSeconds] = useState("");
  const [interventions, setInterventions] = useState("0");
  const [accepted, setAccepted] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  async function download() {
    setBusy(true);
    try {
      const report = await api("/pilot/report");
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "parallax-pilot-report.json";
      link.click();
      URL.revokeObjectURL(url);
      setNotice(
        "Report downloaded. Unreported provider cost is marked unknown.",
      );
    } catch (e) {
      setNotice(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="pilot-metrics">
      <summary>Pilot measurements</summary>
      <p>
        Measured task outcomes on this worker. Provider costs are unknown unless
        observed.
      </p>
      <button
        className="secondary-button"
        disabled={busy}
        onClick={() => void download()}
      >
        Download pilot report
      </button>
      {workflow && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setNotice("");
            const body = {
              workflow_id: workflow.id,
              approach: "single_agent",
              duration_seconds: Number(seconds),
              interventions: Number(interventions),
              accepted,
            };
            const signature = JSON.stringify(body);
            if (pending.current?.signature !== signature)
              pending.current = { signature, id: crypto.randomUUID() };
            try {
              await api("/pilot/benchmark", {
                method: "POST",
                body: JSON.stringify({
                  ...body,
                  request_id: pending.current.id,
                }),
              });
              pending.current = null;
              setNotice(
                "Comparison recorded against this task's saved goal and checks.",
              );
            } catch (failure) {
              setNotice(messageOf(failure));
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            Record your usual single-agent attempt using the same baseline, goal
            and checks as “{workflow.title}”.
          </p>
          <label>
            Duration in seconds
            <input
              type="number"
              min="0"
              max="86400"
              value={seconds}
              onChange={(e) => setSeconds(e.target.value)}
              required
            />
          </label>
          <label>
            Human interventions
            <input
              type="number"
              min="0"
              max="10000"
              value={interventions}
              onChange={(e) => setInterventions(e.target.value)}
              required
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            Met the same acceptance criteria
          </label>
          <button disabled={busy}>Record comparison</button>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
    </details>
  );
}
