import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiUrl, messageOf, viaMachine } from "./api";
import { PublicationPanel } from "./PublicationPanel";
import { ProviderMark } from "./Brand";
import { eventSummary } from "./RunWorkspace";
import { parseDiff } from "./diff-model";
import {
  actorLabel,
  locateFinding,
  normalizeFinding,
  recordedTime,
  relationKind,
  requestLabel,
  type ActorDirectory,
  type FindingDestination,
} from "./task-review";
import { WorkIcon } from "./WorkIcon";
import { workflowGroup, workflowLabels } from "./workflow-state";
import { LABELS, type RunEvent, type RunResult } from "./types";
import type { Workflow } from "./Workflows";
import {
  bindingPresentation,
  checkCounts,
  currentFinalChecks,
  currentVerificationAttempt,
  finalReview,
  gatePresentation,
  observationOf,
  reviewPresentation,
} from "./evidence-presentation";

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
  approvalHint,
  busy,
  online,
  onAction,
  onAgain,
  onRevise,
  canDeliver,
  members,
  actorDirectory = [],
  viewerActor,
  onAssign,
  onRefresh,
  onComment,
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
  approvalHint?: string;
  busy: string;
  online: boolean;
  onAction: (
    action: "approve" | "reject" | "resume" | "cancel" | "apply",
  ) => void;
  onAgain: (feedback?: string) => void;
  onRevise: (findings: { review: number; finding: number }[]) => void;
  canDeliver: boolean;
  members: { account: string; name: string; login: string }[];
  actorDirectory?: ActorDirectory;
  viewerActor?: string;
  onAssign: (reviewer: string) => void;
  onRefresh: () => void;
  onComment: () => void;
  onInspect: (id: string) => void;
  renderEvidence: (
    run: RunResult,
    tab: "checks" | "findings" | "settings",
  ) => ReactNode;
}) {
  const [selectedFindings, setSelectedFindings] = useState<
    { review: number; finding: number }[]
  >([]);
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<EvidenceTab>("changes");
  const [filePath, setFilePath] = useState("");
  const [fileQuery, setFileQuery] = useState("");
  const [diffPage, setDiffPage] = useState(0);
  const [findingTarget, setFindingTarget] = useState<FindingDestination | null>(
    null,
  );
  const codeRef = useRef<HTMLDivElement>(null);
  const [activityOpen, setActivityOpen] = useState(true);
  const [stream, setStream] = useState("connecting");
  const [revision, setRevision] = useState(0);
  const lastEvent = useRef(0);
  const runId = workflow.run_id;
  useEffect(() => {
    setSelectedFindings([]);
    setFindingTarget(null);
    setRun(null);
  }, [runId, workflow.candidate?.digest]);
  useEffect(() => {
    if (!online) {
      setError("");
      setStream("offline");
      return;
    }
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
  }, [runId, revision, visible, online, workflow.candidate?.digest]);
  const files = useMemo(() => parseDiff(run?.diff || ""), [run?.diff]);
  const visibleFiles = files.filter((file) =>
    file.path.toLowerCase().includes(fileQuery.toLowerCase()),
  );
  const activeFile =
    visibleFiles.find((file) => file.path === filePath) || visibleFiles[0];
  useEffect(() => {
    if (findingTarget?.path === activeFile?.path)
      setDiffPage(findingTarget?.page || 0);
    else setDiffPage(0);
  }, [activeFile?.path, findingTarget]);
  const pageSize = 400;
  const pageCount = Math.ceil((activeFile?.lines.length || 0) / pageSize);
  const currentPage = Math.min(diffPage, Math.max(0, pageCount - 1));
  useEffect(() => {
    if (tab !== "changes") return;
    const code = codeRef.current;
    if (!code) {
      if (findingTarget)
        document.getElementById("evidence-tab-changes")?.focus();
      return;
    }
    code.scrollTop = 0;
    if (
      findingTarget?.path !== activeFile?.path ||
      findingTarget?.row === undefined
    ) {
      if (findingTarget)
        document.getElementById("evidence-tab-changes")?.focus();
      return;
    }
    const row = code.querySelector<HTMLElement>(
      `[data-patch-row="${findingTarget.row}"]`,
    );
    if (row) {
      code.scrollTop = Math.max(0, row.offsetTop - code.clientHeight / 2);
      row.focus({ preventScroll: true });
    } else document.getElementById("evidence-tab-changes")?.focus();
  }, [currentPage, activeFile?.path, findingTarget, tab]);
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
    (event) =>
      ![
        "worker_stream",
        "coordinator_stream",
        "evidence_observation",
        "evidence_attempt_started",
      ].includes(event.kind),
  );
  const selectedProject =
    workflow.workspace.split("/").filter(Boolean).at(-1) || "Project";
  const human = (actor?: string | null) =>
    actorLabel(actor, actorDirectory, viewerActor);
  const decision = workflow.decision || workflow.approval;
  const currentAttempt = currentVerificationAttempt(run?.artifacts || {});
  const currentChecks = currentFinalChecks(run?.checks || [], currentAttempt);
  const currentReview = finalReview(
    run?.reviews || [],
    currentChecks,
    currentAttempt,
  );
  const checkOutcomes = checkCounts(currentChecks);
  const finalReviewState = reviewPresentation(currentReview || {});
  const delivery = workflow.delivery;
  const unbound = [
    ...(run?.checks || []),
    ...(currentReview ? [currentReview] : []),
  ].filter((row) => !observationOf(row)).length;
  const uncertainGates = (workflow.candidate?.gates || []).filter(
    (gate) => gatePresentation(gate).state !== "passed",
  );
  const usageReports = Array.isArray(run?.usage?.reports)
    ? run.usage.reports
    : [];
  const relationship = relationKind(workflow);
  const locate = (finding: ReturnType<typeof normalizeFinding>) => {
    const destination = locateFinding(
      files,
      finding,
      workflow.workspace,
      pageSize,
    );
    setFindingTarget(destination);
    if (destination.path) {
      setFileQuery("");
      setFilePath(destination.path);
      setDiffPage(destination.page);
    }
    setTab("changes");
  };
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
        <dl className="task-human-meta" aria-label="Human review record">
          <div>
            <dt>Requester</dt>
            <dd>{human(workflow.requester)}</dd>
          </div>
          <div>
            <dt>Assigned reviewer</dt>
            <dd>
              {workflow.reviewer ? human(workflow.reviewer) : "Not assigned"}
            </dd>
          </div>
          <div>
            <dt>Human decision</dt>
            <dd>
              {decision ? (
                <>
                  {decision.action === "approve"
                    ? "Approved"
                    : decision.action === "reject"
                      ? "Declined"
                      : "Recorded decision"}
                  {" by "}
                  {human(decision.actor)}
                  <time dateTime={decision.at || undefined}>
                    {recordedTime(decision.at)}
                  </time>
                </>
              ) : (
                "No decision recorded"
              )}
            </dd>
          </div>
        </dl>
      </header>
      {(workflow.parent_workflow_id || followups.length > 0) && (
        <nav className="task-relations" aria-label="Related tasks">
          {workflow.parent_workflow_id && (
            <button
              className="text-button"
              onClick={() => onRelated(workflow.parent_workflow_id!)}
            >
              <WorkIcon name="branch" size={13} />
              {relationship === "revision"
                ? "Revised candidate from"
                : relationship === "fresh"
                  ? "New task from current project after"
                  : "Related task"}
              : {parentTitle || workflow.parent_workflow_id.slice(0, 8)}
            </button>
          )}
          {followups.map((child) => (
            <button
              className="text-button"
              key={child.id}
              onClick={() => onRelated(child.id)}
            >
              {relationKind(child) === "revision"
                ? "Candidate revision"
                : relationKind(child) === "fresh"
                  ? "New task from current project"
                  : "Related task"}
              : {child.title}
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
      <section
        className="candidate-summary"
        aria-labelledby="candidate-summary-title"
      >
        <header>
          <h2 id="candidate-summary-title">Candidate result</h2>
          {workflow.candidate && (
            <code title={workflow.candidate.digest}>
              {workflow.candidate.digest.slice(0, 12)}
            </code>
          )}
        </header>
        <p>
          {workflow.candidate?.summary ||
            run?.summary ||
            "No candidate result has been recorded yet."}
        </p>
        <dl className="candidate-summary-facts">
          <div>
            <dt>Changes</dt>
            <dd>
              <button className="text-button" onClick={() => setTab("changes")}>
                {workflow.candidate?.changed_files?.length ??
                  run?.changed_files?.length ??
                  "Unrecorded"}{" "}
                files
              </button>
            </dd>
          </div>
          <div>
            <dt>Current final checks</dt>
            <dd>
              <button className="text-button" onClick={() => setTab("checks")}>
                {currentChecks.length
                  ? `${checkOutcomes.passed} passed · ${checkOutcomes.failed} failed · ${checkOutcomes.unavailable} unavailable · ${checkOutcomes.skipped} skipped · ${checkOutcomes.unrecorded} unrecorded`
                  : "No current final checks recorded"}
              </button>
            </dd>
          </div>
          <div>
            <dt>Independent review</dt>
            <dd>
              <button
                className={`text-button evidence-outcome ${finalReviewState.state}`}
                onClick={() => setTab("findings")}
              >
                {finalReviewState.label}
              </button>
            </dd>
          </div>
          <div>
            <dt>Human decision</dt>
            <dd>
              {decision?.action === "approve"
                ? "Approved"
                : decision?.action === "reject"
                  ? "Declined"
                  : "Awaiting a recorded decision"}
            </dd>
          </div>
          <div>
            <dt>Local delivery</dt>
            <dd>
              {delivery?.local === "applied" || workflow.status === "applied"
                ? "Applied"
                : delivery?.local === "pending"
                  ? "Not applied"
                  : delivery?.local
                    ? label(delivery.local)
                    : workflow.schema_version === "2.0"
                      ? "Unrecorded"
                      : "Legacy combined approval and application"}
            </dd>
          </div>
          <div>
            <dt>GitHub delivery</dt>
            <dd>
              {workflow.publication
                ? "Draft PR published"
                : delivery?.github === "pending"
                  ? "Not published"
                  : delivery?.github
                    ? label(delivery.github)
                    : "Unrecorded"}
            </dd>
          </div>
          <div>
            <dt>Execution time</dt>
            <dd>
              {typeof workflow.runtime_seconds === "number"
                ? `${workflow.runtime_seconds}s recorded`
                : "Unrecorded"}
            </dd>
          </div>
          <div>
            <dt>Provider usage</dt>
            <dd>
              {usageReports.length
                ? `${usageReports.length} usage reports; total cost unknown`
                : "Usage unreported; cost unknown"}
            </dd>
          </div>
        </dl>
        <div className="candidate-uncertainty">
          <strong>Evidence scope &amp; remaining uncertainty</strong>
          <p>
            Checks establish only their recorded coverage. Review is separate
            from human approval; approval is separate from delivery.
          </p>
          {!currentChecks.length && (
            <p>
              No current final command evidence is recorded.
              {!!run?.checks.length &&
                " Previous check outcomes remain in Checks; their association with this verification attempt is unrecorded or historical."}
            </p>
          )}
          {finalReviewState.state !== "passed" && (
            <p>{finalReviewState.detail}</p>
          )}
          {!!unbound && (
            <p>
              Artifact binding is unrecorded for {unbound} final observation
              {unbound === 1 ? "" : "s"}. Older records do not establish exact
              workspace provenance.
            </p>
          )}
          {uncertainGates.map((gate) => (
            <p key={gate.id}>
              <strong>
                {gate.label}: {gatePresentation(gate).label}.
              </strong>{" "}
              {gatePresentation(gate).detail}
            </p>
          ))}
          {error && (
            <p>
              Evidence refresh is unavailable. Displayed results may be older
              recorded evidence.
            </p>
          )}
        </div>
        {runId && (
          <a
            className="text-button"
            href={apiUrl(`/runs/${runId}/receipt`)}
            download
          >
            Download verification record{" "}
            <span>(recorded evidence may be partial)</span>
          </a>
        )}
      </section>
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
                  <span className="author-avatar" aria-hidden="true">
                    {human(workflow.requester).slice(0, 1)}
                  </span>
                  <strong>
                    {requestLabel(workflow.requester, viewerActor)}
                  </strong>
                  <time dateTime={workflow.created_at}>
                    {clock(workflow.created_at)}
                  </time>
                </div>
                <span className="requester-attribution">
                  Requested by {human(workflow.requester)}
                </span>
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
              {!!workflow.comments?.length && (
                <section
                  className="task-review-comments"
                  aria-label="Human review comments"
                >
                  <h2>Review comments</h2>
                  {workflow.comments.map((comment) => (
                    <article key={comment.id}>
                      <div className="activity-author">
                        <strong>{human(comment.actor)}</strong>
                        <time dateTime={comment.at || undefined}>
                          {recordedTime(comment.at)}
                        </time>
                      </div>
                      <p>{comment.message}</p>
                    </article>
                  ))}
                </section>
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
              {selectedFindings.length > 0 && (
                <p className="revision-selection-note">
                  {selectedFindings.length} review finding
                  {selectedFindings.length === 1 ? "" : "s"} selected for a
                  candidate revision.
                </p>
              )}
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
                      : `A revision starts from the saved candidate with a new ${workflow.spec?.limits.minutes ? `${workflow.spec.limits.minutes} minute` : "execution"} budget. A new task starts from your current project.`}
                </span>
                <button
                  className="secondary-button"
                  disabled={
                    sending ||
                    !!busy ||
                    !canDeliver ||
                    !feedback.trim() ||
                    (active && !steerable) ||
                    (steerable && !online)
                  }
                  onClick={() => (steerable ? onSend() : onAgain(feedback))}
                >
                  {sending
                    ? "Sending…"
                    : active
                      ? "Send"
                      : "New task from current project"}
                  <WorkIcon name="arrow" size={13} />
                </button>
                {!active &&
                  workflow.candidate &&
                  [
                    "awaiting_approval",
                    "rejected",
                    "approved",
                    "published",
                    "superseded",
                  ].includes(workflow.status) && (
                    <button
                      className="secondary-button"
                      disabled={
                        !!busy || !online || !feedback.trim() || !canDeliver
                      }
                      onClick={() => onRevise(selectedFindings)}
                    >
                      {busy === "revise"
                        ? "Starting revision…"
                        : "Revise candidate"}
                    </button>
                  )}
              </div>
              {workflow.schema_version === "2.0" && (
                <button
                  className="secondary-button"
                  disabled={!feedback.trim() || !!busy}
                  onClick={onComment}
                >
                  Save review comment
                </button>
              )}
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
            {tab === "changes" && findingTarget?.notice && (
              <p className="finding-navigation-notice" role="status">
                {findingTarget.notice}
              </p>
            )}
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
                          onClick={() => {
                            setFindingTarget(null);
                            setFilePath(file.path);
                          }}
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
                                  <tr
                                    key={i}
                                    data-patch-row={currentPage * pageSize + i}
                                    tabIndex={
                                      findingTarget?.path === activeFile.path &&
                                      findingTarget.row ===
                                        currentPage * pageSize + i
                                        ? -1
                                        : undefined
                                    }
                                    className={`patch-${line.kind}${findingTarget?.path === activeFile.path && findingTarget.row === currentPage * pageSize + i ? " finding-target" : ""}`}
                                  >
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
              <div className="evidence-scroll">
                {tab === "findings" ? (
                  <div className="task-review-reports">
                    {run.reviews.length ? (
                      run.reviews.map((review, reviewIndex) => (
                        <article className="review-report" key={reviewIndex}>
                          <header className="task-review-heading">
                            <ProviderMark
                              provider={text(review.provider, "custom")}
                              size={24}
                            />
                            <div>
                              <span>Independent review</span>
                              <h3>
                                {LABELS[text(review.provider)] ||
                                  text(
                                    review.provider,
                                    `Review ${reviewIndex + 1}`,
                                  )}
                              </h3>
                            </div>
                            <strong
                              className={`evidence-outcome ${reviewPresentation(review).state}`}
                            >
                              {reviewPresentation(review).label}
                            </strong>
                          </header>
                          <p className="evidence-reason">
                            {reviewPresentation(review).detail}
                          </p>
                          <p className="evidence-binding">
                            {bindingPresentation(review)}
                          </p>
                          {!!text(
                            review.summary ||
                              review.answer ||
                              review.response ||
                              review.text,
                          ) && (
                            <p className="review-prose">
                              {text(
                                review.summary ||
                                  review.answer ||
                                  review.response ||
                                  review.text,
                              )}
                            </p>
                          )}
                          {!!review.error && (
                            <p className="inline-error">{text(review.error)}</p>
                          )}
                          {(Array.isArray(review.findings)
                            ? review.findings
                            : []
                          ).map((raw, findingIndex) => {
                            const finding = normalizeFinding(raw, findingIndex);
                            const checked = selectedFindings.some(
                              (f) =>
                                f.review === reviewIndex &&
                                f.finding === findingIndex,
                            );
                            return (
                              <article
                                className="task-review-finding"
                                key={findingIndex}
                              >
                                <div className="task-finding-title">
                                  <span
                                    className={`task-finding-severity ${finding.severityClass}`}
                                  >
                                    {finding.severity}
                                  </span>
                                  <h4>{finding.title}</h4>
                                </div>
                                <p>{finding.body}</p>
                                {finding.file ? (
                                  <button
                                    className="text-button finding-location"
                                    onClick={() => locate(finding)}
                                    aria-label={`View ${finding.file}${finding.line ? `:${finding.line}` : ""} in changes`}
                                  >
                                    <WorkIcon name="code" size={14} />
                                    <code>
                                      {finding.file}
                                      {finding.line
                                        ? `:${finding.line}${finding.endLine && finding.endLine !== finding.line ? `–${finding.endLine}` : ""}`
                                        : ""}
                                    </code>
                                    <span>View in Changes</span>
                                  </button>
                                ) : (
                                  <span className="workflow-muted">
                                    Location unrecorded
                                  </span>
                                )}
                                {workflow.candidate && (
                                  <label className="finding-revision-choice">
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={(event) =>
                                        setSelectedFindings((previous) =>
                                          event.target.checked
                                            ? previous.some(
                                                (f) =>
                                                  f.review === reviewIndex &&
                                                  f.finding === findingIndex,
                                              )
                                              ? previous
                                              : [
                                                  ...previous,
                                                  {
                                                    review: reviewIndex,
                                                    finding: findingIndex,
                                                  },
                                                ]
                                            : previous.filter(
                                                (f) =>
                                                  f.review !== reviewIndex ||
                                                  f.finding !== findingIndex,
                                              ),
                                        )
                                      }
                                    />
                                    Include in revision
                                  </label>
                                )}
                              </article>
                            );
                          })}
                          <details>
                            <summary>Review data</summary>
                            <pre className="raw-data">
                              {JSON.stringify(review, null, 2)}
                            </pre>
                          </details>
                        </article>
                      ))
                    ) : (
                      <div className="evidence-empty">
                        <WorkIcon name="review" size={30} />
                        <h2>No reviews recorded</h2>
                        <p>
                          A candidate without findings still requires recorded
                          independent review and a human decision.
                        </p>
                      </div>
                    )}
                    {!!run.errors.length && (
                      <details className="task-review-diagnostics">
                        <summary>
                          Runtime diagnostics ({run.errors.length})
                        </summary>
                        <pre className="raw-data">
                          {JSON.stringify(run.errors, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                ) : (
                  renderEvidence(run, tab)
                )}
              </div>
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
      {workflow.status === "awaiting_approval" &&
        members.length > 0 &&
        canDeliver && (
          <label>
            Assign reviewer
            <select
              disabled={!!busy}
              value={workflow.reviewer || ""}
              onChange={(e) => onAssign(e.target.value)}
            >
              <option value="" disabled>
                Choose reviewer
              </option>
              {members
                .filter((m) => m.account !== workflow.requester)
                .map((m) => (
                  <option key={m.account} value={m.account}>
                    {m.name || m.login}
                  </option>
                ))}
            </select>
          </label>
        )}
      <PublicationPanel
        workflow={workflow}
        canDeliver={canDeliver}
        onChanged={onRefresh}
        onFeedback={(message) => {
          setActivityOpen(true);
          onFeedback((previous) =>
            previous ? previous + "\n\n" + message : message,
          );
        }}
      />
      <footer className="task-decision">
        <div className="decision-evidence">
          {workflow.candidate ? (
            <>
              <div className="decision-gates">
                {workflow.candidate.gates.map((gate) => (
                  <span key={gate.id} className={gatePresentation(gate).state}>
                    <WorkIcon
                      name={gate.status === "passed" ? "check" : "warning"}
                      size={13}
                    />
                    {gate.label}: {gatePresentation(gate).label}
                  </span>
                ))}
              </div>
              <span className="decision-caption">
                {workflow.status === "applied"
                  ? "Applied to your project."
                  : ready
                    ? workflow.schema_version === "2.0"
                      ? "Approval permits delivery. Choose Apply locally or Publish draft PR separately."
                      : "Approval applies the complete candidate to your project."
                    : approvalHint || "Recorded candidate evidence."}{" "}
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
          {(workflow.status === "approved" ||
            (workflow.schema_version === "2.0" &&
              workflow.status === "needs_attention" &&
              workflow.decision?.action === "approve")) &&
            canDeliver && (
              <button
                className="primary-button"
                disabled={!!busy || !online}
                onClick={() => onAction("apply")}
              >
                {workflow.status === "needs_attention"
                  ? "Retry local application"
                  : "Apply locally"}
              </button>
            )}
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
                  ? workflow.schema_version === "2.0"
                    ? "Approving…"
                    : "Applying…"
                  : run?.status !== "completed"
                    ? "Loading final evidence…"
                    : workflow.schema_version === "2.0"
                      ? "Approve candidate"
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
          ) : ["interrupted", "needs_attention"].includes(workflow.status) &&
            !(
              workflow.schema_version === "2.0" &&
              workflow.decision?.action === "approve"
            ) ? (
            <button
              className="primary-button"
              disabled={!!busy || !online || !canDeliver}
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
                disabled={!!busy || !online || !canDeliver}
                onClick={() => onAction("cancel")}
              >
                Stop task
              </button>
            )}
          {["rejected", "cancelled"].includes(workflow.status) && (
            <button
              className="secondary-button"
              disabled={!!busy || !canDeliver}
              onClick={() => onAgain()}
            >
              Use task again
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
