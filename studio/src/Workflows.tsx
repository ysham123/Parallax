import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, messageOf, viaMachine } from "./api";
import {
  LABELS,
  type CheckSpec,
  type Participant,
  type RunSpec,
} from "./types";
import { canApprove, workflowGroup, workflowLabels } from "./workflow-state";
import { TaskPreflight, type TaskAssessment } from "./TaskPreflight";
import { TaskWorkspace } from "./TaskWorkspace";
import { WorkIcon } from "./WorkIcon";
import "./workflows.css";

type Recipe = Pick<RunSpec, "coordinator" | "team" | "limits" | "checks"> & {
  id: string;
  version: number;
  name: string;
  description: string;
  instructions: string;
  builtin?: boolean;
};
type Candidate = {
  digest: string;
  changed_files: string[];
  check_count: number;
  summary: string;
  gates: { id: string; label: string; status: string; detail: string }[];
};
export type Workflow = {
  id: string;
  title: string;
  prompt?: string;
  original_goal?: string;
  parent_workflow_id?: string | null;
  template_details?: Pick<
    Recipe,
    "id" | "version" | "name" | "description" | "instructions"
  >;
  status: string;
  stage: string;
  workspace: string;
  template: Pick<Recipe, "id" | "version" | "name">;
  created_at: string;
  updated_at: string;
  run_id?: string;
  run_status?: string;
  runtime_seconds?: number;
  summary?: string;
  error?: string;
  candidate?: Candidate;
  spec?: RunSpec;
  decision?: { action: string };
  timeline?: { stage: string; at: string }[];
};

const shortProject = (path: string) =>
  path.replace(/\/$/, "").split("/").pop() || "Choose a project";
