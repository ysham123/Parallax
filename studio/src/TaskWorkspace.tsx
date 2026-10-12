import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiUrl, messageOf, viaMachine } from "./api";
import { PublicationPanel } from "./PublicationPanel";
import "./task.css";
import { ProviderMark } from "./Brand";
import { eventSummary } from "./run-inspection";
import { parseDiff, type DiffFile } from "./diff-model";
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
import {
  workflowCanResume,
  workflowGroup,
  workflowLabels,
} from "./workflow-state";
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
  runEvidenceRead,
} from "./evidence-presentation";

const text = (v: unknown, fallback = "") =>
  v == null ? fallback : typeof v === "string" ? v : JSON.stringify(v);
const clock = (at: string) =>
  new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const label = (v: string) => v.replaceAll("_", " ");

type EvidenceTab = "changes" | "checks" | "findings" | "settings";

/** Display-only: unknown or incomplete patches keep every recorded row visible. */
export function collapsiblePatchHeaders(file?: DiffFile): number[] {
  if (!file) return [];
  const firstHunk = file.lines.findIndex((line) => line.kind === "hunk");
  if (firstHunk < 1) return [];
  const prefix = file.lines.slice(0, firstHunk);
  const fileHeaders = /^index /.test(prefix[1]?.text || "")
    ? prefix.slice(2)
    : prefix.slice(1);
  if (
    !/^diff --git ("(?:[^"\\]|\\.)+"|a\/.+?) ("(?:[^"\\]|\\.)+"|b\/.+)$/.test(
      prefix[0].text,
    ) ||
    fileHeaders.length !== 2 ||
    !/^--- (?:a\/.+|\/dev\/null|"a\/(?:[^"\\]|\\.)+")$/.test(
      fileHeaders[0].text,
    ) ||
    !/^\+\+\+ (?:b\/.+|\/dev\/null|"b\/(?:[^"\\]|\\.)+")$/.test(
      fileHeaders[1].text,
    ) ||
    !prefix.every(
      (line, i) =>
        line.kind === "meta" &&
        (i === 0 ||
          /^index [a-f0-9]+\.\.[a-f0-9]+(?: [0-7]{6})?$/.test(line.text) ||
          line.text.startsWith("--- ") ||
          line.text.startsWith("+++ ")),
    )
  )
    return [];
  let oldRemaining = 0,
    newRemaining = 0,
    seenHunk = false,
    seenContent = false;
  for (const line of file.lines.slice(firstHunk)) {
    if (line.kind === "hunk") {
      if (seenHunk && (oldRemaining !== 0 || newRemaining !== 0)) return [];
      const header = line.text.match(
        /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/,
      );
      if (!header) return [];
      const numbers = [
        header[1],
        header[2] ?? "1",
        header[3],
        header[4] ?? "1",
      ].map(Number);
      if (!numbers.every((n) => Number.isSafeInteger(n) && n >= 0)) return [];
      if (
        (numbers[0] === 0 && numbers[1] > 0) ||
        (numbers[2] === 0 && numbers[3] > 0)
      )
        return [];
      oldRemaining = numbers[1];
      newRemaining = numbers[3];
      seenHunk = true;
    } else if (line.kind === "context") {
      oldRemaining--;
      newRemaining--;
      seenContent = true;
    } else if (line.kind === "addition") {
      newRemaining--;
      seenContent = true;
    } else if (line.kind === "deletion") {
      oldRemaining--;
      seenContent = true;
    } else if (line.text !== "\\ No newline at end of file") return [];
    if (oldRemaining < 0 || newRemaining < 0) return [];
  }
  return seenContent && oldRemaining === 0 && newRemaining === 0
    ? prefix.map((_, i) => i)
    : [];
}

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
  measurements,
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
  measurements?: ReactNode;
}) {
  const [selectedFindings, setSelectedFindings] = useState<
    { review: number; finding: number }[]
  >([]);
  const [runSnapshot, setRunSnapshot] = useState<{
    identity: string;
    value: RunResult;
  } | null>(null);
  const [eventSnapshot, setEventSnapshot] = useState<{
    identity: string;
    values: RunEvent[];
  } | null>(null);
  const [readSnapshot, setReadSnapshot] = useState<{
    identity: string;
    loading: boolean;
    error: string;
  } | null>(null);
  const [tab, setTab] = useState<EvidenceTab>("changes");
  const [measurementsStarted, setMeasurementsStarted] = useState(false);
  const [filePath, setFilePath] = useState("");
  const [fileQuery, setFileQuery] = useState("");
  const [diffPage, setDiffPage] = useState(0);
  const [showPatchHeaders, setShowPatchHeaders] = useState(false);
  const [findingTarget, setFindingTarget] = useState<FindingDestination | null>(
    null,
  );
  const codeRef = useRef<HTMLDivElement>(null);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const retryReturn = useRef<{
    identity: string;
    opener: HTMLButtonElement;
  } | null>(null);
  const [activityOpen, setActivityOpen] = useState(() => {
    try {
      return localStorage.getItem("parallax-task-activity") === "open";
    } catch {
      return false;
    }
  });
  const [correctionOpen, setCorrectionOpen] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem(
        "parallax-task-activity",
        activityOpen ? "open" : "closed",
      );
    } catch {
      /* Disclosure remains usable with browser storage disabled. */
    }
  }, [activityOpen]);
  const [stream, setStream] = useState("connecting");
  const [revision, setRevision] = useState(0);
  const lastEvent = useRef(0);
  const runId = workflow.run_id;
  const evidenceIdentity = JSON.stringify([
    workflow.id,
    runId,
    workflow.candidate?.digest,
    viewerActor,
  ]);
  const eventIdentity = JSON.stringify([workflow.id, runId, viewerActor]);
  const identityRef = useRef(evidenceIdentity);
  identityRef.current = evidenceIdentity;
  const run =
    runSnapshot?.identity === evidenceIdentity ? runSnapshot.value : null;
  const events =
    eventSnapshot?.identity === eventIdentity ? eventSnapshot.values : [];
  const read =
    readSnapshot?.identity === evidenceIdentity ? readSnapshot : null;
  const error = read?.error || "";
  const evidenceRead = runEvidenceRead({
    requested: !!runId,
    online,
    loaded: !!run,
    loading: read?.loading ?? true,
    error,
  });
  useEffect(() => {
    const pending = retryReturn.current;
    if (!pending) return;
    if (!visible || !online || pending.identity !== evidenceIdentity) {
      retryReturn.current = null;
      return;
    }
    if (error || read?.loading || !run) return;
    retryReturn.current = null;
    const frame = requestAnimationFrame(() => {
      if (identityRef.current !== pending.identity) return;
      const focused = document.activeElement;
      if (focused && focused !== document.body && focused !== pending.opener)
        return;
      const target = document.getElementById(`evidence-tab-${tab}`);
      if (
        target?.getClientRects().length &&
        !target.closest("[hidden], [inert]")
      )
        target.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [evidenceIdentity, visible, online, error, read?.loading, run, tab]);
  useEffect(() => {
    setSelectedFindings([]);
    setFindingTarget(null);
  }, [evidenceIdentity]);
  useEffect(() => {
    lastEvent.current = 0;
  }, [eventIdentity]);
  useEffect(() => {
    if (!online) {
      setStream("offline");
      return;
    }
    if (!runId || !visible) return;
    const abort = new AbortController();
    let fetching = false;
    const load = async () => {
      if (fetching || abort.signal.aborted) return;
      fetching = true;
      setReadSnapshot((previous) => ({
        identity: evidenceIdentity,
        loading: true,
        error: previous?.identity === evidenceIdentity ? previous.error : "",
      }));
      try {
        const result = await api<RunResult>(`/runs/${runId}`, {
          signal: abort.signal,
        });
        if (!abort.signal.aborted && identityRef.current === evidenceIdentity) {
          if (result.run_id !== runId)
            throw new Error("Returned run evidence does not match this task.");
          const retry = retryButtonRef.current;
          if (retry && document.activeElement === retry)
            retryReturn.current = { identity: evidenceIdentity, opener: retry };
          setRunSnapshot({ identity: evidenceIdentity, value: result });
          setReadSnapshot({
            identity: evidenceIdentity,
            loading: false,
            error: "",
          });
        }
      } catch (failure) {
        if (!abort.signal.aborted && identityRef.current === evidenceIdentity)
          setReadSnapshot({
            identity: evidenceIdentity,
            loading: false,
            error: messageOf(failure),
          });
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
          abort.signal.aborted ||
          identityRef.current !== evidenceIdentity ||
          !next.kind ||
          next.run_id !== runId ||
          next.sequence <= lastEvent.current
        )
          return;
        lastEvent.current = next.sequence;
        setEventSnapshot((previous) => ({
          identity: eventIdentity,
          values: [
            ...(previous?.identity === eventIdentity ? previous.values : []),
            next,
          ].slice(-500),
        }));
      } catch {
        setStream("reconnecting");
      }
    };
    return () => {
      abort.abort();
      window.clearInterval(timer);
      source.close();
    };
  }, [evidenceIdentity, eventIdentity, revision, visible, online]);
  const files = useMemo(() => parseDiff(run?.diff || ""), [run?.diff]);
  const visibleFiles = files.filter((file) =>
    file.path.toLowerCase().includes(fileQuery.toLowerCase()),
  );
  const activeFile =
    visibleFiles.find((file) => file.path === filePath) || visibleFiles[0];
  const headerRows = useMemo(
    () => new Set(collapsiblePatchHeaders(activeFile)),
    [activeFile],
  );
  useEffect(
    () => setShowPatchHeaders(false),
    [activeFile?.path, runId, workflow.candidate?.digest],
  );
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
  const recordedReviewState = reviewPresentation(currentReview || {});
  const lastLoaded = !!run && (!online || !!error);
  const showReadNotice =
    evidenceRead.state !== "available" &&
    (evidenceRead.state !== "refreshing" || !!error);
  const finalReviewState = run
    ? {
        ...recordedReviewState,
        label: `${lastLoaded ? "Last loaded: " : ""}${recordedReviewState.label}`,
      }
    : {
        state:
          evidenceRead.state === "loading"
            ? "loading"
            : evidenceRead.state === "unrecorded"
              ? "unrecorded"
              : "unavailable",
        label:
          evidenceRead.state === "loading"
            ? "Loading review evidence"
            : evidenceRead.state === "unrecorded"
              ? "Unrecorded"
              : "Review evidence unavailable",
        detail: evidenceRead.detail,
      };
  const delivery = workflow.delivery;
  const changedFileCount =
    workflow.candidate?.changed_files?.length ?? run?.changed_files?.length;
  const materialDelivery =
    !!workflow.publication ||
    ["applied", "published", "approved", "applying"].includes(
      workflow.status,
    ) ||
    (!!delivery?.local && delivery.local !== "pending") ||
    (!!delivery?.github && delivery.github !== "pending");
  const unbound = [
    ...currentChecks,
    ...(currentReview ? [currentReview] : []),
  ].filter((row) => !observationOf(row)).length;
  const uncertainGates = (workflow.candidate?.gates || []).filter(
    (gate) => gatePresentation(gate).state !== "passed",
  );
  const usageReports = Array.isArray(run?.usage?.reports)
    ? run.usage.reports
    : [];
  const resumable = workflowCanResume(
    workflow.status,
    run && run.run_id === runId ? run.status : workflow.run_status,
    workflow.schema_version === "2.0" && decision?.action === "approve",
  );
  const recordedCheckLabel = currentChecks.length
    ? Object.entries(checkOutcomes)
        .filter(([, count]) => count > 0)
        .map(([state, count]) => `${count} ${state}`)
        .join(" · ")
    : "No current final checks recorded";
  const finalCheckLabel = run
    ? `${lastLoaded ? "Last loaded: " : ""}${recordedCheckLabel}`
    : evidenceRead.state === "loading"
      ? "Loading check evidence"
      : evidenceRead.state === "unrecorded"
        ? "No run evidence recorded"
        : "Check evidence unavailable";
  const changedFileLabel =
    typeof changedFileCount === "number"
      ? `${changedFileCount} ${changedFileCount === 1 ? "file" : "files"}`
      : !run && evidenceRead.state === "loading"
        ? "Loading change evidence"
        : !run && evidenceRead.state === "unavailable"
          ? "Change evidence unavailable"
          : "Changes unrecorded";
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
  const followup = (
    <div className="task-followup">
      <label htmlFor="task-feedback">
        {active ? "Direct the team" : "Follow up on this task"}
      </label>
      {selectedFindings.length > 0 && (
        <p className="revision-selection-note">
          {selectedFindings.length} review finding
          {selectedFindings.length === 1 ? "" : "s"} selected for a candidate
          revision.
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
              disabled={!!busy || !online || !feedback.trim() || !canDeliver}
              onClick={() => onRevise(selectedFindings)}
            >
              {busy === "revise" ? "Starting revision…" : "Revise candidate"}
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
  );
  const baselineRows = Array.isArray(run?.artifacts?.baseline_checks)
    ? (run!.artifacts.baseline_checks as Record<string, unknown>[])
    : [];
  const baselineCounts = checkCounts(baselineRows);
  const loadingEvidence = !run && evidenceRead.state === "loading";
  const ledger: {
    name: string;
    value: ReactNode;
    state:
      | "passed"
      | "failed"
      | "attention"
      | "waiting"
      | "pending"
      | "running";
    tab?: EvidenceTab;
  }[] = [
    {
      name: "Baseline checks",
      value: run
        ? baselineRows.length
          ? Object.entries(baselineCounts)
              .filter(([, count]) => count > 0)
              .map(([state, count]) => `${count} ${state}`)
              .join(", ")
          : "Not recorded"
        : loadingEvidence
          ? "Loading"
          : "Unavailable",
      state: loadingEvidence
        ? "running"
        : baselineCounts.failed || baselineCounts.unavailable
          ? "attention"
          : baselineRows.length
            ? "passed"
            : "pending",
      tab: "checks",
    },
    {
      name: "Changes",
      value: changedFileLabel,
      state: workflow.candidate ? "passed" : active ? "running" : "pending",
      tab: "changes",
    },
    {
      name: "Independent review",
      value: finalReviewState.label,
      state:
        finalReviewState.state === "passed"
          ? "passed"
          : finalReviewState.state === "failed"
            ? "failed"
            : finalReviewState.state === "loading"
              ? "running"
              : finalReviewState.state === "unavailable"
                ? "attention"
                : "pending",
      tab: "findings",
    },
    {
      name: "Final checks",
      value: finalCheckLabel,
      state: loadingEvidence
        ? "running"
        : checkOutcomes.failed
          ? "failed"
          : checkOutcomes.unavailable
            ? "attention"
            : currentChecks.length && checkOutcomes.passed
              ? "passed"
              : "pending",
      tab: "checks",
    },
    {
      name: "Human decision",
      value:
        decision?.action === "approve"
          ? "Approved"
          : decision?.action === "reject"
            ? "Declined"
            : workflow.status === "awaiting_approval"
              ? "Awaiting approval"
              : "No recorded decision",
      state:
        decision?.action === "approve"
          ? "passed"
          : decision?.action === "reject"
            ? "failed"
            : workflow.status === "awaiting_approval"
              ? "waiting"
              : "pending",
    },
    {
      name: "Local delivery",
      value:
        delivery?.local === "applied" || workflow.status === "applied"
          ? "Applied"
          : delivery?.local === "pending"
            ? "Not applied"
            : delivery?.local
              ? label(delivery.local)
              : workflow.schema_version === "2.0"
                ? "Unrecorded"
                : "Legacy combined approval and application",
      state:
        delivery?.local === "applied" || workflow.status === "applied"
          ? "passed"
          : "pending",
    },
    {
      name: "GitHub delivery",
      value: workflow.publication
        ? "Draft PR published"
        : delivery?.github === "pending"
          ? "Not published"
          : delivery?.github
            ? label(delivery.github)
            : "Unrecorded",
      state: workflow.publication ? "passed" : "pending",
    },
  ];
  return (
    <section className="task-workspace" aria-labelledby="selected-task-title">
      <header className="task-titlebar">
        <div className="task-title-context">
          <span className="task-project" title={workflow.workspace}>
            {selectedProject}
          </span>
          <span className={`workflow-status ${workflowGroup(workflow.status)}`}>
            {workflowLabels[workflow.status] || label(workflow.status)}
          </span>
        </div>
        <h1 id="selected-task-title" tabIndex={-1}>
          {workflow.title}
        </h1>
        <p className="task-byline">
          <span>
            {requestLabel(workflow.requester, viewerActor) === "Your request"
              ? "Your request"
              : `Requested by ${human(workflow.requester)}`}
          </span>
          <time dateTime={workflow.created_at}>
            {recordedTime(workflow.created_at)}
          </time>
          <span>
            {workflow.reviewer
              ? `Reviewer: ${human(workflow.reviewer)}`
              : "No reviewer assigned"}
          </span>
        </p>
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
      </header>
      {workflow.error && (
        <div className="task-alert" role="alert">
          <WorkIcon name="warning" />
          <p>{workflow.error}</p>
        </div>
      )}
      {error && (
        <div className="task-alert" role="alert">
          <p>
            {run ? "Evidence refresh failed" : "Evidence unavailable"}: {error}
          </p>
          <button
            ref={retryButtonRef}
            className="text-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      <div className="task-decision">
        <div className="decision-evidence">
          <h2 className="next-action-title">Next action</h2>
          {!online && (
            <p className="decision-blocker">
              Reconnect the worker before approving or delivering this
              candidate.
            </p>
          )}
          {workflow.status === "published" && (
            <p className="decision-blocker">
              Draft PR published. Inspect GitHub checks and review feedback
              below.
            </p>
          )}
          {["interrupted", "needs_attention"].includes(workflow.status) &&
            !resumable &&
            decision?.action !== "approve" && (
              <p className="decision-blocker">
                This execution cannot resume. Inspect the failure, then start a
                fresh task from the current project.
              </p>
            )}
          {workflow.candidate ? (
            <>
              <span className="decision-caption">
                {workflow.status === "applied"
                  ? "Applied to your project."
                  : ready
                    ? workflow.schema_version === "2.0"
                      ? "Approve this candidate to permit delivery."
                      : "Approval applies the complete candidate to your project."
                    : workflow.status === "approved"
                      ? "Approval recorded. Apply locally or inspect GitHub delivery below."
                      : workflow.status === "published"
                        ? "Draft PR delivery recorded; inspect its checks and feedback below."
                        : approvalHint || "Recorded candidate evidence."}{" "}
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
          {canDeliver &&
            ["interrupted", "needs_attention"].includes(workflow.status) &&
            !resumable &&
            decision?.action !== "approve" && (
              <button
                className="primary-button"
                disabled={!!busy || !online}
                onClick={() => onAgain()}
              >
                New task from current project
              </button>
            )}
          {canDeliver &&
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
                onClick={() => {
                  setCorrectionOpen(true);
                  setActivityOpen(false);
                  requestAnimationFrame(() =>
                    document.getElementById("task-feedback")?.focus(),
                  );
                }}
              >
                Request revision
              </button>
            )}
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
          ) : resumable ? (
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
      </div>
      <div className={`task-layout ${activityOpen ? "with-activity" : ""}`}>
        <section
          className="candidate-summary"
          aria-labelledby="candidate-summary-title"
        >
          <h2 id="candidate-summary-title" className="ledger-title">
            Evidence
            {workflow.candidate?.digest && (
              <code title={workflow.candidate.digest}>
                {workflow.candidate.digest.slice(0, 12)}
              </code>
            )}
          </h2>
          <dl className="candidate-summary-facts">
            {ledger.map((fact) => (
              <div key={fact.name} className={`ledger-fact ${fact.state}`}>
                <i className={`fact-dot ${fact.state}`} aria-hidden="true" />
                <dt>{fact.name}</dt>
                <dd>
                  {fact.tab ? (
                    <button
                      className={`ledger-link ${fact.name === "Independent review" ? `evidence-outcome ${finalReviewState.state}` : ""}`}
                      onClick={() => setTab(fact.tab!)}
                    >
                      {fact.value}
                    </button>
                  ) : (
                    fact.value
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {(showReadNotice ||
            !currentChecks.length ||
            finalReviewState.state !== "passed" ||
            !!unbound ||
            uncertainGates.length > 0 ||
            !!error) && (
            <div className="candidate-uncertainty">
              {showReadNotice && <p role="status">{evidenceRead.detail}</p>}
              {!!run && !currentChecks.length && (
                <p>
                  No current final command evidence is recorded.
                  {!!run?.checks.length &&
                    " Previous check outcomes remain in Checks; their association with this verification attempt is unrecorded or historical."}
                </p>
              )}
              {!!run && finalReviewState.state !== "passed" && (
                <p>{finalReviewState.detail}</p>
              )}
              {!!unbound && (
                <p>
                  Artifact binding is unrecorded for {unbound} final observation
                  {unbound === 1 ? "" : "s"}. Older records do not establish
                  exact workspace provenance.
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
            </div>
          )}
          <div className="candidate-record-summary">
            <h3>Summary</h3>
            <p>
              {workflow.candidate?.summary ||
                run?.summary ||
                (!run && evidenceRead.state === "loading"
                  ? "Loading saved run evidence…"
                  : !run && evidenceRead.state === "unavailable"
                    ? "The saved run result is unavailable."
                    : "No candidate result has been recorded yet.")}
            </p>
            {(workflow.candidate?.summary || run?.summary) && (
              <small>
                Written by the agents. The evidence above is what was recorded.
              </small>
            )}
          </div>
          <details className="candidate-run-details">
            <summary>Record details</summary>
            <dl className="candidate-record-facts">
              <div>
                <dt>Project</dt>
                <dd>
                  <code>{workflow.workspace}</code>
                </dd>
              </div>
              <div>
                <dt>Recipe</dt>
                <dd>
                  {workflow.template.name} v{workflow.template.version}
                </dd>
              </div>
              {workflow.candidate && (
                <div>
                  <dt>Candidate digest</dt>
                  <dd>
                    <code>{workflow.candidate.digest}</code>
                  </dd>
                </div>
              )}
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
                      {human(decision.actor)}{" "}
                      <time dateTime={decision.at || undefined}>
                        {recordedTime(decision.at)}
                      </time>
                    </>
                  ) : (
                    "No decision recorded"
                  )}
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
                  {!run && evidenceRead.state === "loading"
                    ? "Loading usage evidence; cost unknown"
                    : !run && evidenceRead.state === "unavailable"
                      ? "Usage evidence unavailable; cost unknown"
                      : usageReports.length
                        ? `${usageReports.length} usage reports; total cost unknown`
                        : "Usage unreported; cost unknown"}
                </dd>
              </div>
            </dl>
            {workflow.candidate && workflow.candidate.gates.length > 0 && (
              <div
                className="decision-gates"
                aria-label="Candidate acceptance gates"
              >
                {workflow.candidate.gates.map((gate) => (
                  <span key={gate.id} className={gatePresentation(gate).state}>
                    <i
                      className={`fact-dot ${gatePresentation(gate).state === "passed" ? "passed" : gatePresentation(gate).state === "failed" ? "failed" : "attention"}`}
                      aria-hidden="true"
                    />
                    {gate.label}: {gatePresentation(gate).label}
                  </span>
                ))}
              </div>
            )}
            <p>
              Checks establish only their recorded coverage. Review is separate
              from human approval; approval is separate from delivery.
            </p>
          </details>
          <div className="candidate-links">
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
            {runId && (
              <button className="text-button" onClick={() => onInspect(runId)}>
                Open agent graph
              </button>
            )}
          </div>
          {workflow.status === "awaiting_approval" &&
            members.length > 0 &&
            canDeliver && (
              <label className="assign-reviewer">
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
        </section>
        <div className="task-main-column">
          {workflow.github_target &&
            ["approved", "published"].includes(workflow.status) && (
              <details
                className="task-delivery"
                open={workflow.status === "approved"}
              >
                <summary>GitHub delivery and feedback</summary>
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
              </details>
            )}
          <div
            className={`task-panels ${activityOpen ? "" : "activity-hidden"}`}
          >
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
                                  task.status === "completed"
                                    ? "check"
                                    : "activity"
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
                {followup}
              </div>
            )}
            <div className="task-evidence">
              <div className="evidence-tabbar">
                <div
                  className="evidence-tabs"
                  role="tablist"
                  aria-label="Task evidence"
                >
                  {[
                    [
                      "changes",
                      "Changes",
                      "code",
                      run ? files.length : undefined,
                    ],
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
                        document
                          .getElementById(`evidence-tab-${ids[next]}`)
                          ?.focus();
                      }}
                      onClick={() => setTab(id as EvidenceTab)}
                    >
                      <WorkIcon name={String(icon)} size={15} />
                      {name}
                      {typeof count === "number" && <small>{count}</small>}
                    </button>
                  ))}
                </div>
                <button
                  className="activity-toggle"
                  aria-label={
                    activityOpen ? "Hide task activity" : "Show task activity"
                  }
                  aria-pressed={activityOpen}
                  onClick={() => setActivityOpen(!activityOpen)}
                >
                  <WorkIcon name="activity" size={15} />
                  Activity
                </button>
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
                {tab === "settings" ? null : tab === "changes" ? (
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
                      <div
                        className={`diff-workspace ${files.length === 1 && activeFile ? "single-file" : ""}`}
                      >
                        <aside
                          className="diff-files"
                          aria-label="Changed files"
                        >
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
                              {headerRows.size > 0 && currentPage === 0 ? (
                                <button
                                  className="text-button patch-header-toggle"
                                  aria-expanded={showPatchHeaders}
                                  onClick={() =>
                                    setShowPatchHeaders((previous) => !previous)
                                  }
                                >
                                  {showPatchHeaders
                                    ? "Hide patch headers"
                                    : "Show patch headers"}
                                </button>
                              ) : (
                                <span>Unified diff</span>
                              )}
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
                                    .map((line, i) =>
                                      !showPatchHeaders &&
                                      headerRows.has(
                                        currentPage * pageSize + i,
                                      ) ? null : (
                                        <tr
                                          key={i}
                                          data-patch-row={
                                            currentPage * pageSize + i
                                          }
                                          tabIndex={
                                            findingTarget?.path ===
                                              activeFile.path &&
                                            findingTarget.row ===
                                              currentPage * pageSize + i
                                              ? -1
                                              : undefined
                                          }
                                          className={`patch-${line.kind}${findingTarget?.path === activeFile.path && findingTarget.row === currentPage * pageSize + i ? " finding-target" : ""}`}
                                        >
                                          <td className="line-number">
                                            {line.old}
                                          </td>
                                          <td className="line-number">
                                            {line.next}
                                          </td>
                                          <td className="code-line">
                                            <pre>{line.text || " "}</pre>
                                          </td>
                                        </tr>
                                      ),
                                    )}
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
                            <article
                              className="review-report"
                              key={reviewIndex}
                            >
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
                                <p className="inline-error">
                                  {text(review.error)}
                                </p>
                              )}
                              {(Array.isArray(review.findings)
                                ? review.findings
                                : []
                              ).map((raw, findingIndex) => {
                                const finding = normalizeFinding(
                                  raw,
                                  findingIndex,
                                );
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
                                                      f.review ===
                                                        reviewIndex &&
                                                      f.finding ===
                                                        findingIndex,
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
                                                      f.review !==
                                                        reviewIndex ||
                                                      f.finding !==
                                                        findingIndex,
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
                              A candidate without findings still requires
                              recorded independent review and a human decision.
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
                <div
                  className="evidence-scroll task-details-pane"
                  hidden={tab !== "settings"}
                >
                  {tab === "settings" &&
                    (run ? (
                      renderEvidence(run, "settings")
                    ) : (
                      <p className="workflow-muted">
                        {error
                          ? "Run details are unavailable. Retry the connection above."
                          : "Waiting for run details…"}
                      </p>
                    ))}
                  {measurements && (
                    <details
                      className="task-measurements"
                      onToggle={(event) => {
                        if (event.currentTarget.open)
                          setMeasurementsStarted(true);
                      }}
                    >
                      <summary>
                        Pilot measurements and human assessments
                        <span className="measurement-task-context">
                          {workflow.title}
                        </span>
                      </summary>
                      {measurementsStarted && measurements}
                    </details>
                  )}
                </div>
              </div>
            </div>
          </div>
          {!activityOpen && (
            <details
              className="task-correction"
              open={correctionOpen || selectedFindings.length > 0}
            >
              <summary>
                {canDeliver
                  ? "Request a correction or new task"
                  : "Comment on this task"}
              </summary>
              {followup}
            </details>
          )}
        </div>
      </div>
    </section>
  );
}
