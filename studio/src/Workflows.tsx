import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, relayApi, messageOf, viaMachine } from "./api";
import {
  LABELS,
  type CheckSpec,
  type Participant,
  type RunSpec,
} from "./types";
import {
  canApprove,
  workflowGroup,
  workflowLabels,
  workflowAccess,
  workflowOperationId,
  workflowReviewAccess,
  workflowInReviewInbox,
  githubBindingsForProject,
  type WorkflowAuthority,
} from "./workflow-state";
import { TaskPreflight, type TaskAssessment } from "./TaskPreflight";
import { TaskWorkspace } from "./TaskWorkspace";
import { PilotMetrics } from "./PilotMetrics";
import { WorkIcon } from "./WorkIcon";
import { ArchivedHistory } from "./ArchivedHistory";
import type { EvidenceTransport } from "./session";
import "./workflows.css";
import { reviewLink } from "./review-link";
import { taskTitle, workflowTitle } from "./task-review";

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
  schema_version?: string;
  required_worker_features?: string[];
  requester?: string;
  reviewer?: string;
  delivery?: { local?: string; github?: string };
  publication_operation?: string;
  github_target?: { id: string; full_name: string; base: string };
  publication?: {
    url: string;
    pr: number;
    branch: string;
    commit: string;
    repository: string;
  };
  revision?: { lineage: string; parent: string; parent_digest: string };
  superseded_by?: string;
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
  task_settings?: {
    schema_version: "1.0";
    instructions: string;
    checks: CheckSpec[];
  };
  decision?: { action: string; actor?: string | null; at?: string | null };
  approval?: { action?: string; status?: string; actor?: string; at?: string };
  comments?: {
    id: string;
    actor?: string | null;
    message: string;
    at?: string | null;
  }[];
  timeline?: { stage: string; at: string }[];
};