const when = (value: string) =>
  new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export function Workflows({
  active,
  workspace,
  onWorkspace,
  online,
  onInspect,
  onConnections,
  knownProjects,
  renderEvidence,
  renderParticipant,
  renderCheck,
}: {
  active: boolean;
  knownProjects: string[];
  renderEvidence: (
    run: import("./types").RunResult,
    tab: "checks" | "findings" | "settings",
  ) => ReactNode;
  workspace: string;
  onWorkspace: (value: string) => void;
  online: boolean;
  onInspect: (id: string) => void;
  onConnections: () => void;
  renderParticipant: (
    member: Participant,
    change: (value: Participant) => void,
    coordinator: boolean,
  ) => ReactNode;
  renderCheck: (
    check: CheckSpec,
    index: number,
    change: (value: CheckSpec) => void,
    remove: () => void,
    validity: (valid: boolean) => void,
  ) => ReactNode;
}) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [history, setHistory] = useState<Workflow[]>([]);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const selectedId = useRef<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [team, setTeam] = useState<Participant[]>([]);
  const [coordinator, setCoordinator] = useState<Participant | null>(null);
  const [recipeName, setRecipeName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [checks, setChecks] = useState<CheckSpec[]>([]);
  const [invalidChecks, setInvalidChecks] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [readiness, setReadiness] = useState<TaskAssessment | null>(null);
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [composing, setComposing] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [parentTask, setParentTask] = useState<Workflow | null>(null);
  const taskWorkspace = parentTask?.workspace || workspace;
  const [sendingTasks, setSendingTasks] = useState<Set<string>>(new Set());
  const sendingRef = useRef(new Set<string>());
  const [sendNotices, setSendNotices] = useState<Record<string, string>>({});
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<string, string>>(
    {},
  );
  const firstLoad = useRef(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const pendingStart = useRef<{ signature: string; id: string } | null>(null);
  const alive = useRef(true);
  const activeRef = useRef(active);
  activeRef.current = active;
  const assessmentKey = JSON.stringify([
    taskWorkspace,
    coordinator,
    team,
    checks,
    parentTask?.spec?.package_roots,
  ]);
  const assessmentKeyRef = useRef(assessmentKey);
  assessmentKeyRef.current = assessmentKey;

  const chooseRecipe = useCallback((value: Recipe) => {
    setRecipe(value);
    setCoordinator(structuredClone(value.coordinator));
    setTeam(structuredClone(value.team));
    setMinutes(value.limits.minutes);
    setInstructions(value.instructions);
    setChecks(structuredClone(value.checks));
    setInvalidChecks(new Set());
    setRecipeName("");
    setReadiness(null);
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const rows = await api<Workflow[]>("/workflows", { signal });
    if (!alive.current || signal?.aborted) return;
    setHistory(rows);
    if (firstLoad.current) {
      const deepLink = new URLSearchParams(location.hash.slice(1)).get("task");
      const linkedId =
        deepLink &&
        /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(deepLink)
          ? deepLink
          : null;
      if (rows.length || linkedId) firstLoad.current = false;
      selectedId.current =
        linkedId ||
        rows.find((row) => workflowGroup(row.status) === "approval")?.id ||
        rows[0]?.id ||
        null;
    }
    const id = selectedId.current;
    if (id) {
      const value = await api<Workflow>(`/workflows/${id}`, { signal });
      if (alive.current && !signal?.aborted && selectedId.current === id)
        setSelected(value);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    void Promise.all([
      api<Recipe[]>("/workflow-templates", { signal: abort.signal }).then(
        (rows) => {
          if (abort.signal.aborted) return;
          setRecipes(rows);
          if (rows[0]) chooseRecipe(rows[0]);
        },
      ),
      refresh(abort.signal),
    ])
      .catch((failure) => {
        if (!abort.signal.aborted)
          setError(
            messageOf(failure) === "Not Found"
              ? "Update Parallax on this machine to use saved tasks. Advanced run is still available from the sidebar."
              : messageOf(failure),
          );
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    let fetching = false;
    const timer = window.setInterval(
      () => {
        if (document.hidden || !activeRef.current || fetching) return;
        fetching = true;
        void refresh(abort.signal)
          .catch((failure) => {
            if (!abort.signal.aborted) setError(messageOf(failure));
          })
          .finally(() => {
            fetching = false;
          });
      },
      viaMachine() ? 15000 : 3000,
    );
    return () => {
      alive.current = false;
      abort.abort();
      window.clearInterval(timer);
    };
  }, [chooseRecipe, refresh]);

  useEffect(() => {
    setReadiness(null);
  }, [assessmentKey, minutes]);
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!activeRef.current) return;
      // Do not steal shortcuts from provider/settings dialogs.
      if (
        event.target instanceof Element &&
        !event.target.closest(".task-studio") &&
        event.target !== document.body
      )
        return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQueueOpen(true);
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  async function choose(value: Workflow) {
    selectedId.current = value.id;
    setSelected(value);
    setComposing(false);
    setQueueOpen(false);
    window.history.replaceState(
      null,
      "",
      `${location.pathname}${location.search}#task=${value.id}`,
    );
    setError("");
    try {
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
    }
  }
  async function start() {
    if (!recipe || !coordinator || busy) return;
    setBusy("start");
    setError("");
    setNotice("");
    const body = {
      template_id: recipe.id,
      template_version: recipe.version,
      ...(parentTask ? { parent_workflow_id: parentTask.id } : {}),
      workspace: taskWorkspace,
      prompt,
      coordinator,
      team,
      minutes,
    };
    const signature = JSON.stringify(body);
    if (pendingStart.current?.signature !== signature)
      pendingStart.current = { signature, id: crypto.randomUUID() };
    try {
      const value = await api<Workflow>("/workflows", {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: pendingStart.current.id }),
      });
      selectedId.current = value.id;
      setSelected(value);
      pendingStart.current = null;
      setPrompt("");
      if (parentTask) {
        setFeedbackDrafts((previous) => ({
          ...previous,
          [parentTask.id]:
            previous[parentTask.id] === prompt ? "" : previous[parentTask.id],
        }));
        setParentTask(null);
        const current = recipes.find((row) => row.id === recipe.id);
        if (current) chooseRecipe(current);
      }
      setComposing(false);
      setQueueOpen(false);
      window.history.replaceState(
        null,
        "",
        `${location.pathname}${location.search}#task=${value.id}`,
      );
      setHistory((previous) => [
        value,
        ...previous.filter((row) => row.id !== value.id),
      ]);
      setNotice(
        "Task started. The team will bring its candidate back for your approval.",
      );
      await refresh().catch((failure) =>
        setError(
          `Task started, but the queue could not refresh: ${messageOf(failure)}`,
        ),
      );
    } catch (failure) {
      setError(
        `${messageOf(failure)} Check recent tasks before retrying if the connection timed out.`,
      );
      await refresh().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }
  async function assess() {
    if (!recipe || !coordinator || busy) return;
    const assessedKey = assessmentKey;
    setBusy("assess");
    setError("");
    try {
      const result = await api<TaskAssessment>("/project/assess", {
        method: "POST",
        body: JSON.stringify({
          workspace: taskWorkspace,
          checks,
          package_roots: parentTask?.spec?.package_roots || [],
          participants: [coordinator, ...team],
        }),
      });
      if (assessmentKeyRef.current === assessedKey)
        setReadiness({ ...result, assessed_at: new Date().toISOString() });
    } catch (failure) {
      if (assessmentKeyRef.current === assessedKey)
        setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function saveRecipe(update = false) {
    if (!recipe || !coordinator || busy) return;
    setBusy("save");
    setError("");
    try {
      const saved = await api<Recipe>(
        update ? `/workflow-templates/${recipe.id}` : "/workflow-templates",
        {
          method: update ? "PUT" : "POST",
          body: JSON.stringify({
            name: recipeName.trim() || recipe.name,
            description: recipe.description,
            instructions,
            coordinator,
            team,
            limits: { ...recipe.limits, minutes },
            checks,
          }),
        },
      );
      chooseRecipe(saved);
      setRecipes((previous) => [
        ...previous.filter((row) => row.id !== saved.id),
        saved,
      ]);
      setNotice(
        `Saved ${saved.name}, version ${saved.version}. Existing tasks keep their original settings.`,
      );
      await api<Recipe[]>("/workflow-templates")
        .then(setRecipes)
        .catch((failure) =>
          setError(
            `Recipe saved, but the list could not refresh: ${messageOf(failure)}`,
          ),
        );
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function act(action: "approve" | "reject" | "resume" | "cancel") {
    if (!selected) return;
    const actingId = selected.id;
    setBusy(action);
    setError("");
    setNotice("");
    try {
      const deciding = action === "approve" || action === "reject";
      const value = await api<Workflow>(
        `/workflows/${selected.id}/${deciding ? "decision" : action}`,
        {
          method: "POST",
          ...(deciding
            ? {
                body: JSON.stringify({
                  action,
                  candidate_digest: selected.candidate?.digest,
                }),
              }
            : {}),
        },
      );
      if (selectedId.current === actingId) setSelected(value);
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
      await refresh().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }
  function useAgain(feedback = "") {
    if (!selected?.spec || busy) return;
    const savedRecipe = selected.template_details
      ? {
          ...selected.template_details,
          coordinator: selected.spec.coordinator,
          team: selected.spec.team,
          limits: selected.spec.limits,
          checks: selected.spec.checks,
          builtin: recipes.find((r) => r.id === selected.template.id)?.builtin,
        }
      : recipes.find(
          (r) =>
            r.id === selected.template.id &&
            r.version === selected.template.version,
        );
    if (!savedRecipe) {
      setError(
        "Update this worker and reopen the task to preserve its original workflow settings.",
      );
      return;
    }
    chooseRecipe(savedRecipe);
    setParentTask(selected);
    setPrompt(feedback || selected.prompt || selected.title);
    onWorkspace(selected.workspace);
    setNotice("");
    setComposing(true);
    requestAnimationFrame(() =>
      document.getElementById("workflow-prompt")?.focus(),
    );
  }
  async function openRelated(id: string) {
    const recent = history.find((row) => row.id === id);
    if (recent) {
      await choose(recent);
      return;
    }
    selectedId.current = id;
    setBusy("open");
    setError("");
    try {
      const value = await api<Workflow>(`/workflows/${id}`);
      if (alive.current && selectedId.current === id) {
        setSelected(value);
        setComposing(false);
        setQueueOpen(false);
        window.history.replaceState(
          null,
          "",
          `${location.pathname}${location.search}#task=${id}`,
        );
      }
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function sendDirection(value: Workflow) {
    const submitted = feedbackDrafts[value.id] || "";
    if (!value.run_id || !submitted.trim() || sendingRef.current.has(value.id))
      return;
    sendingRef.current.add(value.id);
    setSendingTasks(new Set(sendingRef.current));
    setSendNotices((previous) => ({ ...previous, [value.id]: "" }));
    try {
      await api(`/runs/${value.run_id}/steer`, {
        method: "POST",
        body: JSON.stringify({ message: submitted }),
      });
      setFeedbackDrafts((previous) => ({
        ...previous,
        [value.id]: previous[value.id] === submitted ? "" : previous[value.id],
      }));
      setSendNotices((previous) => ({
        ...previous,
        [value.id]: "Direction queued for the team.",
      }));
    } catch (failure) {
      setSendNotices((previous) => ({
        ...previous,
        [value.id]: messageOf(failure),
      }));
    } finally {
      sendingRef.current.delete(value.id);
      setSendingTasks(new Set(sendingRef.current));
    }
  }

  const approvalCount = history.filter(
    (w) => workflowGroup(w.status) === "approval",
  ).length;
  const runningCount = history.filter(
    (w) => workflowGroup(w.status) === "running",
  ).length;
  const projects = [
    ...new Set([
      workspace,
      ...knownProjects,
      ...history.map((w) => w.workspace),
    ]),
  ].filter(Boolean);
  const projectHistory = history.filter(
    (w) => !projectFilter || w.workspace === projectFilter,
  );
  const visible = projectHistory.filter(
    (w) =>
      (filter === "all" || workflowGroup(w.status) === filter) &&
      `${w.title} ${w.workspace} ${w.template.name} ${w.id}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
  );
  function newTask() {
    if (busy) return;
    firstLoad.current = false;
    setComposing(true);
    setQueueOpen(false);
    setNotice("");
    if (projectFilter && !parentTask) onWorkspace(projectFilter);
    requestAnimationFrame(() =>
      document.getElementById("workflow-prompt")?.focus(),
    );
  }
  const ready =
    !!selected &&
    canApprove(selected.status, selected.candidate, selected.decision);
  const instructionEdits =
    !!recipe &&
    (instructions !== recipe.instructions ||
      JSON.stringify(checks) !== JSON.stringify(recipe.checks));
  const invalidSettings =
    !Number.isInteger(minutes) ||
    minutes < 1 ||
    minutes > 240 ||
    invalidChecks.size > 0 ||
    checks.some(
      (check) =>
        !check.name.trim() ||
        !check.argv.length ||
        !Number.isFinite(check.timeout) ||
        check.timeout < 1 ||
        check.timeout > 1800,
    );
  return (
    <div className={`task-studio ${queueOpen ? "queue-open" : ""}`}>
      <aside className="task-queue" aria-label="Project tasks">
        <div className="queue-heading">
          <span className="queue-brand">
            Parallax <small>STUDIO</small>
          </span>
          <button
            className="icon-button queue-dismiss"
            aria-label="Hide task list"
            onClick={() => setQueueOpen(false)}
          >
            <WorkIcon name="close" />
          </button>
        </div>
        <button className="new-task-button" onClick={newTask}>
          <WorkIcon name="plus" /> New task <span>↗</span>
        </button>
        <label className="queue-search">
          <WorkIcon name="search" />
          <input
            ref={searchRef}
            aria-label="Search tasks"
            placeholder="Search tasks…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>⌘ K</kbd>
        </label>
        <label className="queue-project">
          <WorkIcon name="folder" />
          <select
            aria-label="Filter by project"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
          >
            <option value="">All projects</option>
            {projects.map((path) => (
              <option key={path} value={path}>
                {shortProject(path)} · {path}
              </option>
            ))}
          </select>
        </label>
        <nav className="queue-views" aria-label="Task views">
          {[
            ["all", "All tasks", "stack"],
            ["approval", "Awaiting approval", "review"],
            ["running", "In progress", "activity"],
            ["attention", "Needs attention", "warning"],
            ["finished", "Completed & closed", "check"],
          ].map(([id, label, icon]) => (
            <button
              key={id}
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              <WorkIcon name={icon} />
              <span>{label}</span>
              <small>
                {
                  projectHistory.filter(
                    (w) => id === "all" || workflowGroup(w.status) === id,
                  ).length
                }
              </small>
            </button>
          ))}
        </nav>
        <div className="queue-list-heading">
          <span>{search ? "SEARCH RESULTS" : "RECENT TASKS"}</span>
          <button
            className="icon-button"
            aria-label="Refresh task list"
            onClick={() => void refresh().catch((f) => setError(messageOf(f)))}
          >
            <WorkIcon name="refresh" size={14} />
          </button>
        </div>
        <div className="queue-scroll">
          {loading ? (
            <p className="queue-empty" role="status">
              Loading tasks…
            </p>
          ) : !visible.length ? (
            <div className="queue-empty">
              <p>
                {history.length
                  ? "No tasks match this view."
                  : "Your tasks will appear here."}
              </p>
              {history.length > 0 && (
                <button
                  className="text-button"
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                    setProjectFilter("");
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            <ul className="task-list">
              {visible.map((w) => (
                <li key={w.id}>
                  <button
                    aria-pressed={!composing && selected?.id === w.id}
                    onClick={() => void choose(w)}
                  >
                    <span className={`task-dot ${workflowGroup(w.status)}`} />
                    <span className="task-list-content">
                      <strong>{w.title}</strong>
                      <span>
                        {shortProject(w.workspace)}
                        <time
                          dateTime={w.updated_at}
                          title={when(w.updated_at)}
                        >
                          {new Date(w.updated_at).toLocaleDateString([], {
                            month: "short",
                            day: "numeric",
                          })}
                        </time>
                      </span>
                      <small>{workflowLabels[w.status] || w.status}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="queue-footer">
          <span>
            <i className={online ? "online-dot" : "offline-dot"} />
            {online ? "Worker connected" : "Worker offline"}
          </span>
          <button
            className="icon-button"
            aria-label="Provider connections"
            onClick={onConnections}
          >
            <WorkIcon name="settings" size={16} />
          </button>
        </div>
      </aside>
      <div className="task-main">
        <div className="mobile-task-bar">
          <button
            className="text-button"
            onClick={() => setQueueOpen(!queueOpen)}
          >
            <WorkIcon name="stack" /> Tasks <span>{history.length}</span>
          </button>
          <button className="text-button" onClick={newTask}>
            <WorkIcon name="plus" /> New task
          </button>
        </div>
        {error && (
          <div className="task-alert" role="alert">
            <WorkIcon name="warning" />
            <p>{error}</p>
            <button
              aria-label="Dismiss error"
              className="icon-button"
              onClick={() => setError("")}
            >
              <WorkIcon name="close" />
            </button>
          </div>
        )}
        {notice && (
          <div className="task-notice" role="status">
            <p>{notice}</p>
            <button
              className="icon-button"
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <WorkIcon name="close" />
            </button>
          </div>
        )}
        {!online && (
          <p className="task-offline">
            Worker offline. Reconnect to start, approve, or resume work.
            Displayed evidence may be out of date.
          </p>
        )}
        <div
          className="task-compose-scroll"
          hidden={!composing && (!!selected || loading)}
        >
          <fieldset disabled={!!busy} className="composer-fieldset">
            <section
              className="workflow-compose"
              aria-labelledby="workflow-compose-title"
            >
              <header className="compose-heading">
                <div>
                  <span className="eyebrow">{shortProject(taskWorkspace)}</span>
                  <h1 id="workflow-compose-title">New task</h1>
                  <p>Give your team an outcome and a way to verify it.</p>
                </div>
                {selected && (
                  <button
                    className="text-button"
                    onClick={() => setComposing(false)}
                  >
                    Back to task <WorkIcon name="close" size={14} />
                  </button>
                )}
              </header>
              {parentTask && (
                <div className="followup-context">
                  <span>
                    <WorkIcon name="branch" size={14} /> Linked follow-up
                  </span>
                  <strong>{parentTask.title}</strong>
                  <p>
                    A new candidate from the current project. This task keeps
                    the original workflow version, checks, and limits. Unapplied
                    code from the parent is not reused.
                  </p>
                  <details>
                    <summary>Original goal and prior result</summary>
                    <p>{parentTask.original_goal || parentTask.prompt}</p>
                    <p>
                      {parentTask.candidate?.summary ||
                        parentTask.summary ||
                        "No completed result recorded."}
                    </p>
                  </details>
                  <button
                    className="text-button"
                    onClick={() => {
                      setParentTask(null);
                      const current = recipes.find((r) => r.id === recipe?.id);
                      if (current) chooseRecipe(current);
                      setNotice(
                        "Standalone task selected. Review the current project's recipe and team settings before starting.",
                      );
                    }}
                  >
                    Make a standalone task
                  </button>
                </div>
              )}
              <label className="workflow-field">
                <span>Project</span>
                <input
                  list="task-projects"
                  aria-label="Workflow project"
                  readOnly={!!parentTask}
                  value={taskWorkspace}
                  onChange={(e) => onWorkspace(e.target.value)}
                  placeholder="Absolute path to an approved project"
                />
                <datalist id="task-projects">
                  {projects.map((path) => (
                    <option key={path} value={path} />
                  ))}
                </datalist>
              </label>
              <label className="workflow-field">
                <span>Task</span>
                <textarea
                  id="workflow-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  maxLength={12000}
                  rows={6}
                  placeholder="Describe the change, relevant context, and what done looks like…"
                />
              </label>
              <div className="compose-options">
                <label>
                  Workflow
                  <select
                    aria-label="Task workflow"
                    disabled={!!parentTask}
                    value={recipe?.id || ""}
                    onChange={(e) => {
                      const next = recipes.find((r) => r.id === e.target.value);
                      if (next) chooseRecipe(next);
                    }}
                  >
                    {parentTask &&
                      recipe &&
                      !recipes.some(
                        (r) =>
                          r.id === recipe.id && r.version === recipe.version,
                      ) && (
                        <option value={recipe.id}>
                          {recipe.name} · v{recipe.version}
                        </option>
                      )}
                    {recipes
                      .filter(
                        (r) =>
                          !parentTask ||
                          r.id !== recipe?.id ||
                          r.version === recipe?.version,
                      )
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                          {r.builtin ? "" : ` · v${r.version}`}
                        </option>
                      ))}
                  </select>
                </label>
                <span className="workflow-pill">
                  <WorkIcon name="review" size={14} /> Approval required
                </span>
              </div>
              <div className="workflow-team-summary">
                <span>
                  {team
                    .map((p) => LABELS[p.provider] || p.provider)
                    .join(" + ")}{" "}
                  builds
                </span>
                <span>
                  {coordinator
                    ? LABELS[coordinator.provider] || coordinator.provider
                    : "Coordinator"}{" "}
                  coordinates and checks
                </span>
                <span>{minutes} min limit</span>
              </div>
              <details className="workflow-settings">
                <summary>
                  Configure team, checks, and reusable instructions
                </summary>
                <p className="workflow-muted">
                  Use different providers for implementation and independent
                  review. Provider usage is charged to your configured accounts.
                </p>
                <button className="text-button" onClick={onConnections}>
                  Manage provider connections
                </button>
                {coordinator &&
                  renderParticipant(coordinator, setCoordinator, true)}
                {team.map((member, index) => (
                  <div key={index}>
                    {renderParticipant(
                      member,
                      (value) =>
                        setTeam((current) =>
                          current.map((m, i) => (i === index ? value : m)),
                        ),
                      false,
                    )}
                    {team.length > 1 && (
                      <button
                        className="text-button"
                        onClick={() =>
                          setTeam((current) =>
                            current.filter((_, i) => i !== index),
                          )
                        }
                      >
                        Remove team member
                      </button>
                    )}
                  </div>
                ))}
                <button
                  className="text-button"
                  disabled={team.length >= 8}
                  onClick={() =>
                    setTeam((current) => [
                      ...current,
                      {
                        provider: "grok",
                        model: null,
                        role: "reviewer",
                        effort: "high",
                        transport: "cli",
                      },
                    ])
                  }
                >
                  Add team member
                </button>
                <label className="workflow-field">
                  <span>Execution time limit, minutes</span>
                  <input
                    type="number"
                    min={1}
                    max={240}
                    value={minutes}
                    onChange={(e) => setMinutes(Number(e.target.value))}
                  />
                </label>
                <p className="workflow-muted">
                  The limit carries across restarts. Time waiting for your
                  approval does not consume it.
                </p>
                <div hidden={!!parentTask}>
                  <label className="workflow-field">
                    <span>Reusable instructions</span>
                    <textarea
                      rows={3}
                      value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                      maxLength={4000}
                    />
                  </label>
                  <label className="workflow-field">
                    <span>Recipe name</span>
                    <input
                      value={recipeName}
                      onChange={(e) => setRecipeName(e.target.value)}
                      maxLength={80}
                      placeholder={`${recipe?.name || "My workflow"} copy`}
                    />
                  </label>
                  <div className="workflow-checks">
                    <h3>Project checks</h3>
                    <p className="workflow-muted">
                      Leave this empty to use the project's detected checks.
                      Save explicit commands when your project needs a
                      particular test or package root.
                    </p>
                    {checks.map((check, index) => (
                      <div key={`${recipe?.id}-${recipe?.version}-${index}`}>
                        {renderCheck(
                          check,
                          index,
                          (value) =>
                            setChecks((current) =>
                              current.map((item, i) =>
                                i === index ? value : item,
                              ),
                            ),
                          () => {
                            setChecks((current) =>
                              current.filter((_, i) => i !== index),
                            );
                            setInvalidChecks(
                              (current) =>
                                new Set(
                                  [...current]
                                    .filter((i) => i !== index)
                                    .map((i) => (i > index ? i - 1 : i)),
                                ),
                            );
                          },
                          (valid) =>
                            setInvalidChecks((current) => {
                              const next = new Set(current);
                              if (valid) next.delete(index);
                              else next.add(index);
                              return next;
                            }),
                        )}
                      </div>
                    ))}
                    <button
                      className="text-button"
                      disabled={checks.length >= 64}
                      onClick={() =>
                        setChecks((current) => [
                          ...current,
                          {
                            name: "Test suite",
                            argv: ["npm", "test"],
                            cwd: ".",
                            timeout: 300,
                          },
                        ])
                      }
                    >
                      Add check
                    </button>
                  </div>
                  <div className="workflow-actions">
                    <button
                      className="secondary-button"
                      disabled={
                        !!busy ||
                        !online ||
                        invalidSettings ||
                        !recipeName.trim()
                      }
                      onClick={() => void saveRecipe()}
                    >
                      Save as recipe
                    </button>
                    {recipe && !recipe.builtin && (
                      <button
                        className="secondary-button"
                        disabled={!!busy || !online || invalidSettings}
                        onClick={() => void saveRecipe(true)}
                      >
                        Save new version
                      </button>
                    )}
                  </div>
                </div>
              </details>

              {instructionEdits && (
                <p className="task-offline">
                  Save your instructions and checks as a recipe before starting.
                </p>
              )}
              {readiness && (
                <TaskPreflight
                  assessment={readiness}
                  configuredChecks={checks}
                  disabled={!!busy || !!parentTask}
                  onUseChecks={(value) => {
                    setChecks(value);
                    setInvalidChecks(new Set());
                  }}
                />
              )}
              <div className="compose-submit">
                <button
                  className="secondary-button"
                  disabled={
                    !!busy ||
                    !online ||
                    !taskWorkspace ||
                    !recipe ||
                    invalidSettings
                  }
                  onClick={() => void assess()}
                >
                  {busy === "assess" ? "Checking…" : "Check readiness"}
                </button>
                <button
                  className="primary-button"
                  disabled={
                    loading ||
                    !!busy ||
                    !online ||
                    !taskWorkspace ||
                    !prompt.trim() ||
                    !coordinator ||
                    instructionEdits ||
                    invalidSettings
                  }
                  onClick={() => void start()}
                >
                  {busy === "start" ? "Starting…" : "Start task"}
                  <WorkIcon name="arrow" />
                </button>
              </div>
              <p className="compose-footnote">
                The team prepares an isolated candidate, runs project checks,
                and brings it back here for your approval.
              </p>
            </section>
          </fieldset>
        </div>
        {!composing && selected ? (
          <TaskWorkspace
            visible={active}
            key={selected.id}
            workflow={selected}
            feedback={feedbackDrafts[selected.id] || ""}
            sending={sendingTasks.has(selected.id)}
            sent={sendNotices[selected.id] || ""}
            onSend={() => void sendDirection(selected)}
            parentTitle={
              history.find((row) => row.id === selected.parent_workflow_id)
                ?.title
            }
            followups={history.filter(
              (row) => row.parent_workflow_id === selected.id,
            )}
            onRelated={(id) => void openRelated(id)}
            onFeedback={(update) =>
              setFeedbackDrafts((previous) => ({
                ...previous,
                [selected.id]:
                  typeof update === "function"
                    ? update(previous[selected.id] || "")
                    : update,
              }))
            }
            ready={ready}
            busy={busy}
            online={online}
            onAction={(action) => void act(action)}
            onAgain={useAgain}
            onInspect={onInspect}
            renderEvidence={renderEvidence}
          />
        ) : !composing && loading ? (
          <div className="task-loading" role="status">
            <WorkIcon name="stack" size={28} />
            <p>Opening your workspace…</p>
          </div>
        ) : null}
        <footer className="task-statusbar">
          <span>
            {approvalCount} awaiting approval · {runningCount} in progress
          </span>
          <span>Parallax v{__PARALLAX_VERSION__}</span>
        </footer>
      </div>
    </div>
  );
}
