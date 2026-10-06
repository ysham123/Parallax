import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type KeyboardEvent,
} from "react";
import { ProviderMark } from "./Brand";
import { TaskGraph } from "./TaskGraph";
import {
  getRunAgents,
  eventsForSelection,
  graphTone,
  reviewLabel,
  describeRunEvent,
} from "./run-inspection";
import { LABELS, type Data, type RunEvent, type RunResult } from "./types";

const value = (input: unknown, fallback = "") =>
  typeof input === "string"
    ? input
    : input == null
      ? fallback
      : typeof input === "object"
        ? JSON.stringify(input)
        : String(input);
const human = (input: unknown) =>
  value(input).replaceAll("_", " ").replaceAll("-", " ");
const object = (input: unknown): Data =>
  input && typeof input === "object" && !Array.isArray(input)
    ? (input as Data)
    : {};
const items = (input: unknown): string[] =>
  Array.isArray(input) ? input.map((item) => value(item)) : [];
const terminal = (status: string) =>
  ["completed", "failed", "cancelled", "canceled", "stopped"].includes(status);
const title = (prompt: string) =>
  prompt
    .split(/\n|[.!?]\s+/)[0]
    .replace(/^#+\s*/, "")
    .slice(0, 170);
const reviewState = (review: Data) =>
  review.ok === true
    ? review.task_id
      ? "approved"
      : "completed"
    : review.ok === false
      ? review.task_id
        ? "rejected"
        : "failed"
      : "not reported";
const findingText = (finding: unknown) =>
  typeof finding === "object" && finding
    ? value(
        object(finding).message ||
          object(finding).body ||
          object(finding).description ||
          finding,
      )
    : value(finding);
const project = (path: string) =>
  path.split("/").filter(Boolean).at(-1) || "Project";
const stamp = (time?: string) =>
  time
    ? new Date(time).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Not reported";

function useMedia(query: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(query);
    const change = () => setMatches(media.matches);
    media.addEventListener("change", change);
    change();
    return () => media.removeEventListener("change", change);
  }, [query]);
  return matches;
}
function trapDrawer(
  event: KeyboardEvent,
  container: HTMLElement | null,
  close: () => void,
) {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    close();
    return;
  }
  if (event.key !== "Tab" || !container) return;
  const controls = [
    ...container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], summary, [tabindex="0"]',
    ),
  ].filter(
    (element) => element.tabIndex >= 0 && element.getClientRects().length > 0,
  );
  const first = controls[0],
    last = controls.at(-1);
  if (!first || !last) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function eventSummary(event: RunEvent): string {
  const data = event.data;
  const item = object(data.item);
  const message = object(data.message);
  const tool = object(data.tool);
  const explicit =
    data.summary ||
    data.reason ||
    data.title ||
    (typeof data.message === "string" ? data.message : undefined) ||
    data.status;
  if (explicit) return value(explicit).slice(0, 450);
  if (data.type === "parallax.process_started")
    return "Managed process started";
  if (data.type === "parallax.process_finished")
    return `Managed process finished${data.exit_code != null ? ` · exit ${value(data.exit_code)}` : ""}`;
  if (event.kind === "check")
    return `${value(data.name, "Project check")} · ${data.ok === true ? "passed" : data.ok === false ? "failed" : "recorded"}`;
  if (event.kind === "environment")
    return `${value(data.name, "Private environment")} · ${data.ok === true ? "ready" : "setup reported"}`;
  if (event.kind === "review")
    return `${value(data.provider, "Independent reviewer")} · ${data.ok === true ? "approved" : data.ok === false ? "changes requested" : "review recorded"}`;
  const command = item.command || tool.name || data.tool_name || data.name;
  if (command) return value(command).slice(0, 300);
  const content =
    typeof item.text === "string"
      ? item.text
      : typeof message.content === "string"
        ? message.content
        : typeof data.content === "string"
          ? data.content
          : undefined;
  return content ? content.slice(0, 350) : describeRunEvent(event);
}

