import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiUrl, messageOf, viaMachine } from "./api";
import { ProviderMark } from "./Brand";
import { eventSummary } from "./RunWorkspace";
import { parseDiff } from "./diff-model";
import { WorkIcon } from "./WorkIcon";
import { workflowGroup, workflowLabels } from "./workflow-state";
import { LABELS, type RunEvent, type RunResult } from "./types";
import type { Workflow } from "./Workflows";

const text = (v: unknown, fallback = "") =>
  v == null ? fallback : typeof v === "string" ? v : JSON.stringify(v);
const clock = (at: string) =>
  new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const label = (v: string) => v.replaceAll("_", " ");

type EvidenceTab = "changes" | "checks" | "findings" | "settings";
export function TaskWorkspace({
  visible,
  feedback,
  onFeedback,
  sending,
  sent,
  onSend,
  parentTitle,
  followups,
  onRelated,
  workflow,
  ready,
  busy,
  online,
  onAction,
  onAgain,
  onInspect,
  renderEvidence,
}: {
  visible: boolean;
  feedback: string;
  sending: boolean;
  sent: string;
  onSend: () => void;
  parentTitle?: string;
  followups: Workflow[];
  onRelated: (id: string) => void;
  onFeedback: (update: string | ((value: string) => string)) => void;
  workflow: Workflow;
  ready: boolean;
  busy: string;
  online: boolean;
  onAction: (action: "approve" | "reject" | "resume" | "cancel") => void;
  onAgain: (feedback?: string) => void;
  onInspect: (id: string) => void;
  renderEvidence: (
    run: RunResult,
    tab: "checks" | "findings" | "settings",
  ) => ReactNode;
}) {
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<EvidenceTab>("changes");
  const [filePath, setFilePath] = useState("");
  const [fileQuery, setFileQuery] = useState("");
  const [diffPage, setDiffPage] = useState(0);
  const codeRef = useRef<HTMLDivElement>(null);
  const [activityOpen, setActivityOpen] = useState(true);
  const [stream, setStream] = useState("connecting");
  const [revision, setRevision] = useState(0);
  const lastEvent = useRef(0);
  const runId = workflow.run_id;
  useEffect(() => {
    if (!runId || !visible) return;
    const abort = new AbortController();
    let fetching = false;
    const load = async () => {
      if (fetching || abort.signal.aborted) return;
      fetching = true;
      try {
        const result = await api<RunResult>(`/runs/${runId}`, {
          signal: abort.signal,
        });
        if (!abort.signal.aborted) {
          setRun(result);
          setError("");
        }
      } catch (failure) {
        if (!abort.signal.aborted) setError(messageOf(failure));
      } finally {
        fetching = false;
      }
    };
    void load();
    const timer = window.setInterval(
      () => {
        if (!document.hidden) void load();
      },
      viaMachine() ? 15000 : 4000,
    );
    const source = new EventSource(
      apiUrl(`/runs/${runId}/events?cursor=${lastEvent.current}`),
      { withCredentials: true },
    );
    source.onopen = () => setStream("live");
    source.onerror = () => setStream("reconnecting");
    source.onmessage = (message) => {
      try {
        const next = JSON.parse(message.data) as RunEvent;
        if (
          !next.kind ||
          next.run_id !== runId ||
          next.sequence <= lastEvent.current
        )
          return;
        lastEvent.current = next.sequence;
        setEvents((previous) => [...previous, next].slice(-500));
      } catch {
        setStream("reconnecting");
      }
    };
    return () => {
      abort.abort();
      window.clearInterval(timer);
      source.close();
    };
  }, [runId, revision, visible, workflow.candidate?.digest]);
  const files = useMemo(() => parseDiff(run?.diff || ""), [run?.diff]);
  const visibleFiles = files.filter((file) =>
    file.path.toLowerCase().includes(fileQuery.toLowerCase()),
  );
  const activeFile =
    visibleFiles.find((file) => file.path === filePath) || visibleFiles[0];
  useEffect(() => setDiffPage(0), [activeFile?.path]);
  const pageSize = 400;
  const pageCount = Math.ceil((activeFile?.lines.length || 0) / pageSize);
  const currentPage = Math.min(diffPage, Math.max(0, pageCount - 1));
  useEffect(() => {
    if (codeRef.current) codeRef.current.scrollTop = 0;
  }, [currentPage, activeFile?.path]);
  const totals = files.reduce(
    (sum, file) => ({
      added: sum.added + file.added,
      removed: sum.removed + file.removed,
    }),
    { added: 0, removed: 0 },
  );
  const active = workflowGroup(workflow.status) === "running";
  const steerable =
    workflow.status === "preparing" &&
    !!run &&
    !["completed", "failed", "cancelled", "interrupted"].includes(run.status);
  const participants = workflow.spec
    ? [workflow.spec.coordinator, ...workflow.spec.team]
    : [];
  const meaningful = events.filter(
    (event) => !["worker_stream", "coordinator_stream"].includes(event.kind),
  );
  const selectedProject =
    workflow.workspace.split("/").filter(Boolean).at(-1) || "Project";
  return (
    <section className="task-workspace" aria-labelledby="selected-task-title">
      <header className="task-titlebar">
        <div className="task-title-context">
          <WorkIcon name="branch" />
          <span title={workflow.workspace}>{selectedProject}</span>
          <span>/</span>
          <code>{workflow.id.slice(0, 8)}</code>
          <span className={`workflow-status ${workflowGroup(workflow.status)}`}>
            {workflowLabels[workflow.status] || label(workflow.status)}
          </span>
        </div>
        <div className="task-title-row">
          <h1 id="selected-task-title">{workflow.title}</h1>
          <button
            className="icon-button"
            title={activityOpen ? "Hide task activity" : "Show task activity"}
            aria-label={
              activityOpen ? "Hide task activity" : "Show task activity"
            }
            aria-pressed={activityOpen}
            onClick={() => setActivityOpen(!activityOpen)}
          >
            <WorkIcon name="stack" />
          </button>
        </div>
        <div className="task-meta">
          <span>
            {workflow.template.name} <code>v{workflow.template.version}</code>
          </span>
          <span>
            {workflow.runtime_seconds
              ? `${Math.max(1, Math.round(workflow.runtime_seconds))}s execution`
              : "Waiting to start"}
          </span>
          {runId && (
            <button className="text-button" onClick={() => onInspect(runId)}>
              Open agent graph <WorkIcon name="arrow" size={13} />
            </button>
          )}
        </div>
      </header>
      {(workflow.parent_workflow_id || followups.length > 0) && (
        <nav className="task-relations" aria-label="Related tasks">
          {workflow.parent_workflow_id && (
            <button
              className="text-button"
              onClick={() => onRelated(workflow.parent_workflow_id!)}
            >
              <WorkIcon name="branch" size={13} />
              Parent: {parentTitle || workflow.parent_workflow_id.slice(0, 8)}
            </button>
          )}
          {followups.map((child) => (
            <button
              className="text-button"
              key={child.id}
              onClick={() => onRelated(child.id)}
            >
              Follow-up: {child.title}
            </button>
          ))}
        </nav>
      )}
      {workflow.error && (
        <div className="task-alert" role="alert">
          <WorkIcon name="warning" />
          <p>{workflow.error}</p>
        </div>
      )}
      {error && (
        <div className="task-alert" role="alert">
          <p>Evidence could not refresh: {error}</p>
          <button
            className="text-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      <div className={`task-panels ${activityOpen ? "" : "activity-hidden"}`}>
        {activityOpen && (
          <div className="task-conversation">
            <div className="pane-heading">
              <span>
                <WorkIcon name="activity" size={15} /> Task activity
              </span>
              <span className="activity-connection">
                {active
                  ? stream === "live"
                    ? "Live"
                    : "Reconnecting"
                  : "Recorded"}
              </span>
            </div>
            <div className="conversation-scroll">
              <article className="task-brief">
                <div className="activity-author">
                  <span className="author-avatar">Y</span>
                  <strong>Your request</strong>
                  <time dateTime={workflow.created_at}>
                    {clock(workflow.created_at)}
                  </time>
                </div>
                <p>{workflow.prompt || workflow.title}</p>
              </article>
              <div className="task-team" aria-label="Assigned team">
                {participants.map((member, i) => (
                  <div key={i}>
                    <ProviderMark provider={member.provider} size={21} />
                    <span>
                      <strong>
                        {LABELS[member.provider] || member.provider}
                      </strong>
                      <small>
                        {i === 0 ? "Coordinator" : member.role} ·{" "}
                        {member.model || "Provider default"}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
              {run && run.tasks.length > 0 && (
                <section className="task-plan">
                  <h2>
                    Plan <span>{run.tasks.length}</span>
                  </h2>
                  {run.tasks.map((task, i) => (
                    <details key={text(task.id, String(i))}>
                      <summary>
                        <span className={`plan-mark ${text(task.status)}`}>
                          <WorkIcon
                            name={
                              task.status === "completed" ? "check" : "activity"
                            }
                            size={13}
                          />
                        </span>
                        <span>{text(task.title, `Task ${i + 1}`)}</span>
                      </summary>
                      <div>
                        <span className="workflow-muted">
                          {label(text(task.status, "pending"))}
                        </span>
                        <p>{text(task.description || task.summary)}</p>
                        {Array.isArray(task.acceptance) && (
                          <ul>
                            {task.acceptance.map((item, j) => (
                              <li key={j}>{text(item)}</li>
                            ))}
                          </ul>
                        )}
                        <details>
                          <summary>Task data</summary>
                          <pre>{JSON.stringify(task, null, 2)}</pre>
                        </details>
                      </div>
                    </details>
                  ))}
                </section>
              )}
              {(workflow.candidate?.summary || run?.summary) && (
                <article className="task-outcome">
                  <div className="activity-author">
                    <span className="author-avatar parallax-avatar">
                      <WorkIcon name="branch" size={15} />
                    </span>
                    <strong>Team result</strong>
                  </div>
                  <p>{workflow.candidate?.summary || run?.summary}</p>
                </article>
              )}
              <details className="task-event-log">
                <summary>
                  <WorkIcon name="terminal" size={15} />
                  <span>Execution log</span>
                  <small>
                    {events.length >= 500
                      ? "Latest 500 events"
                      : `${events.length} events`}
                  </small>
                </summary>
                <ol>
                  {meaningful.slice(-80).map((event) => (
                    <li key={event.sequence}>
                      <details>
                        <summary>
                          <time dateTime={event.timestamp}>
                            {clock(event.timestamp)}
                          </time>
                          <span>{eventSummary(event)}</span>
                        </summary>
                        <pre>{JSON.stringify(event.data, null, 2)}</pre>
                      </details>
                    </li>
                  ))}
                </ol>
                {!meaningful.length && (
                  <p className="workflow-muted">No recorded events yet.</p>
                )}
              </details>
              <div className="task-timeline" aria-label="Task milestones">
                {workflow.timeline?.map((step, i) => (
                  <div key={i}>
                    <span className="timeline-dot" />
                    <span>{label(step.stage)}</span>
                    <time dateTime={step.at}>{clock(step.at)}</time>
                  </div>
                ))}
              </div>
            </div>
            <div className="task-followup">
              <label htmlFor="task-feedback">
                {active ? "Direct the team" : "Follow up on this task"}
              </label>
              <textarea
                id="task-feedback"
                value={feedback}
                onChange={(e) => onFeedback(e.target.value)}
                rows={2}
                maxLength={4000}
                placeholder={
                  steerable
                    ? "Add context or adjust the direction…"
                    : "Describe what needs to change next…"
                }
              />
              <div>
                <span>
                  {steerable
                    ? "Delivered during execution"
                    : active
                      ? "Waiting for an active run"
                      : "Opens a new task for review"}
                </span>
                <button
                  className="secondary-button"
                  disabled={
                    sending ||
                    !!busy ||
                    !feedback.trim() ||
                    (active && !steerable) ||
                    (steerable && !online)
                  }
                  onClick={() => (steerable ? onSend() : onAgain(feedback))}
                >
                  {sending ? "Sending…" : active ? "Send" : "Draft follow-up"}
                  <WorkIcon name="arrow" size={13} />
                </button>
              </div>
              {sent && <p role="status">{sent}</p>}
            </div>
          </div>
        )}
        <div className="task-evidence">
          <div
            className="evidence-tabs"
            role="tablist"
            aria-label="Task evidence"
          >
            {[
              ["changes", "Changes", "code", files.length],
              ["checks", "Checks", "check", run?.checks.length],
              ["findings", "Reviews", "review", run?.reviews.length],
              ["settings", "Details", "settings", undefined],
            ].map(([id, name, icon, count]) => (
              <button
                key={String(id)}
                id={`evidence-tab-${id}`}
                role="tab"
                aria-selected={tab === id}
                aria-controls="task-evidence-panel"
                tabIndex={tab === id ? 0 : -1}
                onKeyDown={(event) => {
                  const ids: EvidenceTab[] = [
                    "changes",
                    "checks",
                    "findings",
                    "settings",
                  ];
                  let next = ids.indexOf(tab);
                  if (event.key === "ArrowRight")
                    next = (next + 1) % ids.length;
                  else if (event.key === "ArrowLeft")
                    next = (next + ids.length - 1) % ids.length;
                  else if (event.key === "Home") next = 0;
                  else if (event.key === "End") next = ids.length - 1;
                  else return;
                  event.preventDefault();
                  setTab(ids[next]);
                  document.getElementById(`evidence-tab-${ids[next]}`)?.focus();
                }}
                onClick={() => setTab(id as EvidenceTab)}
              >
                <WorkIcon name={String(icon)} size={15} />
                {name}
                {typeof count === "number" && <small>{count}</small>}
              </button>
            ))}
          </div>
          <div
            id="task-evidence-panel"
            role="tabpanel"
            aria-labelledby={`evidence-tab-${tab}`}
            className={`evidence-body evidence-${tab}`}
          >
            {tab === "changes" ? (
              files.length ? (
                <>
                  <div className="diff-toolbar">
                    <span>
                      <WorkIcon name="branch" size={14} />
                      {workflow.status === "applied"
                        ? "Applied candidate"
                        : "Candidate changes"}
                    </span>
                    <span className="diff-count">
                      <b>+{totals.added}</b>
                      <i>−{totals.removed}</i>
                    </span>
                    {runId && (
                      <a
                        href={apiUrl(`/runs/${runId}/patch`)}
                        download
                        aria-label="Download exact patch"
                        title="Download exact patch"
                      >
                        <WorkIcon name="download" size={15} />
                      </a>
                    )}
                  </div>
                  <div className="diff-workspace">
                    <aside className="diff-files" aria-label="Changed files">
                      <label>
                        <WorkIcon name="search" size={13} />
                        <input
                          aria-label="Filter changed files"
                          placeholder="Filter files…"
                          value={fileQuery}
                          onChange={(e) => setFileQuery(e.target.value)}
                        />
                      </label>
                      {visibleFiles.map((file) => (
                        <button
                          key={file.path}
                          aria-pressed={activeFile?.path === file.path}
                          onClick={() => setFilePath(file.path)}
                          title={file.path}
                        >
                          <WorkIcon name="code" size={14} />
                          <span>{file.path}</span>
                          <small className="diff-count">
                            <b>+{file.added}</b>
                            <i>−{file.removed}</i>
                          </small>
                        </button>
                      ))}
                    </aside>
                    {activeFile ? (
                      <div className="diff-document" key={activeFile.path}>
                        <div className="diff-file-heading">
                          <code>{activeFile.path}</code>
                          <span>Unified diff</span>
                        </div>
                        {pageCount > 1 && (
                          <div className="diff-pagination">
                            <span>
                              Patch rows {currentPage * pageSize + 1}–
                              {Math.min(
                                (currentPage + 1) * pageSize,
                                activeFile.lines.length,
                              )}{" "}
                              of {activeFile.lines.length.toLocaleString()}
                            </span>
                            <button
                              className="text-button"
                              disabled={currentPage === 0}
                              onClick={() => setDiffPage(currentPage - 1)}
                            >
                              Previous
                            </button>
                            <button
                              className="text-button"
                              disabled={currentPage + 1 >= pageCount}
                              onClick={() => setDiffPage(currentPage + 1)}
                            >
                              Next
                            </button>
                          </div>
                        )}
                        <div
                          className="code-scroll"
                          ref={codeRef}
                          tabIndex={0}
                          role="region"
                          aria-label={`Diff for ${activeFile.path}`}
                        >
                          <table className="patch-table">
                            <tbody>
                              {activeFile.lines
                                .slice(
                                  currentPage * pageSize,
                                  (currentPage + 1) * pageSize,
                                )
                                .map((line, i) => (
                                  <tr key={i} className={`patch-${line.kind}`}>
                                    <td className="line-number">{line.old}</td>
                                    <td className="line-number">{line.next}</td>
                                    <td className="code-line">
                                      <pre>{line.text || " "}</pre>
                                    </td>
                                  </tr>
                                ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    ) : (
                      <div className="evidence-empty">
                        <p>No changed files match “{fileQuery}”.</p>
                        <button
                          className="text-button"
                          onClick={() => setFileQuery("")}
                        >
                          Clear file filter
                        </button>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="evidence-empty">
                  <WorkIcon name="code" size={30} />
                  <h2>
                    {!run && !error
                      ? "Loading changes…"
                      : active
                        ? "Waiting for changes"
                        : "No patch recorded"}
                  </h2>
                  <p>
                    {active
                      ? "The team's file changes will appear here as the runtime records them."
                      : "Review the checks and activity for the recorded outcome."}
                  </p>
                </div>
              )
            ) : run ? (
              <div className="evidence-scroll">{renderEvidence(run, tab)}</div>
            ) : (
              <div className="evidence-empty">
                <p>
                  {error
                    ? "Evidence unavailable. Retry the connection above."
                    : "Waiting for run evidence…"}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
      <footer className="task-decision">
        <div className="decision-evidence">
          {workflow.candidate ? (
            <>
              <div className="decision-gates">
                {workflow.candidate.gates.map((gate) => (
                  <span
                    key={gate.id}
                    className={
                      gate.status === "passed" ? "passed" : "unverified"
                    }
                    title={gate.detail}
                  >
                    <WorkIcon
                      name={gate.status === "passed" ? "check" : "warning"}
                      size={13}
                    />
                    {gate.label}
                  </span>
                ))}
              </div>
              <span className="decision-caption">
                {workflow.status === "applied"
                  ? "Applied to your project."
                  : ready
                    ? "Approval applies the complete candidate to your project."
                    : "Recorded candidate evidence."}{" "}
                <code title={workflow.candidate.digest}>
                  {workflow.candidate.digest.slice(0, 10)}
                </code>
              </span>
            </>
          ) : (
            <>
              <strong>
                {workflow.status === "preparing"
                  ? "Team is preparing the candidate"
                  : workflowLabels[workflow.status] || label(workflow.status)}
              </strong>
              <span className="decision-caption">
                Review, checks, and your approval are required before
                application.
              </span>
            </>
          )}
        </div>
        <div className="decision-actions">
          {ready ? (
            <>
              <button
                className="secondary-button"
                disabled={!!busy || !online || !!error}
                onClick={() => onAction("reject")}
              >
                Decline
              </button>
              <button
                className="primary-button"
                disabled={
                  !!busy ||
                  !online ||
                  !!error ||
                  run?.run_id !== runId ||
                  run?.status !== "completed"
                }
                onClick={() => onAction("approve")}
              >
                <WorkIcon name="check" size={15} />
                {busy === "approve"
                  ? "Applying…"
                  : run?.status !== "completed"
                    ? "Loading final evidence…"
                    : "Approve & apply"}
              </button>
            </>
          ) : workflow.status === "applied" && runId ? (
            <a
              className="secondary-button"
              href={apiUrl(`/runs/${runId}/receipt`)}
              download
            >
              <WorkIcon name="download" size={15} />
              Verification record
            </a>
          ) : ["interrupted", "needs_attention"].includes(workflow.status) ? (
            <button
              className="primary-button"
              disabled={!!busy || !online}
              onClick={() => onAction("resume")}
            >
              Resume task
            </button>
          ) : null}
          {!ready &&
            !["applied", "rejected", "cancelled", "applying"].includes(
              workflow.status,
            ) &&
            workflow.decision?.action !== "approve" && (
              <button
                className="secondary-button"
                disabled={!!busy || !online}
                onClick={() => onAction("cancel")}
              >
                Stop task
              </button>
            )}
          {["rejected", "cancelled"].includes(workflow.status) && (
            <button className="secondary-button" onClick={() => onAgain()}>
              Use task again
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
