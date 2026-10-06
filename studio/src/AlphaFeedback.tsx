import { useState } from "react";
import { api, messageOf } from "./api";
import type { RunResult } from "./types";
export function AlphaFeedback({ run }: { run: RunResult }) {
  const [accepted, setAccepted] = useState(false),
    [unassisted, setUnassisted] = useState(false),
    [unintended, setUnintended] = useState(false),
    [staging, setStaging] = useState(false);
  const [minutes, setMinutes] = useState(0),
    [interventions, setInterventions] = useState(0),
    [task, setTask] = useState(1);
  const [comparison, setComparison] = useState("parallax"),
    [order, setOrder] = useState("first"),
    [status, setStatus] = useState(""),
    [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    setStatus("");
    try {
      await api(
        comparison === "single_codex"
          ? "/feedback/baseline"
          : `/runs/${run.run_id}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({
            accepted,
            setup_unassisted: unassisted,
            manual_interventions: interventions,
            minutes,
            comparison,
            task_number: task,
            order,
            unintended_edits: unintended,
            staging_loss: staging,
          }),
        },
      );
      setStatus("Recorded locally. Nothing has been shared.");
    } catch (e) {
      setStatus(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  if (
    !["completed", "needs_attention", "failed", "cancelled"].includes(
      run.status,
    )
  )
    return null;
  return (
    <details className="alpha-feedback">
      <summary>Optional developer alpha feedback</summary>
      <p className="readiness-note">
        Opt in to local metrics for this finished task. Export includes
        aggregate counts only. Sharing is your choice.
      </p>
      <div className="project-profile-grid">
        <label>
          Compared workflow
          <select
            value={comparison}
            onChange={(e) => setComparison(e.target.value)}
          >
            <option value="parallax">Parallax</option>
            <option value="single_codex">Single Codex baseline</option>
          </select>
        </label>
        <label>
          Task number
          <input
            type="number"
            min={1}
            max={3}
            value={task}
            onChange={(e) => setTask(Number(e.target.value))}
          />
        </label>
        <label>
          Execution order
          <select value={order} onChange={(e) => setOrder(e.target.value)}>
            <option value="first">First</option>
            <option value="second">Second</option>
          </select>
        </label>
        <label>
          Minutes spent
          <input
            type="number"
            min={0}
            max={1440}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          />
        </label>
        <label>
          Manual interventions
          <input
            type="number"
            min={0}
            max={1000}
            value={interventions}
            onChange={(e) => setInterventions(Number(e.target.value))}
          />
        </label>
      </div>
      <div className="feedback-flags">
        {[
          ["Outcome accepted", accepted, setAccepted],
          ["Setup completed without assistance", unassisted, setUnassisted],
          ["Unintended edits observed", unintended, setUnintended],
          ["Staging loss observed", staging, setStaging],
        ].map(([name, value, set]) => (
          <label key={String(name)}>
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => (set as (v: boolean) => void)(e.target.checked)}
            />
            {String(name)}
          </label>
        ))}
      </div>
      <button
        className="secondary-button small"
        disabled={busy}
        onClick={() => void save()}
      >
        {busy ? "Recording…" : "Record local metrics"}
      </button>
      <a
        className="secondary-button small"
        href="/api/feedback/export"
        download="parallax-alpha-metrics.json"
      >
        Export aggregate metrics
      </a>
      <p role="status">{status}</p>
    </details>
  );
}