const recipeKey = (recipe: Pick<Recipe, "id" | "version">) =>
  `${recipe.id}:${recipe.version}`;

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
  teamWorkspace = false,
  executionWorker,
  accountIdentity,
  active,
  workspace,
  onWorkspace,
  online,
  evidenceTransport,
  onReconnect,
  onInspect,
  onConnections,
  knownProjects,
  renderEvidence,
  renderParticipant,
  renderCheck,
  view = "tasks",
  newTaskRequest,
  githubConnectionRevision = 0,
}: {
  view?: "tasks" | "inbox";
  newTaskRequest?: { sequence: number; workspace: string };
  githubConnectionRevision?: number;
  teamWorkspace?: boolean;
  executionWorker?: string;
  accountIdentity?: { actor?: string; workspace: string };
  active: boolean;
  knownProjects: string[];
  renderEvidence: (
    run: import("./types").RunResult,
    tab: "checks" | "findings" | "settings",
  ) => ReactNode;
  workspace: string;
  onWorkspace: (value: string) => void;
  online: boolean;
  evidenceTransport?: EvidenceTransport;
  onReconnect?: () => void;
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
  const [historyState, setHistoryState] = useState<
    "loading" | "ready" | "unavailable"
  >("loading");
  const [historyError, setHistoryError] = useState("");
  const [archiveView, setArchiveView] = useState(false);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const selectedId = useRef<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [turns, setTurns] = useState(20);
  const [team, setTeam] = useState<Participant[]>([]);
  const [coordinator, setCoordinator] = useState<Participant | null>(null);
  const [recipeName, setRecipeName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [checks, setChecks] = useState<CheckSpec[]>([]);
  const [invalidChecks, setInvalidChecks] = useState<Set<number>>(new Set());
  const paired = viaMachine();
  const authorityScope = JSON.stringify([
    executionWorker,
    online,
    teamWorkspace,
    paired,
    accountIdentity?.actor,
    accountIdentity?.workspace,
  ]);
  type SetupContext = {
    authority?:
      | (WorkflowAuthority & { projects?: string[]; workspace?: string })
      | null;
  };
  const [contextSnapshot, setContextSnapshot] = useState<{
    scope: string;
    value: SetupContext;
  } | null>(null);
  const [contextError, setContextError] = useState("");
  const [contextNeedsReload, setContextNeedsReload] = useState(false);
  const contextIdentity = useRef<{ scope: string; value: string } | null>(null);
  const [contextRevision, setContextRevision] = useState(0);
  const authorityRequest = useRef(0);
  const authorityScopeRef = useRef(authorityScope);
  authorityScopeRef.current = authorityScope;
  const authorityLoaded = online && contextSnapshot?.scope === authorityScope;
  const caller = authorityLoaded
    ? contextSnapshot.value.authority || null
    : null;
  const approvedProjects = Array.isArray(caller?.projects)
    ? [
        ...new Set(
          caller.projects.filter(
            (path) => typeof path === "string" && !!path.trim(),
          ),
        ),
      ]
    : [];
  const access = workflowAccess(caller, viaMachine());
  const reviewAccess = workflowReviewAccess(
    caller,
    viaMachine(),
    teamWorkspace,
    selected?.schema_version,
  );
  const [members, setMembers] = useState<
    { account: string; name: string; login: string }[]
  >([]);
  const [githubBindings, setGithubBindings] = useState<
    {
      id: string;
      worker?: string;
      project: string;
      full_name: string;
      base: string;
    }[]
  >([]);
  const githubReadVersion = useRef(0);
  const [githubBinding, setGithubBinding] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const setupAction = useRef("");
  const [error, setError] = useState("");
  const [setupError, setSetupError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [readiness, setReadiness] = useState<TaskAssessment | null>(null);
  const readinessKey = useRef<string | null>(null);
  const assessmentSequence = useRef(0);
  const recipeLoaded = useRef(false);
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [composing, setComposing] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [reportScope, setReportScope] = useState<string | null>(null);
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
  const queueToggleRef = useRef<HTMLButtonElement>(null);
  const queueReturnRef = useRef<HTMLElement | null>(null);
  const navigationFrame = useRef<number | null>(null);
  const navigationRequest = useRef(0);
  const queueOpenRef = useRef(queueOpen);
  queueOpenRef.current = queueOpen;
  const taskMainRef = useRef<HTMLDivElement>(null);
  const connectionReturn = useRef<{
    opener: HTMLButtonElement;
    scope: string;
    project: string;
    identity: string;
    requiresDelivery: boolean;
  } | null>(null);
  const pendingStart = useRef<{ signature: string; id: string } | null>(null);
  const composedRequest = useRef<number | undefined>(undefined);
  const pendingComments = useRef(
    new Map<string, { signature: string; id: string }>(),
  );
  const alive = useRef(true);
  const activeRef = useRef(active);
  activeRef.current = active;
  const onlineRef = useRef(online);
  onlineRef.current = online;
  const historyRequest = useRef(0);
  const assessmentKey = JSON.stringify([
    authorityScope,
    caller?.actor,
    caller?.workspace,
    caller?.team,
    caller?.role,
    approvedProjects,
    recipe?.id,
    recipe?.version,
    taskWorkspace,
    executionWorker,
    minutes,
    coordinator,
    team,
    checks,
    parentTask?.spec?.package_roots,
  ]);
  const assessmentKeyRef = useRef(assessmentKey);
  assessmentKeyRef.current = assessmentKey;
  // Hide and ignore a result immediately when its inputs change, before effects
  // clear state. An older in-flight response cannot gate a different task.
  const projectAllowed =
    online &&
    (!paired || (authorityLoaded && approvedProjects.includes(taskWorkspace)));
  const setupGuard = useRef({
    scope: authorityScope,
    project: taskWorkspace,
    allowed: false,
    key: assessmentKey,
  });
  setupGuard.current = {
    scope: authorityScope,
    project: taskWorkspace,
    allowed: projectAllowed && access.deliver,
    key: assessmentKey,
  };
  const currentReadiness =
    projectAllowed && readinessKey.current === assessmentKey ? readiness : null;
  const readinessBlocked =
    currentReadiness?.status === "blocked" ||
    currentReadiness?.issues?.some((issue) => issue.severity === "blocker");

  const chooseRecipe = useCallback((value: Recipe) => {
    recipeLoaded.current = true;
    setRecipe(value);
    setCoordinator(structuredClone(value.coordinator));
    setTeam(structuredClone(value.team));
    setMinutes(value.limits.minutes);
    // Older saved recipes may omit the limit; the runtime default applies.
    setTurns(value.limits.coordinator_turns ?? 20);
    setInstructions(value.instructions);
    setChecks(structuredClone(value.checks));
    setInvalidChecks(new Set());
    setRecipeName("");
    setReadiness(null);
  }, []);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++historyRequest.current;
      if (!online) {
        setHistoryState("unavailable");
        if (teamWorkspace) {
          setHistory([]);
          setSelected(null);
        }
        return;
      }
      let rows: Workflow[];
      try {
        rows = await api<Workflow[]>("/workflows", { signal });
      } catch (failure) {
        if (
          !alive.current ||
          signal?.aborted ||
          historyRequest.current !== request ||
          !onlineRef.current
        )
          return;
        setHistoryState("unavailable");
        setHistoryError(messageOf(failure));
        if (teamWorkspace) {
          setHistory([]);
          setSelected(null);
        }
        return;
      }
      if (
        !alive.current ||
        signal?.aborted ||
        historyRequest.current !== request ||
        !onlineRef.current
      )
        return;
      setHistoryState("ready");
      setHistoryError("");
      setHistory(rows);
      if (firstLoad.current) {
        const deepLink = new URLSearchParams(location.hash.slice(1)).get(
          "task",
        );
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
        if (
          alive.current &&
          !signal?.aborted &&
          historyRequest.current === request &&
          onlineRef.current &&
          selectedId.current === id
        )
          setSelected(value);
      }
    },
    [online, teamWorkspace],
  );

  const loadSetupContext = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++authorityRequest.current;
      try {
        const context = await api<SetupContext>("/context", { signal });
        if (
          signal?.aborted ||
          !onlineRef.current ||
          authorityScopeRef.current !== authorityScope ||
          request !== authorityRequest.current
        )
          throw new Error(
            "Project permissions changed. Inspect the current setup again.",
          );
        if (paired && !context.authority)
          throw new Error(
            "Workspace permissions are unavailable. Update or reconnect this worker.",
          );
        if (
          paired &&
          accountIdentity &&
          (context.authority?.workspace !== accountIdentity.workspace ||
            (accountIdentity.actor &&
              context.authority?.actor !== accountIdentity.actor))
        ) {
          setContextNeedsReload(true);
          throw new Error(
            "The signed-in account or workspace changed. Reload Studio before continuing.",
          );
        }
        const identity = JSON.stringify([
          context.authority?.actor,
          context.authority?.workspace,
          context.authority?.team,
        ]);
        if (
          paired &&
          contextIdentity.current?.scope === authorityScope &&
          contextIdentity.current.value !== identity
        ) {
          setContextNeedsReload(true);
          throw new Error(
            "The signed-in account or workspace changed. Reload Studio before continuing.",
          );
        }
        contextIdentity.current = { scope: authorityScope, value: identity };
        setContextSnapshot({ scope: authorityScope, value: context });
        setContextNeedsReload(false);
        setContextError("");
        return context;
      } catch (failure) {
        if (
          !signal?.aborted &&
          authorityScopeRef.current === authorityScope &&
          request === authorityRequest.current
        ) {
          setContextSnapshot(null);
          setContextError(messageOf(failure));
        }
        throw failure;
      }
    },
    [
      authorityScope,
      paired,
      accountIdentity?.actor,
      accountIdentity?.workspace,
    ],
  );

  useEffect(() => {
    const abort = new AbortController();
    // Re-entering tasks after changing provider connections or workspace access
    // invalidates a previous observation. No provider work runs on navigation.
    assessmentSequence.current++;
    setReadiness(null);
    // Clear on leaving as well, so a repository handoff waits for refreshed
    // permissions before consuming its request and focusing the visible form.
    setContextSnapshot(null);
    if (active && online) {
      void loadSetupContext(abort.signal).catch(() => undefined);
    }
    return () => {
      assessmentSequence.current++;
      abort.abort();
    };
  }, [active, online, loadSetupContext, contextRevision]);

  function openConnections(
    opener: HTMLButtonElement,
    requiresDelivery = false,
  ) {
    connectionReturn.current = {
      opener,
      scope: authorityScope,
      project: taskWorkspace,
      identity: JSON.stringify([
        caller?.actor,
        caller?.workspace,
        caller?.team,
      ]),
      requiresDelivery,
    };
    onConnections();
  }

  useEffect(() => {
    const pending = connectionReturn.current;
    if (!pending || !active || (online && !authorityLoaded && !contextError))
      return;
    const frame = requestAnimationFrame(() => {
      connectionReturn.current = null;
      // Permission refresh can temporarily hide the dialog's original opener.
      // Restore it only once the same permitted draft is visible again. Keep
      // deliberate keyboard navigation elsewhere while the refresh was pending.
      if (document.activeElement && document.activeElement !== document.body)
        return;
      const sameDraft =
        pending.scope === authorityScope &&
        pending.project === taskWorkspace &&
        pending.identity ===
          JSON.stringify([caller?.actor, caller?.workspace, caller?.team]);
      const visible =
        pending.opener.isConnected &&
        pending.opener.getClientRects().length > 0 &&
        !pending.opener.closest("[hidden], [inert]");
      if (
        sameDraft &&
        visible &&
        (!pending.requiresDelivery || (access.deliver && projectAllowed))
      )
        pending.opener.focus();
      else taskMainRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [
    active,
    online,
    authorityLoaded,
    contextError,
    authorityScope,
    taskWorkspace,
    caller?.actor,
    caller?.workspace,
    caller?.team,
    access.deliver,
    projectAllowed,
  ]);

  async function authorizeSetupAction() {
    const expected = setupGuard.current;
    if (
      !activeRef.current ||
      !expected.allowed ||
      expected.scope !== authorityScope ||
      expected.project !== taskWorkspace ||
      expected.key !== assessmentKey
    )
      throw new Error(
        "Choose a currently authorized project on the connected worker.",
      );
    const context = await loadSetupContext();
    if (
      !alive.current ||
      !activeRef.current ||
      !onlineRef.current ||
      authorityScopeRef.current !== authorityScope ||
      setupGuard.current.key !== assessmentKey
    )
      throw new Error("Task setup changed. Inspect the current setup again.");
    if (
      paired &&
      (context.authority?.actor !== caller?.actor ||
        context.authority?.workspace !== caller?.workspace ||
        context.authority?.team !== caller?.team)
    )
      throw new Error(
        "The signed-in account or workspace changed. Reload Studio before continuing.",
      );
    if (
      !workflowAccess(context.authority || null, paired).deliver ||
      (paired && !context.authority?.projects?.includes(taskWorkspace))
    )
      throw new Error(
        "Your current permissions do not allow starting tasks in this project.",
      );
  }

  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    setSetupError("");
    if (viaMachine()) {
      const githubRequest = ++githubReadVersion.current;
      void relayApi<typeof githubBindings>("/github/bindings", {
        signal: abort.signal,
      })
        .then((v) => {
          if (
            !abort.signal.aborted &&
            githubReadVersion.current === githubRequest
          )
            setGithubBindings(v);
        })
        .catch(() => {});
      void relayApi<typeof members>("/workspaces/members", {
        signal: abort.signal,
      })
        .then((v) => {
          if (!abort.signal.aborted) setMembers(v);
        })
        .catch(() => {});
    }
    void Promise.all([
      (online
        ? api<Recipe[]>("/workflow-templates", { signal: abort.signal })
        : Promise.resolve([] as Recipe[])
      ).then((rows) => {
        if (abort.signal.aborted) return;
        setRecipes(rows);
        if (rows[0] && !recipeLoaded.current) chooseRecipe(rows[0]);
      }),
      refresh(abort.signal),
    ])
      .catch((failure) => {
        if (!abort.signal.aborted)
          setSetupError(
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
  }, [chooseRecipe, refresh, online]);

  useEffect(() => {
    assessmentSequence.current++;
    setReadiness(null);
  }, [assessmentKey]);
  useEffect(() => {
    if (!paired || !online || !githubConnectionRevision) return;
    const abort = new AbortController();
    const request = ++githubReadVersion.current;
    void relayApi<typeof githubBindings>("/github/bindings", {
      signal: abort.signal,
    })
      .then((value) => {
        if (!abort.signal.aborted && githubReadVersion.current === request)
          setGithubBindings(value);
      })
      .catch((failure) => {
        if (!abort.signal.aborted && githubReadVersion.current === request)
          setError(
            `The connection was saved, but delivery destinations could not refresh: ${messageOf(failure)}. Reload Studio before selecting GitHub delivery.`,
          );
      });
    return () => abort.abort();
  }, [githubConnectionRevision, authorityScope, online, paired]);
  useEffect(() => {
    setGithubBinding((current) =>
      githubBindingsForProject(
        githubBindings,
        taskWorkspace,
        executionWorker,
      ).some(
        (binding) =>
          binding.id === current && binding.project === taskWorkspace,
      )
        ? current
        : "",
    );
  }, [taskWorkspace, githubBindings, executionWorker]);

  function focusNavigation(destination: () => HTMLElement | null) {
    if (!alive.current || !activeRef.current) return;
    if (navigationFrame.current !== null)
      cancelAnimationFrame(navigationFrame.current);
    const origin = document.activeElement;
    const scope = authorityScopeRef.current;
    navigationFrame.current = requestAnimationFrame(() => {
      navigationFrame.current = null;
      if (
        !alive.current ||
        !activeRef.current ||
        authorityScopeRef.current !== scope
      )
        return;
      if (
        document.activeElement &&
        document.activeElement !== document.body &&
        document.activeElement !== origin
      )
        return;
      destination()?.focus();
    });
  }
  function openQueue() {
    if (!alive.current || !activeRef.current) return;
    if (!queueOpenRef.current)
      queueReturnRef.current = document.activeElement as HTMLElement | null;
    setQueueOpen(true);
    focusNavigation(() => (queueOpenRef.current ? searchRef.current : null));
  }
  function closeQueue() {
    if (!alive.current || !activeRef.current) return;
    setQueueOpen(false);
    focusNavigation(() => {
      if (queueOpenRef.current) return null;
      const opener = queueReturnRef.current;
      return opener !== document.body &&
        opener?.isConnected &&
        opener.getClientRects().length > 0 &&
        !opener.closest("[hidden], [inert]")
        ? opener
        : queueToggleRef.current;
    });
  }
  useEffect(() => {
    return () => {
      if (navigationFrame.current !== null) {
        cancelAnimationFrame(navigationFrame.current);
        navigationFrame.current = null;
      }
    };
  }, [active, authorityScope]);
  useEffect(() => {
    navigationRequest.current++;
    setBusy((current) => (current === "open" ? "" : current));
  }, [authorityScope]);
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
        openQueue();
      } else if (
        event.key === "Escape" &&
        queueOpenRef.current &&
        event.target instanceof Element &&
        event.target.closest(".task-queue")
      ) {
        event.preventDefault();
        closeQueue();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  async function choose(value: Workflow, explicit = true) {
    const request = ++navigationRequest.current;
    const scope = authorityScopeRef.current;
    setBusy((current) => (current === "open" ? "" : current));
    setArchiveView(false);
    selectedId.current = value.id;
    setSelected(value);
    setComposing(false);
    if (explicit) {
      setQueueOpen(false);
      focusNavigation(() =>
        selectedId.current === value.id && !queueOpenRef.current
          ? document.getElementById("selected-task-title") ||
            taskMainRef.current
          : null,
      );
    }
    window.history.replaceState(
      null,
      "",
      `${location.pathname}${location.search}#task=${value.id}`,
    );
    setError("");
    try {
      await refresh();
    } catch (failure) {
      if (
        alive.current &&
        navigationRequest.current === request &&
        authorityScopeRef.current === scope &&
        selectedId.current === value.id
      )
        setError(messageOf(failure));
    }
  }
  async function start() {
    if (
      !recipe ||
      !coordinator ||
      busy ||
      setupAction.current ||
      !access.deliver ||
      !projectAllowed
    )
      return;
    if (
      loading ||
      !online ||
      !taskWorkspace ||
      !prompt.trim() ||
      invalidSettings
    )
      return;
    if (readinessBlocked) {
      setError(
        "Resolve the blocked setup and check readiness again before starting.",
      );
      return;
    }
    setupAction.current = "start";
    setBusy("start");
    setError("");
    setNotice("");
    const body = {
      schema_version: "2.0",
      ...(githubBinding ? { github_binding: githubBinding } : {}),
      template_id: recipe.id,
      template_version: recipe.version,
      ...(parentTask ? { parent_workflow_id: parentTask.id } : {}),
      workspace: taskWorkspace,
      prompt,
      coordinator,
      team,
      minutes,
      ...(turns !== (recipe.limits.coordinator_turns ?? 20)
        ? { coordinator_turns: turns }
        : {}),
      ...(taskSettingsEdits
        ? { task_settings: { schema_version: "1.0", instructions, checks } }
        : {}),
    };
    const signature = JSON.stringify(body);
    if (pendingStart.current?.signature !== signature)
      pendingStart.current = { signature, id: crypto.randomUUID() };
    let dispatched = false;
    try {
      await authorizeSetupAction();
      dispatched = true;
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
        dispatched
          ? `${messageOf(failure)} Check recent tasks before retrying if the connection timed out.`
          : messageOf(failure),
      );
      if (dispatched) await refresh().catch(() => undefined);
    } finally {
      setupAction.current = "";
      setBusy("");
    }
  }
  async function assess() {
    if (
      !recipe ||
      !coordinator ||
      busy ||
      setupAction.current ||
      !access.deliver ||
      !projectAllowed ||
      invalidSettings
    )
      return;
    const assessedKey = assessmentKey;
    const assessedSequence = ++assessmentSequence.current;
    setupAction.current = "assess";
    setReadiness(null);
    setBusy("assess");
    setError("");
    try {
      await authorizeSetupAction();
      const result = await api<TaskAssessment>("/project/assess", {
        method: "POST",
        body: JSON.stringify({
          workspace: taskWorkspace,
          checks,
          package_roots: parentTask?.spec?.package_roots || [],
          participants: [coordinator, ...team],
        }),
      });
      if (
        alive.current &&
        onlineRef.current &&
        assessmentKeyRef.current === assessedKey &&
        assessmentSequence.current === assessedSequence
      ) {
        readinessKey.current = assessedKey;
        setReadiness({ ...result, assessed_at: new Date().toISOString() });
      }
    } catch (failure) {
      if (
        alive.current &&
        assessmentKeyRef.current === assessedKey &&
        assessmentSequence.current === assessedSequence
      )
        setError(messageOf(failure));
    } finally {
      setupAction.current = "";
      setBusy("");
    }
  }
  async function saveRecipe(update = false) {
    if (!recipe || !coordinator || busy || !access.deliver) return;
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
  async function act(
    action: "approve" | "reject" | "resume" | "cancel" | "apply",
  ) {
    if (
      !selected ||
      busy ||
      (action === "approve" || action === "reject"
        ? !reviewAccess
        : !access.deliver)
    )
      return;
    const actingId = selected.id;
    setBusy(action);
    setError("");
    setNotice("");
    try {
      const deciding = action === "approve" || action === "reject";
      const value = await api<Workflow>(
        `/workflows/${selected.id}/${deciding ? (selected.schema_version === "2.0" ? "approve" : "decision") : action}`,
        {
          method: "POST",
          ...(deciding || action === "apply"
            ? {
                body: JSON.stringify({
                  ...(action !== "apply" ? { action } : {}),
                  ...(selected.schema_version === "2.0" || action === "apply"
                    ? {
                        request_id: workflowOperationId(
                          JSON.stringify([
                            caller?.actor || "local",
                            selected.workspace,
                            selected.id,
                          ]),
                          action,
                          selected.candidate?.digest || "",
                        ),
                      }
                    : {}),
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
    if (!selected?.spec || busy || !access.deliver) return;
    const savedRecipe = selected.template_details
      ? {
          ...selected.template_details,
          instructions:
            selected.task_settings?.instructions ??
            selected.template_details.instructions,
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
  async function reviseCandidate(
    findings: { review: number; finding: number }[] = [],
  ) {
    if (!selected?.candidate || busy || !access.deliver) return;
    const correction = feedbackDrafts[selected.id]?.trim();
    if (!correction) {
      setError(
        "Describe the correction in the direction field before revising.",
      );
      return;
    }
    setBusy("revise");
    setError("");
    const body = {
      candidate_digest: selected.candidate.digest,
      correction,
      findings,
    };
    const signature = JSON.stringify({ parent: selected.id, ...body });
    if (pendingStart.current?.signature !== signature)
      pendingStart.current = { id: crypto.randomUUID(), signature };
    try {
      const value = await api<Workflow>(`/workflows/${selected.id}/revise`, {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: pendingStart.current.id }),
      });
      pendingStart.current = null;
      selectedId.current = value.id;
      setSelected(value);
      setNotice(
        "Revision started from the saved candidate. Fresh checks, review and approval are required.",
      );
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function openRelated(id: string) {
    const recent = history.find((row) => row.id === id);
    if (recent) {
      await choose(recent);
      return;
    }
    const request = ++navigationRequest.current;
    const scope = authorityScopeRef.current;
    const current = () =>
      alive.current &&
      navigationRequest.current === request &&
      authorityScopeRef.current === scope &&
      selectedId.current === id;
    selectedId.current = id;
    setBusy("open");
    setError("");
    try {
      const value = await api<Workflow>(`/workflows/${id}`);
      if (current()) {
        setSelected(value);
        setComposing(false);
        setQueueOpen(false);
        focusNavigation(() =>
          current()
            ? document.getElementById("selected-task-title") ||
              taskMainRef.current
            : null,
        );
        window.history.replaceState(
          null,
          "",
          `${location.pathname}${location.search}#task=${id}`,
        );
      }
    } catch (failure) {
      if (current()) setError(messageOf(failure));
    } finally {
      if (current()) setBusy((value) => (value === "open" ? "" : value));
    }
  }
  async function updateReview(
    action: "reviewer" | "comment",
    body: Record<string, unknown>,
  ) {
    if (
      !selected ||
      busy ||
      (action === "reviewer" ? !access.deliver : !access.review)
    )
      return;
    const actingId = selected.id;
    setBusy(action);
    setError("");
    if (action === "comment") {
      const signature = JSON.stringify(body);
      const previous = pendingComments.current.get(actingId);
      const id =
        previous?.signature === signature ? previous.id : crypto.randomUUID();
      pendingComments.current.set(actingId, { signature, id });
      body = { ...body, request_id: id };
    }
    try {
      const value = await api<Workflow>(`/workflows/${actingId}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (action === "comment") pendingComments.current.delete(actingId);
      if (alive.current && selectedId.current === actingId) setSelected(value);
      await refresh();
    } catch (failure) {
      if (alive.current && selectedId.current === actingId)
        setError(messageOf(failure));
    } finally {
      if (alive.current) setBusy("");
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
  const effectiveFilter = view === "inbox" ? "your-review" : filter;
  const inView = (w: Workflow, id: string) =>
    id === "all" ||
    (id === "your-review"
      ? workflowInReviewInbox(w, caller, viaMachine(), teamWorkspace)
      : workflowGroup(w.status, w.decision?.action) === id);
  const visible = projectHistory.filter(
    (w) =>
      inView(w, effectiveFilter) &&
      `${w.title} ${w.workspace} ${w.template.name} ${w.id}`
        .toLowerCase()
        .includes(search.toLowerCase().trim()),
  );
  useEffect(() => {
    if (view !== "inbox") return;
    setComposing(false);
    setArchiveView(false);
    if (!online || loading || historyState !== "ready" || !authorityLoaded)
      return;
    const waiting = projectHistory.filter((w) =>
      workflowInReviewInbox(w, caller, viaMachine(), teamWorkspace),
    );
    if (waiting.some((w) => w.id === selectedId.current)) return;
    if (waiting[0]) void choose(waiting[0], false);
    else {
      selectedId.current = null;
      setSelected(null);
    }
  }, [
    view,
    history,
    projectFilter,
    online,
    loading,
    historyState,
    authorityLoaded,
    caller,
    teamWorkspace,
  ]);
  function newTask() {
    if (busy || !access.deliver) return;
    firstLoad.current = false;
    setComposing(true);
    setArchiveView(false);
    setQueueOpen(false);
    setNotice("");
    if (parentTask) {
      setParentTask(null);
      setPrompt("");
      const current =
        recipes.find((item) => item.id === recipe?.id) || recipes[0];
      if (current) chooseRecipe(current);
    }
    if (projectFilter) onWorkspace(projectFilter);
    focusNavigation(() => document.getElementById("workflow-prompt"));
  }
  useEffect(() => {
    if (
      !newTaskRequest ||
      composedRequest.current === newTaskRequest.sequence ||
      !access.deliver ||
      busy ||
      view !== "tasks"
    )
      return;
    composedRequest.current = newTaskRequest.sequence;
    firstLoad.current = false;
    if (parentTask) {
      setPrompt("");
      const current =
        recipes.find((item) => item.id === recipe?.id) || recipes[0];
      if (current) chooseRecipe(current);
    }
    setParentTask(null);
    setComposing(true);
    setArchiveView(false);
    setQueueOpen(false);
    setProjectFilter(newTaskRequest.workspace);
    setNotice("");
    focusNavigation(() => document.getElementById("workflow-prompt"));
  }, [newTaskRequest, access.deliver, busy, view]);
  const ready =
    !!selected &&
    online &&
    historyState === "ready" &&
    reviewAccess &&
    canApprove(selected.status, selected.candidate, selected.decision) &&
    (!caller?.team ||
      (selected.requester !== caller.actor &&
        (!selected.reviewer || selected.reviewer === caller.actor)));
  const taskSettingsEdits =
    !!recipe &&
    (instructions !== recipe.instructions ||
      JSON.stringify(checks) !== JSON.stringify(recipe.checks));
  const invalidSettings =
    !Number.isInteger(minutes) ||
    minutes < 1 ||
    minutes > 240 ||
    !Number.isInteger(turns) ||
    turns < 2 ||
    turns > 60 ||
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
      <div className="task-browser-bar">
        <button
          ref={queueToggleRef}
          className="text-button task-browser-toggle"
          aria-label={view === "inbox" ? "Review queue" : "Task list"}
          aria-expanded={queueOpen}
          aria-controls="project-task-browser"
          onClick={() => (queueOpen ? closeQueue() : openQueue())}
        >
          <WorkIcon name="stack" />
          {view === "inbox" ? "Review queue" : "Task list"}
          <span className="task-browser-count">
            {historyState === "ready" && online ? visible.length : "—"}
          </span>
        </button>
        <span className="task-browser-summary">
          {historyState === "ready" && online
            ? `${approvalCount} awaiting approval · ${runningCount} in progress`
            : "Task counts unavailable"}
        </span>
        {view === "tasks" && access.deliver && (
          <button
            className="new-task-button"
            disabled={!!busy || !access.deliver}
            onClick={newTask}
          >
            <WorkIcon name="plus" /> New task
          </button>
        )}
      </div>
      <aside
        id="project-task-browser"
        className="task-queue"
        aria-label="Project tasks"
        hidden={!queueOpen}
      >
        <div className="queue-heading">
          <h2>{view === "inbox" ? "Review inbox" : "Task browser"}</h2>
          <button
            className="icon-button queue-dismiss"
            aria-label="Hide task list"
            onClick={closeQueue}
          >
            <WorkIcon name="close" />
          </button>
        </div>
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
          {(view === "inbox"
            ? [["your-review", "Awaiting your review", "review"]]
            : [
                ["all", "All tasks", "stack"],
                ["approval", "Awaiting approval", "review"],
                ...(access.deliver
                  ? [["delivery", "Ready for delivery", "arrow"]]
                  : []),
                ["running", "In progress", "activity"],
                ["attention", "Needs attention", "warning"],
                ["finished", "Completed & closed", "check"],
              ]
          ).map(([id, label, icon]) => (
            <button
              key={id}
              aria-pressed={!archiveView && effectiveFilter === id}
              onClick={() => {
                setFilter(id);
                setArchiveView(false);
              }}
            >
              <WorkIcon name={icon} />
              <span>{label}</span>
              <small>
                {historyState !== "ready" || !online
                  ? "—"
                  : projectHistory.filter((w) => inView(w, id)).length}
              </small>
            </button>
          ))}
          {viaMachine() && view === "tasks" && (
            <button
              aria-pressed={archiveView}
              onClick={() => {
                setArchiveView(true);
                setComposing(false);
                setQueueOpen(false);
                focusNavigation(() => taskMainRef.current);
              }}
            >
              <WorkIcon name="stack" />
              <span>Archived records</span>
            </button>
          )}
        </nav>
        <div className="queue-list-heading">
          <span>
            {search
              ? "Search results"
              : view === "inbox"
                ? "Waiting for you"
                : "Recent tasks"}
          </span>
          <button
            className="icon-button"
            aria-label="Refresh task list"
            onClick={() => void refresh().catch((f) => setError(messageOf(f)))}
          >
            <WorkIcon name="refresh" size={14} />
          </button>
        </div>
        <div className="queue-scroll">
          {historyState === "unavailable" || !online ? (
            <p className="queue-empty">
              Task history unavailable. Counts are unknown.
            </p>
          ) : loading ? (
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
                    <span
                      className={`task-dot ${workflowGroup(w.status, w.decision?.action)}`}
                    />
                    <span className="task-list-content">
                      <strong>{workflowTitle(w)}</strong>
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
          <details
            key={`report:${authorityScope}`}
            className="queue-report-tools"
            onToggle={(event) => {
              if (event.currentTarget.open) setReportScope(authorityScope);
            }}
          >
            <summary>Pilot report</summary>
            {reportScope === authorityScope && (
              <PilotMetrics
                workflow={null}
                allowMeasure={false}
                allowLabel={false}
              />
            )}
          </details>
        </div>
        <div className="queue-footer">
          <span>
            <i className={online ? "online-dot" : "offline-dot"} />
            {online ? "Worker connected" : "Worker offline"}
          </span>
          <button
            className="icon-button"
            aria-label="Provider connections"
            onClick={(event) => openConnections(event.currentTarget)}
          >
            <WorkIcon name="settings" size={16} />
          </button>
        </div>
      </aside>
      <div className="task-main" ref={taskMainRef} tabIndex={-1}>
        {viaMachine() && authorityLoaded && !caller && (
          <div className="task-alert" role="alert">
            Update Parallax on this machine to use versioned tasks and separate
            delivery. Existing personal task approval remains available.
          </div>
        )}
        {contextError && online && (
          <div className="task-alert" role="alert">
            <p>{contextError}</p>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                contextNeedsReload
                  ? location.reload()
                  : setContextRevision((value) => value + 1)
              }
            >
              {contextNeedsReload ? "Reload Studio" : "Refresh project access"}
            </button>
          </div>
        )}
        {view === "tasks" &&
          authorityLoaded &&
          !access.deliver &&
          !selected &&
          online &&
          historyState === "ready" && (
            <div className="task-loading" role="status">
              <h2>No tasks to inspect</h2>
              <p>
                Tasks shared with your role appear here. Open Review inbox for
                work awaiting your decision.
              </p>
            </div>
          )}
        {setupError && online && historyState !== "unavailable" && (
          <div className="task-alert" role="alert">
            <WorkIcon name="warning" />
            <p>{setupError}</p>
          </div>
        )}
        {error && online && (
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
        {!archiveView && (!online || historyState === "unavailable") && (
          <div className="task-availability" role="status">
            <div>
              <strong>
                {!online ? "Machine offline" : "Task history unavailable"}
              </strong>
              <p>
                {teamWorkspace
                  ? "Team task history needs a connected machine and current project permissions. Counts are unknown; reconnect to inspect evidence or approve work."
                  : "Task counts are unknown. Any displayed personal evidence may be out of date. Reconnect before starting or approving work."}
              </p>
              {online && historyError && <p>{historyError}</p>}
            </div>
            {onReconnect && (
              <button className="secondary-button" onClick={onReconnect}>
                Reconnect machine
              </button>
            )}
            {online && (
              <button className="text-button" onClick={() => void refresh()}>
                Retry task history
              </button>
            )}
          </div>
        )}
        {!archiveView &&
          evidenceTransport?.status === "local_evidence_only" && (
            <div className="task-availability" role="status">
              <div>
                <strong>
                  Some full evidence is available only on the machine
                </strong>
                <p>
                  Full evidence is retained locally.{" "}
                  {evidenceTransport.problem_count} record
                  {evidenceTransport.problem_count === 1
                    ? " exceeds"
                    : "s exceed"}{" "}
                  the relay limit and cannot be inspected in remote Studio.
                  Remote approval is blocked for affected candidates. Open local
                  Studio on the machine to inspect the saved evidence.
                </p>
                {evidenceTransport.detail && <p>{evidenceTransport.detail}</p>}
              </div>
            </div>
          )}
        {archiveView && <ArchivedHistory />}
        <div
          className="task-compose-scroll"
          hidden={
            view === "inbox" ||
            !access.deliver ||
            archiveView ||
            (!composing &&
              (!!selected ||
                loading ||
                !online ||
                historyState === "unavailable"))
          }
        >
          <fieldset
            disabled={!!busy && busy !== "assess"}
            className="composer-fieldset"
          >
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
                    onClick={() => {
                      setComposing(false);
                      focusNavigation(
                        () =>
                          document.getElementById("selected-task-title") ||
                          taskMainRef.current,
                      );
                    }}
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
                  <strong>{workflowTitle(parentTask)}</strong>
                  <p>
                    A new candidate from the current project. This task keeps
                    the original workflow version and checks; its time and
                    decision limits can be raised below. Unapplied code from the
                    parent is not reused.
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
                {paired ? (
                  <select
                    aria-label="Workflow project"
                    value={
                      approvedProjects.includes(taskWorkspace)
                        ? taskWorkspace
                        : ""
                    }
                    disabled={!!parentTask || !authorityLoaded || !online}
                    onChange={(e) => onWorkspace(e.target.value)}
                  >
                    <option value="">Choose an approved project</option>
                    {approvedProjects.map((path) => (
                      <option key={path} value={path}>
                        {path}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    list="task-projects"
                    aria-label="Workflow project"
                    readOnly={!!parentTask}
                    value={taskWorkspace}
                    onChange={(e) => onWorkspace(e.target.value)}
                    placeholder="Absolute path to an approved project"
                  />
                )}
                {!paired && (
                  <datalist id="task-projects">
                    {projects.map((path) => (
                      <option key={path} value={path} />
                    ))}
                  </datalist>
                )}
              </label>
              <div className="composer-setup" aria-label="Project setup">
                <div>
                  <h2 role="status">
                    {busy === "assess"
                      ? "Inspecting project setup…"
                      : !currentReadiness
                        ? "Setup not inspected"
                        : readinessBlocked ||
                            currentReadiness.status === "needs_configuration"
                          ? "Setup needs attention"
                          : currentReadiness.status === "ready"
                            ? "Setup inspected"
                            : "Assessment received"}
                  </h2>
                  <p>
                    {currentReadiness
                      ? "Checks have not run. Provider inference and quota remain unverified."
                      : "Inspect the environment, selected providers and check plan. This does not start a task."}
                  </p>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={
                    !online ||
                    !taskWorkspace ||
                    !recipe ||
                    invalidSettings ||
                    !access.deliver ||
                    !projectAllowed
                  }
                  aria-disabled={!!busy}
                  onClick={() => void assess()}
                >
                  {busy === "assess" ? "Checking…" : "Check readiness"}
                </button>
              </div>
              {paired &&
                !contextError &&
                (!authorityLoaded || !projectAllowed) && (
                  <div className="composer-project-notice" role="status">
                    <p>
                      {!online
                        ? "Reconnect this worker to refresh project access."
                        : !authorityLoaded
                          ? "Checking current project permissions…"
                          : "Choose an approved project. Workspace Owners manage project access on this worker."}
                    </p>
                    {online && authorityLoaded && (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => setContextRevision((value) => value + 1)}
                      >
                        Refresh project access
                      </button>
                    )}
                  </div>
                )}
              {!!currentReadiness?.issues?.length && (
                <ul className="composer-setup-issues" aria-label="Setup issues">
                  {currentReadiness.issues.map((issue, index) => (
                    <li
                      key={index}
                      className={issue.severity === "blocker" ? "blocker" : ""}
                    >
                      <strong>
                        {issue.severity === "blocker"
                          ? "Blocked: "
                          : "Attention: "}
                      </strong>
                      {issue.message}
                      {issue.provider && (
                        <code>Provider: {issue.provider}</code>
                      )}
                      {issue.root && <code>{issue.root}</code>}
                    </li>
                  ))}
                </ul>
              )}
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
              {currentReadiness && (
                <TaskPreflight
                  assessment={currentReadiness}
                  showIssues={false}
                  configuredChecks={checks}
                  disabled={!!busy || !!parentTask}
                  onUseChecks={(value) => {
                    setChecks(value);
                    setInvalidChecks(new Set());
                    setNotice(
                      "Detected checks added to this task. Inspect setup again to refresh the observation.",
                    );
                  }}
                />
              )}
              <div className="compose-options">
                <label>
                  Workflow
                  <select
                    aria-label="Task workflow"
                    disabled={!!parentTask}
                    value={recipe ? recipeKey(recipe) : ""}
                    onChange={(e) => {
                      const next = recipes.find(
                        (r) => recipeKey(r) === e.target.value,
                      );
                      if (next) chooseRecipe(next);
                    }}
                  >
                    {recipe &&
                      !recipes.some(
                        (r) => recipeKey(r) === recipeKey(recipe),
                      ) && (
                        <option value={recipeKey(recipe)}>
                          {recipe.name} · v{recipe.version} (
                          {parentTask ? "saved task" : "draft selection"})
                        </option>
                      )}
                    {recipes.map((r) => (
                      <option key={recipeKey(r)} value={recipeKey(r)}>
                        {r.name} · v{r.version}
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
                  Team:{" "}
                  {team
                    .map(
                      (p) =>
                        `${LABELS[p.provider] || p.provider} (${p.role || "generalist"})`,
                    )
                    .join(", ")}
                </span>
                <span>
                  Coordinator:{" "}
                  {coordinator
                    ? LABELS[coordinator.provider] || coordinator.provider
                    : "Not selected"}
                </span>
                <span>{minutes} min limit</span>
              </div>
              <details className="workflow-settings">
                <summary>Configure team, task instructions, and checks</summary>
                <p className="workflow-muted">
                  Use different providers for implementation and independent
                  review. Provider usage is charged to your configured accounts.
                </p>
                <button
                  className="text-button"
                  onClick={(event) =>
                    openConnections(event.currentTarget, true)
                  }
                >
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
                <label className="workflow-field">
                  <span>Coordinator decisions</span>
                  <input
                    type="number"
                    min={2}
                    max={60}
                    value={turns}
                    onChange={(e) => setTurns(Number(e.target.value))}
                  />
                </label>
                <p className="workflow-muted">
                  The most planning and repair decisions the coordinator may
                  make. Raise it when a task stopped at its decision limit.
                </p>
                <div hidden={!!parentTask}>
                  <label className="workflow-field">
                    <span>Task instructions</span>
                    <textarea
                      rows={3}
                      value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                      maxLength={4000}
                    />
                  </label>
                  <p className="workflow-muted">
                    Instructions and checks apply to this task. Your saved
                    workflow stays unchanged. Save as a recipe only when you
                    want to reuse these settings.
                  </p>
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
                      Leave this empty to use the project's detected checks. Add
                      explicit commands when your project needs a particular
                      test or package root.
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
                        !recipeName.trim() ||
                        !access.deliver
                      }
                      onClick={() => void saveRecipe()}
                    >
                      Save as recipe
                    </button>
                    {recipe && !recipe.builtin && (
                      <button
                        className="secondary-button"
                        disabled={
                          !!busy ||
                          !online ||
                          invalidSettings ||
                          !access.deliver
                        }
                        onClick={() => void saveRecipe(true)}
                      >
                        Save new version
                      </button>
                    )}
                  </div>
                </div>
              </details>

              {viaMachine() && (
                <label>
                  Delivery
                  <select
                    value={githubBinding}
                    onChange={(e) => setGithubBinding(e.target.value)}
                  >
                    <option value="">Apply locally after approval</option>
                    {githubBindingsForProject(
                      githubBindings,
                      taskWorkspace,
                      executionWorker,
                    ).map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.full_name} · {b.base} · draft PR
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {readinessBlocked && (
                <p className="task-offline" role="status">
                  Resolve the blocked setup, then check readiness again to
                  start.
                </p>
              )}
              <p className="workflow-muted">
                {minutes} minutes limits execution time across restarts.
                Approval waiting time is excluded. Provider usage is charged to
                your configured accounts; this time limit is not a spending cap.
              </p>
              <div className="compose-submit">
                <button
                  className="primary-button"
                  disabled={
                    loading ||
                    !!busy ||
                    !online ||
                    !taskWorkspace ||
                    !projectAllowed ||
                    !prompt.trim() ||
                    !coordinator ||
                    readinessBlocked ||
                    invalidSettings ||
                    !access.deliver
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
        {view === "inbox" &&
          online &&
          !loading &&
          historyState === "ready" &&
          !selected && (
            <div className="task-loading" role="status">
              <WorkIcon name="check" size={28} />
              <h2>No tasks awaiting your review</h2>
              <p>Assigned and eligible candidate reviews will appear here.</p>
            </div>
          )}
        {!archiveView &&
        !composing &&
        selected &&
        (!teamWorkspace || (online && historyState === "ready")) ? (
          <TaskWorkspace
            visible={active}
            key={`task:${selected.id}`}
            workflow={selected}
            // Without team authority, Studio is the local owner, recorded as "local".
            viewerActor={caller ? caller.actor : authorityLoaded ? "local" : undefined}
            actorDirectory={members}
            feedback={feedbackDrafts[selected.id] || ""}
            sending={sendingTasks.has(selected.id)}
            sent={sendNotices[selected.id] || ""}
            onSend={() => void sendDirection(selected)}
            parentTitle={(() => {
              const parent = history.find(
                (row) => row.id === selected.parent_workflow_id,
              );
              return parent ? workflowTitle(parent) : undefined;
            })()}
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
            approvalHint={
              caller?.team && selected.status === "awaiting_approval"
                ? selected.requester === caller.actor
                  ? "A different member must approve this candidate, including for Owners."
                  : selected.reviewer && selected.reviewer !== caller.actor
                    ? "Only the assigned reviewer can approve this candidate."
                    : undefined
                : undefined
            }
            busy={busy}
            online={online}
            onAction={(action) => void act(action)}
            onAgain={useAgain}
            onRevise={(findings) => void reviseCandidate(findings)}
            canDeliver={access.deliver}
            members={
              caller?.team
                ? members.filter((member) =>
                    caller.reviewers_by_project?.[selected.workspace]?.includes(
                      member.account,
                    ),
                  )
                : members
            }
            onAssign={(reviewer) => void updateReview("reviewer", { reviewer })}
            onRefresh={() => void refresh()}
            onComment={() =>
              void updateReview("comment", {
                message: feedbackDrafts[selected.id] || "",
              })
            }
            onInspect={onInspect}
            reviewLink={
              teamWorkspace && accountIdentity?.workspace && executionWorker
                ? reviewLink(location.origin, {
                    workspace: accountIdentity.workspace,
                    worker: executionWorker,
                    task: selected.id,
                  }) || undefined
                : undefined
            }
            renderEvidence={renderEvidence}
            measurements={
              <PilotMetrics
                key={`metrics:${selected.id}`}
                workflow={selected}
                allowMeasure={
                  active &&
                  online &&
                  access.deliver &&
                  (!paired || approvedProjects.includes(selected.workspace))
                }
                allowLabel={
                  active &&
                  online &&
                  access.review &&
                  (!paired || approvedProjects.includes(selected.workspace))
                }
              />
            }
          />
        ) : !archiveView && !composing && loading ? (
          <div className="task-loading" role="status">
            <WorkIcon name="stack" size={28} />
            <p>Opening your workspace…</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