function State({ state }: { state: string }) {
  return (
    <span className={`status ${graphTone(state)}`}>
      <i />
      {human(state)}
    </span>
  );
}
function Chevron({ open = false }: { open?: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
      style={{ transform: open ? "rotate(90deg)" : undefined }}
    >
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}
function EventRows({ events }: { events: RunEvent[] }) {
  return events.length ? (
    <>
      {events.length > 100 && (
        <p className="work-empty-note">
          Latest 100 of {events.length} loaded events
        </p>
      )}
      <ol className="work-events">
        {events
          .slice(-100)
          .reverse()
          .map((event) => (
            <li key={event.sequence}>
              <time dateTime={event.timestamp}>{stamp(event.timestamp)}</time>
              <div>
                <span className="work-event-label">
                  {event.data.provider
                    ? LABELS[value(event.data.provider)] ||
                      value(event.data.provider)
                    : human(event.kind)}
                  {event.task_id && <code>{event.task_id}</code>}
                </span>
                <p>{eventSummary(event)}</p>
                <details>
                  <summary>Recorded event #{event.sequence}</summary>
                  <pre>{JSON.stringify(event.data, null, 2)}</pre>
                </details>
              </div>
            </li>
          ))}
      </ol>
    </>
  ) : (
    <p className="work-empty-note">
      No matching events have been reported. Recorded activity appears here when
      the runtime returns it.
    </p>
  );
}

type Props = {
  run: RunResult | null;
  runs: RunResult[];
  events: RunEvent[];
  loading: boolean;
  busy: string;
  streamStatus: string;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onChoose: (id: string) => void;
  onOverlayChange: (open: boolean) => void;
  onNew: () => void;
  onReload: () => void;
  onReview: (section?: "findings" | "changes" | "checks" | "settings") => void;
  onAction: (kind: "pause" | "cancel" | "resume") => void;
  steering: string;
  onSteering: (text: string) => void;
  onSteer: () => void;
  recovery: ReactNode;
  renderTask: (task: Data) => ReactNode;
};

export function RunWorkspace(props: Props) {
  const { run, runs, events, selected, onSelect, loading, busy, streamStatus } =
    props;
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState(
    () => new URLSearchParams(location.search).get("workspace") || "",
  );
  const [view, setView] = useState<"agents" | "tasks" | "list">("agents");
  const [inspectorTab, setInspectorTab] = useState<
    "overview" | "activity" | "changes" | "evidence"
  >("overview");
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [allEvents, setAllEvents] = useState(false);
  const [steerOpen, setSteerOpen] = useState(false);
  const [fullBrief, setFullBrief] = useState(false);
  const inspectorRef = useRef<HTMLElement>(null);
  const selectionTrigger = useRef<HTMLElement | null>(null);
  const agents = useMemo(
    () => (run ? getRunAgents(run, events) : []),
    [run, events],
  );
  const scopedEvents = useMemo(
    () => (run ? eventsForSelection(run, events, selected) : []),
    [run, events, selected],
  );
  const projects = [...new Set(runs.map((item) => item.spec.workspace))];
  const history = runs.filter(
    (item) =>
      (!projectFilter || item.spec.workspace === projectFilter) &&
      (historyFilter === "all" ||
        (historyFilter === "attention"
          ? ["needs_attention", "interrupted", "failed"].includes(item.status)
          : !terminal(item.status) &&
            !["needs_attention", "interrupted"].includes(item.status))) &&
      `${item.spec.prompt} ${item.run_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const agent = agents.find((item) => `agent:${item.key}` === selected);
  const task = run?.tasks.find((item) => value(item.id) === selected);
  const reviewIndex = selected?.startsWith("review:")
    ? Number(selected.slice(7))
    : -1;
  const review = run?.reviews[reviewIndex];
  const lastEvent = events.at(-1);
  const scopedLastEvent = scopedEvents.at(-1);
  const narrow = useMedia("(max-width: 900px)");
  const compactHistory = useMedia("(max-width: 1180px)");
  const inspectionModal = narrow && !!selected;
  const historyModal = compactHistory && historyOpen;
  const historyTrigger = useRef<HTMLElement | null>(null);
  const historyRef = useRef<HTMLElement>(null);
  useEffect(() => {
    props.onOverlayChange(inspectionModal || historyModal);
    return () => props.onOverlayChange(false);
  }, [inspectionModal, historyModal, props.onOverlayChange]);
  useEffect(() => {
    if (historyModal)
      historyRef.current
        ?.querySelector<HTMLButtonElement>(
          'button[aria-label="Close run history"]',
        )
        ?.focus();
  }, [historyModal]);
  useEffect(() => {
    setInspectorTab(selected === "evidence:checks" ? "evidence" : "overview");
  }, [selected]);
  useEffect(() => {
    if (
      inspectionModal &&
      !inspectorRef.current?.contains(document.activeElement)
    ) {
      if (
        !selectionTrigger.current &&
        document.activeElement instanceof HTMLElement
      )
        selectionTrigger.current = document.activeElement;
      inspectorRef.current
        ?.querySelector<HTMLButtonElement>(
          'button[aria-label="Close inspector"]',
        )
        ?.focus();
    }
  }, [inspectionModal]);
  useEffect(() => {
    setFullBrief(false);
    setSteerOpen(false);
  }, [run?.run_id]);
  const inspect = (id: string) => {
    if (!inspectorRef.current?.contains(document.activeElement))
      selectionTrigger.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
    onSelect(id);
    if (window.matchMedia("(max-width: 900px)").matches)
      requestAnimationFrame(() =>
        inspectorRef.current
          ?.querySelector<HTMLButtonElement>(
            'button[aria-label="Close inspector"]',
          )
          ?.focus(),
      );
  };
  const closeInspection = () => {
    onSelect(null);
    requestAnimationFrame(() => selectionTrigger.current?.focus());
  };
  const closeHistory = () => {
    setHistoryOpen(false);
    requestAnimationFrame(() => historyTrigger.current?.focus());
  };
  const toggleHistory = () => {
    historyTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setHistoryOpen(!historyOpen);
  };
  const relevantReviews = run
    ? task
      ? run.reviews.filter((item) => value(item.task_id) === value(task.id))
      : agent
        ? agent.reviews.map((item) => item.review)
        : review
          ? [review]
          : run.reviews
    : [];
  const fileNames = task
    ? items(task.files)
    : agent
      ? [...new Set(agent.tasks.flatMap((item) => items(item.files)))]
      : run?.changed_files || [];
  const taskResult = object(task?.result);
  const matchingChanges = task
    ? items(taskResult.changed_files)
    : agent
      ? [
          ...new Set(
            agent.tasks.flatMap((item) =>
              items(object(item.result).changed_files),
            ),
          ),
        ]
      : run?.changed_files || [];
  const statusLabel = run?.artifacts.integration_applied
    ? "Integrated"
    : run?.artifacts.verified_only
      ? "Verified candidate"
      : human(run?.status || "No run selected");
  const inspectorName = agent
    ? LABELS[agent.participant.provider] || agent.participant.provider
    : task
      ? value(task.title, value(task.id))
      : review
        ? `${LABELS[value(review.provider)] || value(review.provider)} review`
        : selected === "evidence:checks"
          ? "Project checks"
          : "Run overview";

  return (
    <section
      className={`workbench ${historyOpen ? "history-open" : ""} ${selected ? "selection-open" : ""}`}
      aria-label="Agent workspace"
    >
      <aside
        className="work-history"
        aria-label="Run history"
        ref={historyRef}
        role={historyModal ? "dialog" : undefined}
        aria-modal={historyModal || undefined}
        inert={inspectionModal || undefined}
        onKeyDown={(e) => {
          if (historyModal) trapDrawer(e, historyRef.current, closeHistory);
        }}
      >
        <div className="work-history-heading">
          <span>
            Runs{" "}
            <small title={`${runs.length} recorded runs across projects`}>
              {history.length}
            </small>
          </span>
          <button
            className="work-icon-button"
            onClick={props.onReload}
            disabled={loading}
            aria-label="Refresh run history"
          >
            ↻
          </button>
          <button
            className="work-icon-button history-close"
            onClick={closeHistory}
            aria-label="Close run history"
          >
            ×
          </button>
        </div>
        <button className="work-new-button" onClick={props.onNew}>
          <span>+</span> New run{" "}
        </button>
        <label className="sr-only" htmlFor="history-project">
          Filter by project
        </label>
        <select
          id="history-project"
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
        >
          <option value="">All projects</option>
          {projectFilter && !projects.includes(projectFilter) && (
            <option value={projectFilter}>{project(projectFilter)}</option>
          )}
          {projects.map((path) => (
            <option value={path} key={path}>
              {project(path)}
            </option>
          ))}
        </select>
        <input
          aria-label="Search runs"
          placeholder="Search runs…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="work-history-filters" aria-label="Run filters">
          {[
            ["all", "All"],
            ["active", "Active"],
            ["attention", "Attention"],
          ].map(([id, label]) => (
            <button
              key={id}
              aria-pressed={historyFilter === id}
              className={historyFilter === id ? "selected" : ""}
              onClick={() => setHistoryFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="work-history-list">
          {history.map((item) => (
            <button
              key={item.run_id}
              className={`work-history-item ${run?.run_id === item.run_id ? "selected" : ""}`}
              disabled={busy === "open"}
              onClick={() => {
                onSelect(null);
                props.onChoose(item.run_id);
                closeHistory();
              }}
              aria-label={`Open ${human(item.status)} run: ${title(item.spec.prompt)}, ${item.run_id.slice(0, 8)}`}
            >
              <div>
                <span className={`work-run-dot ${graphTone(item.status)}`} />
                <span>{project(item.spec.workspace)}</span>
                <small>{human(item.spec.mode)}</small>
              </div>
              <strong>{title(item.spec.prompt)}</strong>
              <span>
                {item.artifacts.integration_applied
                  ? "Integrated"
                  : human(item.status)}
                <code>{item.run_id.slice(0, 7)}</code>
              </span>
            </button>
          ))}
          {!history.length && (
            <p className="work-empty-note">
              {loading
                ? "Loading runs…"
                : search || historyFilter !== "all" || projectFilter
                  ? "No runs match these filters."
                  : "Your project runs will appear here."}
            </p>
          )}
        </div>
        <div className="work-history-footer">
          Local history<span>Inference through your connections</span>
        </div>
      </aside>
      {historyOpen && (
        <button
          className="work-history-backdrop"
          onClick={closeHistory}
          aria-label="Dismiss run history"
        />
      )}
      <div className="work-surface" inert={historyModal || undefined}>
        <header className="work-header" inert={inspectionModal || undefined}>
          <button
            className="work-icon-button history-toggle"
            onClick={toggleHistory}
            aria-label="Toggle run history"
            aria-expanded={historyOpen}
          >
            ☰
          </button>
          <div className="work-title">
            <div>
              <span>{run ? project(run.spec.workspace) : "Workspace"}</span>
              <span>/</span>
              <code>{run?.run_id.slice(0, 8) || "New run"}</code>
              {run && <State state={statusLabel} />}
            </div>
            <h1>{run ? title(run.spec.prompt) : "Your team’s workspace"}</h1>
          </div>
          <div className="work-actions">
            {run && (
              <>
                <button
                  className="work-button"
                  onClick={() => setSteerOpen(!steerOpen)}
                  aria-expanded={steerOpen}
                  disabled={terminal(run.status)}
                >
                  Steer
                </button>
                {!terminal(run.status) && (
                  <>
                    <button
                      className="work-button"
                      onClick={() =>
                        props.onAction(
                          [
                            "paused",
                            "pausing",
                            "interrupted",
                            "needs_attention",
                          ].includes(run.status)
                            ? "resume"
                            : "pause",
                        )
                      }
                      disabled={!!busy}
                    >
                      {[
                        "paused",
                        "pausing",
                        "interrupted",
                        "needs_attention",
                      ].includes(run.status)
                        ? "Resume"
                        : "Pause"}
                    </button>
                    <button
                      className="work-button work-stop"
                      onClick={() => props.onAction("cancel")}
                      disabled={!!busy}
                    >
                      Stop
                    </button>
                  </>
                )}
                <button
                  className="work-button"
                  onClick={() =>
                    selected === "run" ? closeInspection() : inspect("run")
                  }
                  aria-pressed={selected === "run"}
                >
                  Details
                </button>
                <button
                  className="work-button work-primary"
                  onClick={() => props.onReview()}
                >
                  Review <span>↗</span>
                </button>
              </>
            )}
            <button
              className="work-icon-button work-new-compact"
              onClick={props.onNew}
              aria-label="New run"
            >
              +
            </button>
          </div>
        </header>
        {run ? (
          <>
            {steerOpen && (
              <form
                className="work-steering"
                inert={inspectionModal || undefined}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (props.steering.trim()) props.onSteer();
                }}
              >
                <label htmlFor="workspace-steering">
                  Steer the next checkpoint
                </label>
                <div>
                  <input
                    id="workspace-steering"
                    value={props.steering}
                    onChange={(e) => props.onSteering(e.target.value)}
                    placeholder="Clarify scope, add context, or redirect the plan…"
                  />
                  <button
                    className="work-button work-primary"
                    disabled={!!busy || !props.steering.trim()}
                  >
                    Send
                  </button>
                </div>
                <small>
                  Active attempts keep their current instructions. Guidance is
                  recorded for the coordinator’s next checkpoint.
                </small>
              </form>
            )}
            <div
              className="work-statusline"
              inert={inspectionModal || undefined}
            >
              <span
                className={`work-connection-dot ${streamStatus === "live" ? "live" : ""}`}
              />
              <span>
                {terminal(run.status)
                  ? "Recorded run"
                  : streamStatus === "live"
                    ? "Connected to runtime"
                    : human(streamStatus)}
              </span>
              <span className="work-status-time">
                Last event {stamp(lastEvent?.timestamp)}
              </span>
              <span className="work-status-separator" />
              <span>
                {
                  run.tasks.filter((item) =>
                    /complete|resolved/.test(value(item.status)),
                  ).length
                }
                /{run.tasks.length} tasks
              </span>
              <button
                onClick={() => {
                  inspect("evidence:checks");
                  setInspectorTab("evidence");
                }}
              >
                {run.checks.length
                  ? `${run.checks.filter((item) => item.ok === true).length}/${run.checks.length} checks passed`
                  : "Checks pending"}
              </button>
            </div>
            {props.recovery && (
              <div
                className="work-recovery"
                inert={inspectionModal || undefined}
              >
                {props.recovery}
              </div>
            )}
            <div className="work-area">
              <div
                className="work-canvas-column"
                inert={inspectionModal || undefined}
              >
                <div className="work-roster" aria-label="Configured agents">
                  {agents.map((member) => (
                    <button
                      key={member.key}
                      className={`work-agent ${selected === `agent:${member.key}` ? "selected" : ""}`}
                      onClick={() => inspect(`agent:${member.key}`)}
                      aria-label={`Inspect agent ${LABELS[member.participant.provider] || member.participant.provider}, ${member.coordinator ? "coordinator" : member.roles.join(", ")}`}
                    >
                      <ProviderMark
                        provider={member.participant.provider}
                        size={25}
                      />
                      <span>
                        <strong>
                          {LABELS[member.participant.provider] ||
                            member.participant.provider}
                        </strong>
                        <small>
                          {member.coordinator
                            ? "Coordinator"
                            : member.roles
                                .map((role) => human(role))
                                .join(" · ")}
                        </small>
                      </span>
                      <span className="work-agent-count">
                        {member.tasks.length
                          ? `${member.tasks.length} task${member.tasks.length === 1 ? "" : "s"}`
                          : member.reviews.length
                            ? `${member.reviews.length} review${member.reviews.length === 1 ? "" : "s"}`
                            : member.sessions.length
                              ? "Session recorded"
                              : "No activity recorded"}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="work-canvas-toolbar">
                  <div className="work-view-switch" aria-label="Workspace view">
                    {(
                      [
                        ["agents", "Agent graph"],
                        ["tasks", "Task graph"],
                        ["list", "List"],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        aria-pressed={view === id}
                        className={view === id ? "selected" : ""}
                        onClick={() => setView(id)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <span className="work-graph-caption">
                    {view === "agents"
                      ? "Assignments & recorded evidence"
                      : view === "tasks"
                        ? "Dependencies & repair history"
                        : "All recorded work"}
                  </span>
                </div>
                <div
                  className={`work-canvas ${view === "list" ? "list-view" : ""}`}
                >
                  {view !== "list" ? (
                    <TaskGraph
                      run={run}
                      events={events}
                      tasks={run.tasks}
                      selected={selected}
                      onSelect={inspect}
                      view={view}
                    />
                  ) : (
                    <div
                      className="work-list"
                      aria-label="Accessible agent and task list"
                    >
                      <h2>Agents</h2>
                      {agents.map((member) => (
                        <button
                          key={member.key}
                          className={
                            selected === `agent:${member.key}` ? "selected" : ""
                          }
                          onClick={() => inspect(`agent:${member.key}`)}
                        >
                          <ProviderMark
                            provider={member.participant.provider}
                            size={26}
                          />
                          <span>
                            <strong>
                              {LABELS[member.participant.provider] ||
                                member.participant.provider}
                            </strong>
                            <small>
                              {member.coordinator
                                ? "Coordinator"
                                : member.roles.join(" · ")}{" "}
                              · {member.tasks.length} assigned tasks
                            </small>
                          </span>
                          <Chevron />
                        </button>
                      ))}
                      <h2>
                        Tasks <small>{run.tasks.length}</small>
                      </h2>
                      {run.tasks.map((item) => (
                        <button
                          key={value(item.id)}
                          className={
                            selected === value(item.id) ? "selected" : ""
                          }
                          onClick={() => inspect(value(item.id))}
                        >
                          <ProviderMark
                            provider={value(item.provider)}
                            size={26}
                          />
                          <span>
                            <strong>{value(item.title, value(item.id))}</strong>
                            <small>
                              {items(item.files).length} owned files · attempt{" "}
                              {value(item.attempts, "0")}
                            </small>
                          </span>
                          <State state={value(item.status, "planned")} />
                          <Chevron />
                        </button>
                      ))}
                      {!run.tasks.length && (
                        <p className="work-empty-note">
                          {run.spec.mode === "review"
                            ? "Review runs contain assessment sessions rather than implementation tasks."
                            : "The coordinator has not recorded a task plan yet."}
                        </p>
                      )}
                      <h2>
                        Independent reviews <small>{run.reviews.length}</small>
                      </h2>
                      {run.reviews.map((item, index) => (
                        <button
                          key={index}
                          className={
                            selected === `review:${index}` ? "selected" : ""
                          }
                          onClick={() => inspect(`review:${index}`)}
                        >
                          <ProviderMark
                            provider={value(item.provider)}
                            size={26}
                          />
                          <span>
                            <strong>{reviewLabel(item, index)}</strong>
                            <small>
                              {LABELS[value(item.provider)] ||
                                value(item.provider)}{" "}
                              review
                            </small>
                          </span>
                          <State state={reviewState(item)} />
                          <Chevron />
                        </button>
                      ))}
                      <button onClick={() => inspect("evidence:checks")}>
                        <span className="work-evidence-icon">✓</span>
                        <span>
                          <strong>Project checks</strong>
                          <small>
                            {run.checks.length
                              ? `${run.checks.filter((item) => item.ok === true).length} of ${run.checks.length} passed`
                              : "No checks recorded"}
                          </small>
                        </span>
                        <Chevron />
                      </button>
                    </div>
                  )}
                </div>
                <details
                  className="work-console"
                  open={consoleOpen}
                  onToggle={(e) => setConsoleOpen(e.currentTarget.open)}
                >
                  <summary>
                    <span>
                      <Chevron open={consoleOpen} /> Activity{" "}
                      <small>{scopedEvents.length}</small>
                      {selected && (
                        <span className="work-console-scope">
                          Selected{" "}
                          {agent ? "agent" : task ? "task" : "evidence"}
                        </span>
                      )}
                    </span>
                    <span>
                      {scopedLastEvent
                        ? eventSummary(scopedLastEvent).slice(0, 95)
                        : "Waiting for matching recorded events"}
                    </span>
                  </summary>
                  <div className="work-console-controls">
                    <button
                      className={!allEvents ? "selected" : ""}
                      aria-pressed={!allEvents}
                      onClick={() => setAllEvents(false)}
                    >
                      Milestones
                    </button>
                    <button
                      className={allEvents ? "selected" : ""}
                      aria-pressed={allEvents}
                      onClick={() => setAllEvents(true)}
                    >
                      All recorded events
                    </button>
                    <button onClick={() => onSelect(null)}>
                      Clear selection
                    </button>
                  </div>
                  <EventRows
                    events={
                      allEvents
                        ? scopedEvents
                        : scopedEvents.filter(
                            (item) => item.kind !== "provider",
                          )
                    }
                  />
                </details>
              </div>
              <aside
                className={`work-inspector ${selected ? "open" : ""}`}
                ref={inspectorRef}
                aria-label="Agent and task inspector"
                role={inspectionModal ? "dialog" : undefined}
                aria-modal={inspectionModal || undefined}
                onKeyDown={(e) => {
                  if (inspectionModal)
                    trapDrawer(e, inspectorRef.current, closeInspection);
                  else if (e.key === "Escape") closeInspection();
                }}
              >
                <div className="work-inspector-heading">
                  <span>
                    {agent
                      ? "AGENT"
                      : task
                        ? "TASK"
                        : review
                          ? "INDEPENDENT REVIEW"
                          : selected === "evidence:checks"
                            ? "EVIDENCE"
                            : "RUN"}
                  </span>
                  <button
                    className="work-icon-button"
                    onClick={closeInspection}
                    aria-label="Close inspector"
                  >
                    ×
                  </button>
                </div>
                <div className="work-inspector-title">
                  {agent && (
                    <ProviderMark
                      provider={agent.participant.provider}
                      size={36}
                    />
                  )}
                  <h2>{inspectorName}</h2>
                </div>
                <div
                  className="work-inspector-tabs"
                  role="tablist"
                  aria-label="Inspector sections"
                >
                  {(
                    ["overview", "activity", "changes", "evidence"] as const
                  ).map((id, index, list) => (
                    <button
                      id={`inspector-tab-${id}`}
                      aria-controls="inspector-content"
                      role="tab"
                      aria-selected={inspectorTab === id}
                      tabIndex={inspectorTab === id ? 0 : -1}
                      className={inspectorTab === id ? "selected" : ""}
                      key={id}
                      onClick={() => setInspectorTab(id)}
                      onKeyDown={(e) => {
                        if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                          e.preventDefault();
                          const next =
                            list[
                              (index + (e.key === "ArrowRight" ? 1 : 3)) %
                                list.length
                            ];
                          setInspectorTab(next);
                          requestAnimationFrame(() =>
                            document
                              .getElementById(`inspector-tab-${next}`)
                              ?.focus(),
                          );
                        }
                      }}
                    >
                      {human(id)}
                    </button>
                  ))}
                </div>
                <div
                  className="work-inspector-content"
                  id="inspector-content"
                  role="tabpanel"
                  aria-labelledby={`inspector-tab-${inspectorTab}`}
                >
                  {inspectorTab === "overview" && (
                    <>
                      {agent ? (
                        <>
                          <p className="work-inspector-description">
                            {agent.coordinator
                              ? "Plans the run, assigns work, and requests verification and integration."
                              : agent.participant.role === "reviewer"
                                ? "Independently assesses changes against the requirements and recorded evidence."
                                : "Works on scoped assignments in an isolated workspace."}
                          </p>
                          <dl className="work-properties">
                            <div>
                              <dt>Connection</dt>
                              <dd>
                                {agent.participant.transport === "api"
                                  ? "API inference"
                                  : "Local CLI"}
                              </dd>
                            </div>
                            <div>
                              <dt>Requested model</dt>
                              <dd>
                                {agent.participant.model ||
                                  "Configured account default"}
                              </dd>
                            </div>
                            <div>
                              <dt>Requested effort</dt>
                              <dd>
                                {agent.participant.effort || "Provider default"}
                              </dd>
                            </div>
                            <div>
                              <dt>Effective model</dt>
                              <dd>
                                {value(
                                  agent.effectiveSettings?.model,
                                  "Not reported",
                                )}
                              </dd>
                            </div>
                            <div>
                              <dt>Effective effort</dt>
                              <dd>
                                {value(
                                  agent.effectiveSettings?.effort,
                                  "Not reported",
                                )}
                              </dd>
                            </div>
                            <div>
                              <dt>Last observation</dt>
                              <dd>{stamp(agent.latestEvent?.timestamp)}</dd>
                            </div>
                          </dl>
                          {agent.latestEvent && (
                            <div className="work-observation">
                              <span>LAST REPORTED EVENT</span>
                              <p>{eventSummary(agent.latestEvent)}</p>
                            </div>
                          )}
                          <h3>
                            Assignments <small>{agent.tasks.length}</small>
                          </h3>
                          {agent.tasks.map((item) => (
                            <button
                              className="work-assignment"
                              key={value(item.id)}
                              onClick={() => inspect(value(item.id))}
                            >
                              <span>
                                {value(item.title, value(item.id))}
                                <small>
                                  {items(item.files).join(", ") ||
                                    "No file ownership recorded"}
                                </small>
                              </span>
                              <State state={value(item.status, "planned")} />
                              <Chevron />
                            </button>
                          ))}
                          {!agent.tasks.length && (
                            <p className="work-empty-note">
                              {agent.coordinator
                                ? "Coordinator decisions appear in Activity."
                                : agent.reviews.length
                                  ? "Review evidence is available in Evidence."
                                  : "No implementation assignments recorded."}
                            </p>
                          )}
                          <details>
                            <summary>
                              Provider sessions{" "}
                              <small>{agent.sessions.length}</small>
                            </summary>
                            {agent.sessions.map((session, index) => (
                              <div className="work-session" key={index}>
                                <span>
                                  {human(session.mode)} ·{" "}
                                  {value(session.task_id, "Coordinator")}
                                </span>
                                <code>
                                  {value(
                                    session.session_id,
                                    "Session identity not reported",
                                  )}
                                </code>
                                <small title={value(session.workspace)}>
                                  {value(
                                    session.workspace,
                                    "Workspace not reported",
                                  )}
                                </small>
                              </div>
                            ))}
                          </details>
                        </>
                      ) : task ? (
                        props.renderTask(task)
                      ) : review ? (
                        <>
                          <State state={reviewState(review)} />
                          <p>{value(review.summary || review.answer)}</p>
                          {(Array.isArray(review.findings)
                            ? review.findings
                            : []
                          ).map((finding, index) => (
                            <p key={index}>{findingText(finding)}</p>
                          ))}
                        </>
                      ) : selected === "evidence:checks" ? (
                        <CheckEvidence run={run} />
                      ) : (
                        <>
                          <State state={statusLabel} />
                          <p className="work-inspector-description">
                            {run.summary ||
                              "The coordinator has not returned an outcome yet."}
                          </p>
                          <dl className="work-properties">
                            <div>
                              <dt>Workflow</dt>
                              <dd>{human(run.spec.mode)}</dd>
                            </div>
                            <div>
                              <dt>Team preset</dt>
                              <dd>{run.spec.profile}</dd>
                            </div>
                            <div>
                              <dt>Concurrency</dt>
                              <dd>{run.spec.limits.workers} workers</dd>
                            </div>
                            <div>
                              <dt>Run limit</dt>
                              <dd>{run.spec.limits.minutes} minutes</dd>
                            </div>
                            <div>
                              <dt>Changed files</dt>
                              <dd>{run.changed_files.length}</dd>
                            </div>
                          </dl>
                          <button
                            className="work-disclosure"
                            onClick={() => setFullBrief(!fullBrief)}
                            aria-expanded={fullBrief}
                          >
                            Original task brief <Chevron open={fullBrief} />
                          </button>
                          {fullBrief && (
                            <p className="work-original-brief">
                              {run.spec.prompt}
                            </p>
                          )}
                          <h3>Configured team</h3>
                          {agents.map((member) => (
                            <button
                              key={member.key}
                              className="work-assignment"
                              onClick={() => inspect(`agent:${member.key}`)}
                            >
                              <ProviderMark
                                provider={member.participant.provider}
                                size={22}
                              />
                              <span>
                                {LABELS[member.participant.provider] ||
                                  member.participant.provider}
                                <small>
                                  {member.coordinator
                                    ? "Coordinator"
                                    : member.roles.join(" · ")}
                                </small>
                              </span>
                              <Chevron />
                            </button>
                          ))}
                        </>
                      )}
                    </>
                  )}
                  {inspectorTab === "activity" && (
                    <>
                      <p className="work-empty-note">
                        Recorded events for{" "}
                        {selected ? "this selection" : "the run"}. Tool details
                        depend on what the provider reports.
                      </p>
                      <EventRows events={scopedEvents} />
                    </>
                  )}
                  {inspectorTab === "changes" && (
                    <>
                      <h3>
                        {task || agent ? "Owned files" : "Changed files"}{" "}
                        <small>{fileNames.length}</small>
                      </h3>
                      {fileNames.map((file) => (
                        <div className="work-file" key={file}>
                          <code>{file}</code>
                          <span>
                            {matchingChanges.includes(file)
                              ? "Changed"
                              : "Assigned scope"}
                          </span>
                        </div>
                      ))}
                      {!fileNames.length && (
                        <p className="work-empty-note">
                          No files have been recorded for this selection.
                        </p>
                      )}
                      <button
                        className="work-button"
                        onClick={() => props.onReview("changes")}
                      >
                        Open combined diff ↗
                      </button>
                      <p className="work-empty-note">
                        The combined diff is reviewed against the actual project
                        checks before integration.
                      </p>
                    </>
                  )}
                  {inspectorTab === "evidence" && (
                    <>
                      {selected === "evidence:checks" || !selected ? (
                        <CheckEvidence run={run} />
                      ) : (
                        <>
                          {relevantReviews.map((item, index) => (
                            <article className="work-review" key={index}>
                              <div>
                                <ProviderMark
                                  provider={value(item.provider)}
                                  size={22}
                                />
                                <strong>
                                  {LABELS[value(item.provider)] ||
                                    value(item.provider)}
                                </strong>
                                <State state={reviewState(item)} />
                              </div>
                              <small>{reviewLabel(item, index)}</small>
                              <p>{value(item.summary || item.answer)}</p>
                              {(Array.isArray(item.findings)
                                ? item.findings
                                : []
                              ).map((finding, i) => (
                                <p key={i}>{findingText(finding)}</p>
                              ))}
                            </article>
                          ))}
                          {!relevantReviews.length && (
                            <p className="work-empty-note">
                              No independent review recorded for this selection
                              yet.
                            </p>
                          )}
                          <button
                            className="work-button"
                            onClick={() => inspect("evidence:checks")}
                          >
                            Inspect project checks <Chevron />
                          </button>
                        </>
                      )}
                    </>
                  )}
                </div>
              </aside>
            </div>
          </>
        ) : (
          <div className="work-start">
            <div className="work-start-symbol">⟡</div>
            <span className="eyebrow">PARALLAX WORKSPACE</span>
            <h2>
              {loading
                ? "Connecting to your project…"
                : "Give your team an outcome."}
            </h2>
            <p>
              Follow agents, inspect their assignments, and review the result in
              one workspace.
            </p>
            <button className="work-button work-primary" onClick={props.onNew}>
              New run <span>→</span>
            </button>
            {history.length > 0 && (
              <button
                className="work-button"
                onClick={() => props.onChoose(history[0].run_id)}
              >
                Open latest run
              </button>
            )}
            <span className="work-start-note">
              Codex coordinates · Quality first · Independent review
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

function CheckEvidence({ run }: { run: RunResult }) {
  const baseline = Array.isArray(run.artifacts.baseline_checks)
    ? (run.artifacts.baseline_checks as Data[])
    : [];
  return (
    <>
      <p className="work-empty-note">
        {run.checks.length
          ? "Recorded commands on the combined candidate."
          : "Final checks have not been recorded yet."}
      </p>
      {run.checks.map((check, index) => (
        <details key={index} className="work-check">
          <summary>
            <span>
              {value(check.name, "Project check")}
              <small>{value(check.cwd, ".")}</small>
            </span>
            <State
              state={
                check.ok === true
                  ? "passed"
                  : check.ok === false
                    ? "failed"
                    : "not reported"
              }
            />
          </summary>
          <code>{items(check.argv).join(" ")}</code>
          <pre>{value(check.output, "Output not reported")}</pre>
        </details>
      ))}
      {baseline.length > 0 && (
        <details className="work-baseline">
          <summary>
            Baseline checks{" "}
            <small>
              {baseline.filter((check) => check.ok === false).length} failed
            </small>
          </summary>
          {baseline.map((check, index) => (
            <div key={index}>
              <span>{value(check.name)}</span>
              <State state={check.ok === true ? "passed" : "failed"} />
            </div>
          ))}
        </details>
      )}
      <p className="work-empty-note">
        Only reported results appear here. Review includes the verification
        record and preservation gates.
      </p>
    </>
  );
}
