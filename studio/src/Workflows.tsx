import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, apiUrl, messageOf, viaMachine } from "./api";
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
  workflowStep,
} from "./workflow-state";
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
type Workflow = {
  id: string;
  title: string;
  prompt?: string;
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
  workspace,
  onWorkspace,
  online,
  onInspect,
  onConnections,
  renderParticipant,
  renderCheck,
}: {
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
  const [readiness, setReadiness] = useState<{
    status: string;
    issues: { severity: string; message: string }[];
  } | null>(null);
  const [patch, setPatch] = useState<string | null>(null);
  const [patchError, setPatchError] = useState("");
  const [showPatch, setShowPatch] = useState(false);
  const pendingStart = useRef<{ signature: string; id: string } | null>(null);
  const alive = useRef(true);
  const detailRef = useRef<HTMLElement>(null);

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
              ? "Update Parallax on this machine to use saved workflows. New run is still available from the sidebar."
              : messageOf(failure),
          );
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    let fetching = false;
    const timer = window.setInterval(
      () => {
        if (document.hidden || fetching) return;
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
  }, [workspace, coordinator, team, minutes, checks]);
  useEffect(() => {
    setPatch(null);
    setPatchError("");
    setShowPatch(false);
  }, [selected?.id]);
  useEffect(() => {
    if (!showPatch || !selected?.run_id) return;
    const abort = new AbortController();
    void fetch(apiUrl(`/runs/${selected.run_id}/patch`), {
      credentials: "same-origin",
      signal: abort.signal,
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Unable to load this patch. Reconnect and retry.");
        return response.text();
      })
      .then((value) => {
        if (!abort.signal.aborted) setPatch(value);
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setPatchError(messageOf(failure));
      });
    return () => abort.abort();
  }, [showPatch, selected?.run_id]);

  async function choose(value: Workflow) {
    selectedId.current = value.id;
    setSelected(value);
    setError("");
    try {
      await refresh();
      requestAnimationFrame(() => {
        detailRef.current?.focus();
        detailRef.current?.scrollIntoView({ block: "start" });
      });
    } catch (failure) {
      setError(messageOf(failure));
    }
  }
  async function start() {
    if (!recipe || !coordinator) return;
    setBusy("start");
    setError("");
    setNotice("");
    const body = {
      template_id: recipe.id,
      template_version: recipe.version,
      workspace,
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
      await refresh();
      setNotice(
        "Work started on your machine. Your project waits for your approval.",
      );
      requestAnimationFrame(() => {
        detailRef.current?.focus();
        detailRef.current?.scrollIntoView({ block: "start" });
      });
    } catch (failure) {
      setError(
        `${messageOf(failure)} Check recent workflows before retrying if the connection timed out.`,
      );
      await refresh().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }
  async function assess() {
    if (!recipe || !coordinator) return;
    setBusy("assess");
    setError("");
    try {
      setReadiness(
        await api("/project/assess", {
          method: "POST",
          body: JSON.stringify({
            workspace,
            checks,
            participants: [coordinator, ...team],
          }),
        }),
      );
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function saveRecipe(update = false) {
    if (!recipe || !coordinator) return;
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
      setRecipes(await api<Recipe[]>("/workflow-templates"));
      chooseRecipe(saved);
      setNotice(
        `Saved ${saved.name}, version ${saved.version}. Existing workflows keep their original settings.`,
      );
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy("");
    }
  }
  async function act(action: "approve" | "reject" | "resume" | "cancel") {
    if (!selected) return;
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
      setSelected(value);
      await refresh();
    } catch (failure) {
      setError(messageOf(failure));
      await refresh().catch(() => undefined);
    } finally {
      setBusy("");
    }
  }
  function useAgain() {
    if (!selected?.spec) return;
    const savedRecipe = recipes.find((r) => r.id === selected.template.id);
    if (savedRecipe) chooseRecipe(savedRecipe);
    setPrompt(selected.prompt || selected.title);
    onWorkspace(selected.workspace);
    setCoordinator(selected.spec.coordinator);
    setTeam(selected.spec.team);
    setMinutes(selected.spec.limits.minutes);
    setNotice(
      "Loaded the previous task and team. Review the recipe and outcome before starting a new candidate.",
    );
    document.getElementById("workflow-prompt")?.focus();
  }

  const approvalCount = history.filter(
    (w) => workflowGroup(w.status) === "approval",
  ).length;
  const runningCount = history.filter(
    (w) => workflowGroup(w.status) === "running",
  ).length;
  const visible = history.filter(
    (w) => filter === "all" || workflowGroup(w.status) === filter,
  );
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
    <div className="workflow-home">
      <header className="workflow-hero">
        <div>
          <span className="eyebrow">YOUR CODING WORKFLOWS</span>
          <h1>From a task to a change you trust.</h1>
          <p>
            Choose a recipe. Let your coding team prepare and check the change.
            You decide when it reaches your project.
          </p>
        </div>
        <div className="workflow-counts" aria-label="Workflow overview">
          <button
            aria-label={`${approvalCount} workflows ready for approval`}
            onClick={() => {
              setFilter("approval");
              document
                .getElementById("workflow-history")
                ?.scrollIntoView({ block: "start" });
            }}
          >
            <strong>{approvalCount}</strong>
            <span>ready for you</span>
          </button>
          <button
            aria-label={`${runningCount} workflows in progress`}
            onClick={() => {
              setFilter("running");
              document
                .getElementById("workflow-history")
                ?.scrollIntoView({ block: "start" });
            }}
          >
            <strong>{runningCount}</strong>
            <span>in progress</span>
          </button>
        </div>
      </header>
      {error && (
        <div className="alert" role="alert">
          <p>{error}</p>
          <button className="text-button" onClick={() => setError("")}>
            Dismiss
          </button>
        </div>
      )}
      {notice && (
        <p className="workflow-notice" role="status">
          {notice}
        </p>
      )}
      {!online && (
        <p className="workflow-notice">
          This machine is offline. Saved evidence may be out of date. Reconnect
          it to start, approve, or resume work.
        </p>
      )}
      <section
        className="workflow-recipes"
        aria-label="Choose a workflow recipe"
      >
        {recipes
          .filter((value) => value.builtin)
          .map((value, index) => (
            <button
              key={value.id}
              className={`workflow-recipe ${recipe?.id === value.id ? "selected" : ""}`}
              onClick={() => chooseRecipe(value)}
              aria-pressed={recipe?.id === value.id}
            >
              <span className="workflow-recipe-index">
                {value.builtin ? `0${index + 1}` : "SAVED"}
              </span>
              <strong>{value.name}</strong>
              <span>
                {value.description ||
                  "Your saved team, instructions, and checks."}
              </span>
              <small>
                {value.builtin
                  ? "Built-in recipe"
                  : `Your recipe · v${value.version}`}
              </small>
            </button>
          ))}
      </section>
      {recipes.some((value) => !value.builtin) && (
        <label className="workflow-saved-picker">
          <span>Your saved recipes</span>
          <select
            aria-label="Saved workflow recipe"
            value={recipe && !recipe.builtin ? recipe.id : ""}
            onChange={(event) => {
              const saved = recipes.find(
                (value) => value.id === event.target.value,
              );
              if (saved) chooseRecipe(saved);
            }}
          >
            <option value="" disabled>
              Choose a saved recipe…
            </option>
            {recipes
              .filter((value) => !value.builtin)
              .map((value) => (
                <option key={value.id} value={value.id}>
                  {value.name} · v{value.version}
                </option>
              ))}
          </select>
        </label>
      )}
      <div className="workflow-columns">
        <section
          className="workflow-compose"
          aria-labelledby="workflow-compose-title"
        >
          <div className="section-heading">
            <div>
              <span className="eyebrow">START SOMETHING</span>
              <h2 id="workflow-compose-title">
                {recipe?.name || "Loading recipes…"}
              </h2>
            </div>
            <span className="workflow-pill">Approval required</span>
          </div>
          <label className="workflow-field">
            <span>Project</span>
            <input
              aria-label="Workflow project"
              value={workspace}
              onChange={(e) => onWorkspace(e.target.value)}
              placeholder="Absolute path to an approved project"
            />
          </label>
          <label className="workflow-field">
            <span>What should change?</span>
            <textarea
              id="workflow-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              maxLength={12000}
              placeholder={
                recipe?.id === "fix-a-bug"
                  ? "What breaks, how to reproduce it, and what should happen instead…"
                  : "Describe the outcome and how you will know it works…"
              }
              rows={5}
            />
          </label>
          <div className="workflow-team-summary">
            <span>
              {team.map((p) => LABELS[p.provider] || p.provider).join(" + ") ||
                "Choose a builder"}{" "}
              builds
            </span>
            <span>
              {coordinator
                ? LABELS[coordinator.provider] || coordinator.provider
                : "Choose a coordinator"}{" "}
              coordinates and checks
            </span>
          </div>
          <details className="workflow-settings">
            <summary>Team, time limit, and recipe settings</summary>
            <p className="workflow-muted">
              Use different providers for implementation and independent review.
              Provider usage is charged to your configured accounts.
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
              The limit carries across restarts. Time waiting for your approval
              does not consume it.
            </p>
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
                Leave this empty to use the project's detected checks. Save
                explicit commands when your project needs a particular test or
                package root.
              </p>
              {checks.map((check, index) => (
                <div key={`${recipe?.id}-${recipe?.version}-${index}`}>
                  {renderCheck(
                    check,
                    index,
                    (value) =>
                      setChecks((current) =>
                        current.map((item, i) => (i === index ? value : item)),
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
                  !!busy || !online || invalidSettings || !recipeName.trim()
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
          </details>
          {instructionEdits && (
            <p className="workflow-notice">
              Save your instructions and checks as a recipe before starting.
            </p>
          )}
          {readiness && (
            <div
              className={`workflow-readiness ${readiness.status}`}
              role="status"
            >
              <strong>
                {readiness.status === "ready"
                  ? "Project is ready"
                  : "Project setup needs attention"}
              </strong>
              {readiness.issues.map((issue, index) => (
                <p key={index}>{issue.message}</p>
              ))}
            </div>
          )}
          <div className="workflow-actions">
            <button
              className="secondary-button"
              disabled={
                !!busy || !online || !workspace || !recipe || invalidSettings
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
                !workspace ||
                !prompt.trim() ||
                !coordinator ||
                instructionEdits ||
                invalidSettings ||
                minutes < 1 ||
                minutes > 240
              }
              onClick={() => void start()}
            >
              {busy === "start" ? "Starting…" : "Prepare a verified change"}
              <span aria-hidden="true">↗</span>
            </button>
          </div>
          <p className="workflow-muted">
            Work runs on your selected machine. Your working project stays
            unchanged until you approve the verified candidate.
          </p>
        </section>
        <section
          className="workflow-activity"
          id="workflow-history"
          aria-labelledby="workflow-activity-title"
        >
          <div className="section-heading">
            <div>
              <span className="eyebrow">PICK UP WHERE YOU LEFT OFF</span>
              <h2 id="workflow-activity-title">Recent workflows</h2>
            </div>
            <button
              className="text-button"
              onClick={() =>
                void refresh().catch((failure) => setError(messageOf(failure)))
              }
            >
              Refresh
            </button>
          </div>
          <div className="workflow-filters" aria-label="Filter workflows">
            {[
              ["all", "All"],
              ["approval", "For approval"],
              ["running", "Running"],
              ["attention", "Needs attention"],
              ["finished", "Finished"],
            ].map(([id, label]) => (
              <button
                key={id}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          {loading ? (
            <p role="status">Loading saved work…</p>
          ) : !visible.length ? (
            <div className="workflow-empty">
              <span aria-hidden="true">◇</span>
              <h3>
                {history.length
                  ? "Nothing in this view"
                  : "Your next change starts here"}
              </h3>
              <p>
                {history.length
                  ? "Choose another filter to see your workflows."
                  : "Start with a small, specific task. Its progress, candidate, and approval will stay here when you return."}
              </p>
            </div>
          ) : (
            <ul className="workflow-list">
              {visible.map((value) => (
                <li key={value.id}>
                  <button
                    onClick={() => void choose(value)}
                    aria-pressed={selected?.id === value.id}
                  >
                    <span
                      className={`workflow-status ${workflowGroup(value.status)}`}
                    >
                      {workflowLabels[value.status] || value.status}
                    </span>
                    <strong>{value.title}</strong>
                    <span>
                      {shortProject(value.workspace)} · {value.template.name}
                    </span>
                    <small>{when(value.updated_at)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      {selected && (
        <section
          className="workflow-detail"
          ref={detailRef}
          tabIndex={-1}
          aria-labelledby="workflow-detail-title"
        >
          <header>
            <div>
              <span
                className={`workflow-status ${workflowGroup(selected.status)}`}
              >
                {workflowLabels[selected.status] || selected.status}
              </span>
              <h2 id="workflow-detail-title">{selected.title}</h2>
              <p>
                {shortProject(selected.workspace)} · {selected.template.name} v
                {selected.template.version}
                {selected.runtime_seconds
                  ? ` · ${Math.ceil(selected.runtime_seconds / 60)} min execution time`
                  : ""}
              </p>
            </div>
            {selected.run_id && (
              <button
                className="secondary-button"
                onClick={() => onInspect(selected.run_id!)}
              >
                Open run evidence
              </button>
            )}
          </header>
          <ol className="workflow-steps" aria-label="Workflow stages">
            {[
              "Prepare and verify",
              "Your approval",
              "Apply change",
              "Receipt",
            ].map((label, index) => (
              <li
                key={label}
                className={
                  index < workflowStep(selected.status)
                    ? "done"
                    : index === workflowStep(selected.status)
                      ? "current"
                      : ""
                }
                aria-current={
                  index === workflowStep(selected.status) ? "step" : undefined
                }
              >
                <span>{index + 1}</span>
                {label}
              </li>
            ))}
          </ol>
          {selected.error && (
            <p className="workflow-readiness blocked" role="alert">
              {selected.error}
            </p>
          )}
          {selected.status === "preparing" && (
            <p className="workflow-muted" role="status">
              {selected.run_status
                ? `The team is ${selected.run_status.replaceAll("_", " ")}.`
                : "Preparing the project and checking provider settings."}{" "}
              You can leave this page. Work continues while the worker stays
              online.
            </p>
          )}
          {selected.candidate && (
            <>
              <div className="workflow-evidence">
                {selected.candidate.gates.map((gate) => (
                  <div key={gate.id}>
                    <span aria-hidden="true">✓</span>
                    <strong>{gate.label}</strong>
                    <p>{gate.detail}</p>
                  </div>
                ))}
              </div>
              <div className="workflow-candidate">
                <div>
                  <h3>
                    {selected.status === "applied"
                      ? "Change applied"
                      : "Prepared change"}
                  </h3>
                  <p className="workflow-summary">
                    {selected.candidate.summary}
                  </p>
                  <p className="workflow-muted">
                    {selected.candidate.changed_files.length} changed{" "}
                    {selected.candidate.changed_files.length === 1
                      ? "file"
                      : "files"}{" "}
                    · {selected.candidate.check_count} passing{" "}
                    {selected.candidate.check_count === 1 ? "check" : "checks"}
                  </p>
                </div>
                <ul aria-label="Changed files">
                  {selected.candidate.changed_files.map((file) => (
                    <li key={file}>
                      <code>{file}</code>
                    </li>
                  ))}
                </ul>
              </div>
              <details
                className="workflow-patch"
                open={showPatch}
                onToggle={(e) => setShowPatch(e.currentTarget.open)}
              >
                <summary>Inspect the exact patch</summary>
                {patchError ? (
                  <p role="alert">{patchError}</p>
                ) : patch === null ? (
                  <p role="status">Loading patch…</p>
                ) : (
                  <pre>{patch || "No file changes."}</pre>
                )}
              </details>
              {ready && (
                <div className="workflow-approval">
                  <div>
                    <h3>Ready when you are.</h3>
                    <p>
                      Approval applies this candidate to{" "}
                      {shortProject(selected.workspace)}. Parallax checks that
                      the project and evidence still match.
                    </p>
                  </div>
                  <div className="workflow-actions">
                    <button
                      className="secondary-button"
                      disabled={!!busy || !online}
                      onClick={() => void act("reject")}
                    >
                      Decline candidate
                    </button>
                    <button
                      className="primary-button"
                      disabled={!!busy || !online}
                      onClick={() => void act("approve")}
                    >
                      {busy === "approve"
                        ? "Recording approval…"
                        : "Approve and apply"}
                    </button>
                  </div>
                </div>
              )}
              {selected.status === "applied" && selected.run_id && (
                <div className="workflow-success">
                  <strong>Applied with a verification record.</strong>
                  <p>
                    Your staging and unrelated files were preserved by the
                    recorded application checks.
                  </p>
                  <a
                    className="secondary-button"
                    href={apiUrl(`/runs/${selected.run_id}/receipt`)}
                    download
                  >
                    Download verification record
                  </a>
                </div>
              )}
            </>
          )}
          <div className="workflow-actions">
            {["interrupted", "needs_attention"].includes(selected.status) && (
              <button
                className="primary-button"
                disabled={!!busy || !online}
                onClick={() => void act("resume")}
              >
                Resume saved work
              </button>
            )}
            {!["applied", "rejected", "cancelled", "applying"].includes(
              selected.status,
            ) &&
              selected.decision?.action !== "approve" && (
                <button
                  className="secondary-button"
                  disabled={!!busy || !online}
                  onClick={() => void act("cancel")}
                >
                  Stop workflow
                </button>
              )}
            {selected.spec && (
              <button className="text-button" onClick={useAgain}>
                Use this task again
              </button>
            )}
          </div>
          <p className="workflow-muted">
            Verification covers the recorded checks and reviews. It does not
            prove every behavior is correct.
          </p>
        </section>
      )}
    </div>
  );
}
