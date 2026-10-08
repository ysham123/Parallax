import { useEffect, useState } from "react";
import { api, messageOf, viaMachine } from "./api";

type Lesson = {
  id: string;
  kind: "prefer" | "avoid" | "caution" | "fact";
  when: string;
  observed: string;
  scope: string[];
  status: string;
  support: number;
  refute: number;
};
type Memory = { lessons: Lesson[]; counts: { runs: number; nodes: number; lessons: number } };

const KIND: Record<Lesson["kind"], string> = {
  prefer: "Worked",
  avoid: "Failed",
  caution: "Caution",
  fact: "Fact",
};

/** This project's local memory: what earlier runs recorded, with controls to disable lessons or forget it all. */
export function ProjectMemory({ workspace }: { workspace: string }) {
  const [memory, setMemory] = useState<Memory | null>(null);
  const [error, setError] = useState("");
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [revision, setRevision] = useState(0);
  // Memory stays on the machine that ran the work; a paired machine's memory is not relayed.
  const remote = viaMachine();

  useEffect(() => {
    let current = true;
    setMemory(null);
    setError("");
    setHidden(false);
    setConfirming(false);
    if (remote || !workspace.trim()) return;
    api<Memory>(`/memory?${new URLSearchParams({ workspace })}`)
      .then((value) => current && setMemory(value))
      .catch((problem) => {
        if (!current) return;
        const message = messageOf(problem);
        // Workspaces without local memory access, or a path that is not a project yet, show nothing.
        if (/403|hosted|existing project directory|not approved/i.test(message)) setHidden(true);
        else setError(message);
      });
    return () => {
      current = false;
    };
  }, [workspace, revision, remote]);

  if (remote || hidden || !workspace.trim()) return null;

  async function toggle(lesson: Lesson) {
    setBusy(lesson.id);
    setError("");
    try {
      await api(`/memory/lessons/${encodeURIComponent(lesson.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ workspace, status: lesson.status === "disabled" ? "active" : "disabled" }),
      });
      setRevision((value) => value + 1);
    } catch (problem) {
      setError(messageOf(problem));
    } finally {
      setBusy("");
    }
  }

  async function forget() {
    setBusy("forget");
    setError("");
    try {
      await api(`/memory?${new URLSearchParams({ workspace })}`, { method: "DELETE" });
      setConfirming(false);
      setRevision((value) => value + 1);
    } catch (problem) {
      setError(messageOf(problem));
    } finally {
      setBusy("");
    }
  }

  const lessons = memory?.lessons || [];
  return (
    <section className="project-readiness project-memory" aria-labelledby="memory-title" aria-busy={!memory && !error}>
      <div className="readiness-heading">
        <div>
          <span className="eyebrow">PROJECT MEMORY</span>
          <h2 id="memory-title">What earlier runs learned</h2>
          <p>
            Coordinators read these as dated observations from this project, never as rules. They are stored only on
            this machine.
          </p>
        </div>
        <button className="secondary-button small" onClick={() => setRevision((value) => value + 1)} disabled={!!busy}>
          Refresh
        </button>
      </div>
      {error ? (
        <p role="alert" className="readiness-error">
          {error}
        </p>
      ) : !memory ? (
        <p role="status">Reading this project's memory…</p>
      ) : (
        <>
          <p className="readiness-note">
            {memory.counts.runs} {memory.counts.runs === 1 ? "run" : "runs"} recorded · {memory.counts.lessons} active{" "}
            {memory.counts.lessons === 1 ? "lesson" : "lessons"}
          </p>
          {lessons.length === 0 ? (
            <p className="readiness-note">
              No lessons yet. After a run finishes, an isolated session may record up to three, each grounded in that
              run's checks and reviews.
            </p>
          ) : (
            <ul className="memory-lessons">
              {lessons.map((lesson) => (
                <li key={lesson.id} className={lesson.status === "disabled" ? "disabled" : undefined}>
                  <div>
                    <span className={`memory-kind ${lesson.kind}`}>{KIND[lesson.kind] || lesson.kind}</span>
                    <strong>{lesson.when}</strong>
                    <p>{lesson.observed}</p>
                    <small>
                      {lesson.scope.join(", ")} · support {lesson.support} · contradicted {lesson.refute}
                      {lesson.status !== "active" ? ` · ${lesson.status}` : ""}
                    </small>
                  </div>
                  <button
                    className="secondary-button small"
                    onClick={() => void toggle(lesson)}
                    disabled={!!busy}
                    aria-label={`${lesson.status === "disabled" ? "Enable" : "Disable"} lesson: ${lesson.when}`}
                  >
                    {busy === lesson.id ? "Saving…" : lesson.status === "disabled" ? "Enable" : "Disable"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {memory.counts.runs > 0 &&
            (confirming ? (
              <div className="memory-forget" role="group" aria-label="Confirm forgetting project memory">
                <p>Forget every recorded run and lesson for this project? Runs and receipts are not affected.</p>
                <button className="secondary-button small memory-danger" onClick={() => void forget()} disabled={!!busy}>
                  {busy === "forget" ? "Forgetting…" : "Forget project memory"}
                </button>
                <button className="secondary-button small" onClick={() => setConfirming(false)} disabled={!!busy}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="text-button memory-forget-start" onClick={() => setConfirming(true)}>
                Forget this project's memory
              </button>
            ))}
        </>
      )}
    </section>
  );
}
