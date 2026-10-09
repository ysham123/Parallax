import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, apiUrl, messageOf, viaMachine } from "./api";
import { ProviderMark } from "./Brand";
import { RunWorkspace } from "./RunWorkspace";
import { Connections as ConnectionsPanel } from "./Connections";
import { ProjectReadiness } from "./ProjectReadiness";
import { ProjectMemory } from "./ProjectMemory";
import { Recovery } from "./Recovery";
import { Baseline } from "./Baseline";
import { AlphaFeedback } from "./AlphaFeedback";
import { Verification } from "./Verification";
import { ContextDetails, ExplorationDetail, VariantDetail } from "./Exploration";
import { Workflows } from "./Workflows";
import { contextManifest, explorations } from "./run-inspection";
import {
  INITIAL_SPEC,
  connectionProvider,
  type Connection,
  LABELS,
  PROVIDERS,
  type CheckSpec,
  type Data,
  type Participant,
  type Profile,
  type Provider,
  type ProviderId,
  type RunEvent,
  type RunResult,
  type RunSpec,
} from "./types";

type Tab = "workflows" | "team" | "run" | "review";
type ReviewTab = "findings" | "changes" | "checks" | "settings";
type IconName =
  | "connection"
  | "orbit"
  | "team"
  | "run"
  | "review"
  | "arrow"
  | "plus"
  | "close"
  | "refresh"
  | "sun"
  | "moon"
  | "folder"
  | "check"
  | "pause"
  | "stop"
  | "play"
  | "chevron"
  | "settings"
  | "save"
  | "trash"
  | "copy"
  | "external"
  | "clock"
  | "warning"
  | "command";

function Icon({
  name,
  size = 18,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  const paths: Record<IconName, ReactNode> = {
    connection: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M4 12h16M12 4c4 4 4 12 0 16-4-4-4-12 0-16Z" />
      </>
    ),
    orbit: (
      <>
        <ellipse cx="12" cy="12" rx="10" ry="5" transform="rotate(-42 12 12)" />
        <circle cx="12" cy="12" r="2.8" />
        <circle cx="19" cy="5.5" r="1.5" fill="currentColor" stroke="none" />
      </>
    ),
    team: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v2" />
      </>
    ),
    run: (
      <>
        <path d="m8 4 12 8-12 8Z" />
        <path d="M3 5v14" />
      </>
    ),
    review: (
      <>
        <rect x="5" y="3" width="14" height="18" rx="3" />
        <path d="m8.5 11 2 2 5-5M9 17h6" />
      </>
    ),
    arrow: (
      <>
        <path d="M4 12h16m-6-6 6 6-6 6" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M19.5 11a8 8 0 0 0-14-5M4.5 13a8 8 0 0 0 14 5" />
      </>
    ),
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
      </>
    ),
    moon: <path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z" />,
    folder: (
      <path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    ),
    check: <path d="m5 12 4.5 4.5L19 7" />,
    pause: (
      <>
        <path d="M8 5v14M16 5v14" />
      </>
    ),
    stop: <rect x="5" y="5" width="14" height="14" rx="2" />,
    play: <path d="m8 5 11 7-11 7Z" />,
    chevron: <path d="m8 5 7 7-7 7" />,
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="2.5" fill="var(--surface)" />
        <circle cx="15" cy="17" r="2.5" fill="var(--surface)" />
      </>
    ),
    save: (
      <>
        <path d="M4 3h13l4 4v14H3V3Z" />
        <path d="M7 3v6h9V3M7 21v-7h10v7" />
      </>
    ),
    trash: (
      <>
        <path d="M3 6h18M8 6V3h8v3M6 6l1 15h10l1-15M10 10v7m4-7v7" />
      </>
    ),
    copy: (
      <>
        <rect x="8" y="8" width="12" height="13" rx="2" />
        <path d="M16 8V3H3v13h5" />
      </>
    ),
    external: (
      <>
        <path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    warning: (
      <>
        <path d="m12 3 10 18H2Z" />
        <path d="M12 9v5m0 3v.1" />
      </>
    ),
    command: (
      <>
        <path d="M8 8h8v8H8ZM8 8H5a3 3 0 1 1 3-3v3Zm8 0V5a3 3 0 1 1 3 3h-3Zm0 8h3a3 3 0 1 1-3 3v-3Zm-8 0v3a3 3 0 1 1-3-3h3Z" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

const text = (value: unknown, fallback = "") =>
  value === undefined || value === null
    ? fallback
    : typeof value === "string"
      ? value
      : JSON.stringify(value);
const human = (value: unknown) =>
  text(value).replaceAll("_", " ").replaceAll("-", " ");
const isFinished = (status: string) =>
  [
    "completed",
    "complete",
    "succeeded",
    "success",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "blocked",
    "timeout",
    "timed_out",
  ].includes(status.toLowerCase());
const isPaused = (status: string) =>
  ["paused", "pausing", "interrupted", "needs_attention"].includes(
    status.toLowerCase(),
  );
const available = (provider?: Provider) =>
  !!provider &&
  !!provider.executable &&
  provider.authenticated !== false &&
  ["ready", "configured"].includes(provider.status);
const providerId = (provider: Provider): ProviderId =>
  provider.provider || provider.id;
const shortPath = (path: string) =>
  path.split("/").filter(Boolean).at(-1) || "Linked workspace";
const json = (value: unknown) => JSON.stringify(value, null, 2);
const requestTitle = (prompt: string) => {
  const first =
    prompt
      .trim()
      .split("\n")[0]
      ?.split(/(?<=[.!?])\s+(?=[A-Z])/)[0] || "Run details";
  return first.length > 150 ? `${first.slice(0, 147).trimEnd()}…` : first;
};

function Status({ value, dot = true }: { value: string; dot?: boolean }) {
  const lower = value.toLowerCase();
  const tone =
    /fail|error|cancel|block|missing|unavailable|unauthenticated|denied|changes requested|rejected/.test(
      lower,
    )
      ? "bad"
      : /success|complete|resolved|ready|passed|available|authenticated|accepted|approved/.test(
            lower,
          )
        ? "good"
        : /run|start|plan|dispatch|work|active|validat|integrat/.test(lower)
          ? "active"
          : /paus|waiting|queued|pending|attention|interrupted/.test(lower)
            ? "pending"
            : "neutral";
  return (
    <span className={`status ${tone}`}>
      {dot && <i />}
      {human(value) || "Unknown"}
    </span>
  );
}

function Empty({
  icon = "orbit",
  title,
  children,
}: {
  icon?: IconName;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={27} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

function selectedModel(participant: Participant, provider?: Provider) {
  return provider?.models?.find(
    (model) => model.id === (participant.model || provider.default_model),
  );
}

function modelSelectionError(participant: Participant, provider?: Provider) {
  if (!provider) return "The connection's model catalog is unavailable.";
  if (!participant.model && provider.default_model_error)
    return provider.default_model_error;
  if (selectedModel(participant, provider)) return "";
  if (participant.model)
    return `Saved model ${participant.model} is unavailable in this catalog. Refresh models or select an available model.`;
  return provider.default_model
    ? `Configured default ${provider.default_model} is unavailable in this catalog. Refresh models or select an available model.`
    : "The configured default could not be discovered. Refresh models or select an explicit model.";
}

function ParticipantEditor({
  participant,
  providers,
  connections,
  onChange,
  onRemove,
  coordinator = false,
  checking = false,
}: {
  participant: Participant;
  providers: Provider[];
  connections: Connection[];
  onChange: (p: Participant) => void;
  onRemove?: () => void;
  coordinator?: boolean;
  checking?: boolean;
}) {
  const provider = connectionProvider(participant, providers, connections);
  const name =
    participant.transport === "api"
      ? connections.find(
          (c) =>
            c.id ===
            (participant.connection_id || `${participant.provider}-api`),
        )?.name || `${LABELS[participant.provider] || participant.provider} API`
      : LABELS[participant.provider] || participant.provider;
  const models = provider?.models || [];
  const model = selectedModel(participant, provider);
  const modelError = modelSelectionError(participant, provider);
  const efforts = model?.efforts || [];
  const selectedConnection =
    participant.transport === "api"
      ? `api:${participant.connection_id || `${participant.provider}-api`}`
      : `cli:${participant.provider}`;
  const availableConnections = [
    ...PROVIDERS.map((id) => `cli:${id}`),
    ...connections
      .filter((c) => c.transport === "api")
      .map((c) => `api:${c.id}`),
  ];
  function changeConnection(value: string) {
    if (value.startsWith("cli:")) {
      const id = value.slice(4);
      const next = providers.find((p) => providerId(p) === id);
      const m = next?.models?.find((m) => m.id === next.default_model);
      onChange({
        ...participant,
        provider: id,
        transport: "cli",
        connection_id: null,
        model: null,
        effort: m?.efforts?.includes("high")
          ? "high"
          : m?.default_effort || null,
      });
    } else {
      const connection = connections.find((c) => c.id === value.slice(4));
      if (!connection) return;
      const m = connection.models?.find(
        (m) => m.id === connection.default_model,
      );
      onChange({
        ...participant,
        provider: connection.provider,
        transport: "api",
        connection_id: connection.id,
        model: null,
        effort: m?.efforts?.includes("high")
          ? "high"
          : m?.default_effort || null,
      });
    }
  }
  function changeModel(id: string) {
    const next = models.find((m) => m.id === (id || provider?.default_model));
    onChange({
      ...participant,
      model: id || null,
      effort: next?.efforts?.includes(participant.effort || "")
        ? participant.effort
        : next?.default_effort || null,
    });
  }
  return (
    <div
      className={`participant-card ${coordinator ? "coordinator-card" : ""}`}
    >
      <div className="participant-top">
        <ProviderMark
          provider={
            participant.provider === "antigravity" &&
            participant.transport === "api"
              ? "gemini"
              : participant.provider
          }
          size={37}
        />
        <div className="participant-name">
          <span>{coordinator ? "LEAD THE TEAM" : "TEAM MEMBER"}</span>
          <strong>{name}</strong>
        </div>
        {coordinator ? (
          <span className="leader-label">Coordinator</span>
        ) : onRemove ? (
          <button
            type="button"
            className="icon-button remove-participant"
            title={`Remove ${name}`}
            aria-label={`Remove ${name}`}
            onClick={onRemove}
          >
            <Icon name="close" size={16} />
          </button>
        ) : null}
      </div>
      <div className="participant-fields">
        <label>
          Connection
          <select
            aria-label={
              coordinator
                ? "Coordinator connection"
                : `${name} participant connection`
            }
            value={selectedConnection}
            onChange={(e) => changeConnection(e.target.value)}
          >
            {!availableConnections.includes(selectedConnection) && (
              <option value={selectedConnection}>
                Saved connection · unavailable
              </option>
            )}
            <optgroup label="Local CLI">
              {PROVIDERS.map((id) => (
                <option key={id} value={`cli:${id}`}>
                  {LABELS[id]} · CLI
                </option>
              ))}
            </optgroup>
            {connections.some((c) => c.transport === "api") && (
              <optgroup label="API connections">
                {connections
                  .filter((c) => c.transport === "api")
                  .map((c) => (
                    <option key={c.id} value={`api:${c.id}`}>
                      {c.name} · API
                    </option>
                  ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="model-field">
          Model
          <select
            aria-label={coordinator ? "Coordinator model" : `${name} model`}
            aria-invalid={(!checking && !!modelError) || undefined}
            value={participant.model || ""}
            onChange={(e) => changeModel(e.target.value)}
          >
            <option value="">
              {provider?.default_model
                ? `${participant.transport === "api" ? "Connection" : "CLI"} default · ${models.find((m) => m.id === provider.default_model)?.label || provider.default_model}${!models.some((m) => m.id === provider.default_model) || provider.default_model_error ? " · unavailable" : ""}`
                : `${participant.transport === "api" ? "Connection" : "CLI"} default${checking ? " · checking" : " · unavailable"}`}
            </option>
            {participant.model &&
              !models.some((m) => m.id === participant.model) && (
                <option value={participant.model}>
                  {participant.model} · saved selection · unavailable
                </option>
              )}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label || m.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Effort
          <select
            aria-label={coordinator ? "Coordinator effort" : `${name} effort`}
            value={participant.effort || ""}
            onChange={(e) =>
              onChange({ ...participant, effort: e.target.value || null })
            }
            disabled={
              (checking && !provider) ||
              (!efforts.length && !participant.effort)
            }
          >
            <option value="">
              {efforts.length
                ? "Provider default"
                : checking && !provider
                  ? "Checking capabilities…"
                  : "No verified effort control"}
            </option>
            {participant.effort && !efforts.includes(participant.effort) && (
              <option value={participant.effort}>
                {human(participant.effort)} · saved selection
              </option>
            )}
            {efforts.map((e) => (
              <option key={e} value={e}>
                {human(e)}
              </option>
            ))}
          </select>
        </label>
        {!coordinator && (
          <label>
            Role
            <select
              aria-label={`${name} role`}
              value={participant.role}
              onChange={(e) =>
                onChange({
                  ...participant,
                  role: e.target.value as Participant["role"],
                })
              }
            >
              <option value="generalist">Generalist</option>
              <option value="implementer">Implementer</option>
              <option value="reviewer">Reviewer</option>
            </select>
          </label>
        )}
      </div>
      <div className="model-catalog-meta">
        <span>Models: {provider?.catalog_source || "Source not reported"}</span>
        <span>
          Default:{" "}
          {provider?.default_model_source ||
            (provider ? "Native CLI / catalog" : "Not discovered")}
        </span>
        {participant.model && provider?.default_model_error && (
          <span>{provider.default_model_error}</span>
        )}
      </div>
      {!checking && modelError && <p className="inline-error">{modelError}</p>}
      <div className="participant-meta">
        <Status
          value={
            provider?.status ||
            (checking ? "checking" : "connection unavailable")
          }
        />
        <span title={provider?.catalog_source || "Catalog source not reported"}>
          {participant.transport === "api"
            ? provider?.catalog_source || "API connection"
            : provider?.version ||
              (checking ? "Discovering local agent…" : "Version not reported")}
        </span>
      </div>
      {provider?.authenticated === false && (
        <p className="inline-error">
          {participant.transport === "api"
            ? "Configure credentials in Connections."
            : `Sign in to ${name} through its CLI, then refresh connections.`}
        </p>
      )}
      {participant.effort &&
        ((efforts.length > 0 && !efforts.includes(participant.effort)) ||
          (participant.transport === "api" && !efforts.length)) && (
          <p className="inline-error">
            {efforts.length
              ? "Select an effort supported by this model."
              : "This catalog has no verified effort control. Select a model with supported efforts or use the provider default."}
          </p>
        )}
    </div>
  );
}

function CheckEditor({
  check,
  onChange,
  onRemove,
  index,
  onValidity,
}: {
  check: CheckSpec;
  onChange: (check: CheckSpec) => void;
  onRemove: () => void;
  index: number;
  onValidity?: (valid: boolean) => void;
}) {
  const [argv, setArgv] = useState(json(check.argv));
  const [error, setError] = useState("");
  useEffect(() => {
    setArgv(JSON.stringify(check.argv));
  }, [check.argv]);
  return (
    <div className="check-editor">
      <label>
        Name
        <input
          aria-label={`Check ${index + 1} name`}
          value={check.name}
          onChange={(e) => onChange({ ...check, name: e.target.value })}
          placeholder="Test suite"
        />
      </label>
      <label className="check-command">
        Command arguments <small>JSON array</small>
        <input
          aria-label={`Check ${index + 1} command arguments`}
          className="mono"
          value={argv}
          onChange={(e) => {
            setArgv(e.target.value);
            try {
              const parsed: unknown = JSON.parse(e.target.value);
              if (
                !Array.isArray(parsed) ||
                !parsed.length ||
                parsed.some((v) => typeof v !== "string")
              )
                throw new Error("Use a nonempty JSON array of strings.");
              setError("");
              onValidity?.(true);
              onChange({ ...check, argv: parsed as string[] });
            } catch {
              setError("Use a nonempty JSON array of strings.");
              onValidity?.(false);
            }
          }}
          placeholder={'["npm", "test"]'}
          aria-invalid={!!error}
        />
        {error && <span className="inline-error">{error}</span>}
      </label>
      <label className="check-root">
        Package root
        <input
          aria-label={`Check ${index + 1} package root`}
          value={check.cwd || "."}
          onChange={(e) => onChange({ ...check, cwd: e.target.value })}
        />
      </label>
      <label className="check-timeout">
        Timeout (s)
        <input
          aria-label={`Check ${index + 1} timeout`}
          type="number"
          min="1"
          max="1800"
          value={check.timeout}
          onChange={(e) =>
            onChange({ ...check, timeout: Number(e.target.value) })
          }
        />
      </label>
      <button
        type="button"
        className="icon-button"
        onClick={onRemove}
        title={`Remove check ${index + 1}`}
        aria-label={`Remove check ${index + 1}`}
      >
        <Icon name="trash" size={16} />
      </button>
    </div>
  );
}

function TaskDetail({
  task,
  tasks = [],
  events = [],
  onClose,
  onSelect,
}: {
  task: Data;
  tasks?: Data[];
  events?: RunEvent[];
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const manifest = contextManifest(
    [...events].reverse().find((event) => event.kind === "context" && event.task_id === text(task.id)),
  );
  // A task resolved by one of its own variants was explored, not repaired.
  const explored = explorations(tasks).get(text(task.id));
  const repaired = text(task.resolved_by) && !explored?.selected;
  const result =
    task.result && typeof task.result === "object" ? (task.result as Data) : {};
  const providerResult =
    result.provider_result && typeof result.provider_result === "object"
      ? (result.provider_result as Data)
      : {};
  const output =
    result.answer ||
    result.response ||
    result.text ||
    providerResult.answer ||
    providerResult.response ||
    providerResult.text ||
    task.output ||
    task.summary;
  const resolution =
    task.resolution_review && typeof task.resolution_review === "object"
      ? (task.resolution_review as Data)
      : null;
  return (
    <div className="task-detail">
      <div className="section-heading">
        <div>
          <span className="eyebrow">TASK {text(task.id)}</span>
          <h3>{text(task.title, "Task details")}</h3>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close task details"
        >
          <Icon name="close" />
        </button>
      </div>
      <p>{text(task.prompt)}</p>
      <div className="task-properties">
        <span>
          Provider{" "}
          <strong>
            {LABELS[text(task.provider) as ProviderId] || text(task.provider)}
          </strong>
        </span>
        <span>
          Status <Status value={text(task.status, "planned")} />
        </span>
        {Array.isArray(task.files) && (
          <span>
            Owned files{" "}
            <strong>
              {task.files.map((v) => text(v)).join(", ") || "No files declared"}
            </strong>
          </span>
        )}
      </div>
      {Array.isArray(task.dependencies) && task.dependencies.length > 0 && (
        <div className="work-task-dependencies">
          <h3>Required dependencies</h3>
          {task.dependencies.map((id) => {
            const dependency = tasks.find((item) => text(item.id) === text(id));
            return (
              <button
                className="work-assignment"
                key={text(id)}
                onClick={() => onSelect(text(id))}
              >
                <span>{text(dependency?.title, text(id))}</span>
                <Status value={text(dependency?.status, "not reported")} />
              </button>
            );
          })}
        </div>
      )}
      {task.variant_of ? <VariantDetail task={task} tasks={tasks} onSelect={onSelect} /> : null}
      {explored && <ExplorationDetail task={task} tasks={tasks} onSelect={onSelect} />}
      {manifest && <ContextDetails manifest={manifest} label="Latest context packet" />}
      {Array.isArray(task.acceptance) && task.acceptance.length > 0 && (
        <div className="task-acceptance">
          <span className="eyebrow">ACCEPTANCE CRITERIA</span>
          <ul className="acceptance">
            {task.acceptance.map((item, i) => (
              <li key={i}>
                <span className="acceptance-bullet" aria-hidden="true">
                  •
                </span>
                {text(item)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {repaired && (
        <div className="task-resolution">
          <span className="eyebrow">REPAIR HISTORY</span>
          <p>
            The original attempt failed. The runtime recorded a replacement and
            reviewed it against this task’s requirements.
          </p>
          <button
            className="secondary-button"
            onClick={() => onSelect(text(task.resolved_by))}
          >
            Inspect replacement <code>{text(task.resolved_by)}</code>
            <Icon name="arrow" size={14} />
          </button>
          {resolution && (
            <>
              <div className="task-resolution-review">
                <Status
                  value={
                    resolution.ok === true
                      ? "approved"
                      : resolution.ok === false
                        ? "rejected"
                        : "unknown"
                  }
                />
                <span>
                  {LABELS[text(resolution.provider)] ||
                    text(resolution.provider)}
                </span>
              </div>
              {text(resolution.summary) && <p>{text(resolution.summary)}</p>}
              {Array.isArray(resolution.findings) &&
                resolution.findings.length > 0 && (
                  <ul>
                    {resolution.findings.map((finding, i) => (
                      <li key={i}>{text(finding)}</li>
                    ))}
                  </ul>
                )}
            </>
          )}
          <details>
            <summary>Original failed outcome</summary>
            <pre className="raw-data">{json(result)}</pre>
          </details>
        </div>
      )}
      {text(output) && <pre className="task-output">{text(output)}</pre>}
      <details>
        <summary>Task data</summary>
        <pre className="raw-data">{json(task)}</pre>
      </details>
    </div>
  );
}

function ReviewContent({ run, tab }: { run: RunResult; tab: ReviewTab }) {
  if (tab === "changes")
    return (
      <>
        <div className="review-summary">
          <span>
            <strong>{run.changed_files.length}</strong> changed files
          </span>
          <span>
            {run.spec.integrate
              ? "Integration requested in run settings"
              : "Changes kept separate"}
          </span>
        </div>
        {run.changed_files.length > 0 && (
          <div className="changed-files">
            {run.changed_files.map((file) => (
              <span key={file}>
                <Icon name="folder" size={13} />
                {file}
              </span>
            ))}
          </div>
        )}
        {run.diff ? (
          <pre className="diff" aria-label="Run diff">
            {run.diff.split("\n").map((line, i) => (
              <span
                key={i}
                className={
                  line.startsWith("+") && !line.startsWith("+++")
                    ? "addition"
                    : line.startsWith("-") && !line.startsWith("---")
                      ? "deletion"
                      : line.startsWith("@@")
                        ? "hunk"
                        : line.startsWith("diff ") ||
                            line.startsWith("+++") ||
                            line.startsWith("---")
                          ? "file-line"
                          : ""
                }
              >
                <i>{i + 1}</i>
                {line || " "}
                {"\n"}
              </span>
            ))}
          </pre>
        ) : (
          <Empty icon="review" title="No diff reported">
            A diff will appear when the runtime records changes. Review and
            compare runs may finish without file changes.
          </Empty>
        )}
      </>
    );
  if (tab === "checks")
    return run.checks.length ? (
      <div className="check-results">
        {run.checks.map((check, i) => (
          <article key={text(check.name, String(i))} className="result-check">
            <div>
              <Icon name="command" size={20} />
              <h3>{text(check.name, `Check ${i + 1}`)}</h3>
              <Status
                value={text(
                  check.status,
                  check.ok === true
                    ? "passed"
                    : check.ok === false
                      ? "failed"
                      : check.returncode === 0 || check.exit_code === 0
                        ? "passed"
                        : check.returncode !== undefined ||
                            check.exit_code !== undefined
                          ? "failed"
                          : "reported",
                )}
              />
            </div>
            <code>
              {Array.isArray(check.argv)
                ? check.argv.map((v) => text(v)).join(" ")
                : text(check.command)}
            </code>
            <div className="check-facts">
              {check.returncode !== undefined && (
                <span>Exit {text(check.returncode)}</span>
              )}
              {check.exit_code !== undefined && (
                <span>Exit {text(check.exit_code)}</span>
              )}
              {(check.duration_seconds ?? check.elapsed_seconds) !==
                undefined && (
                <span>
                  {text(check.duration_seconds ?? check.elapsed_seconds)}{" "}
                  seconds
                </span>
              )}
            </div>
            {check.stdout || check.stderr || check.output ? (
              <pre>
                {text(check.stdout || check.output)}
                {check.stderr ? `\n${text(check.stderr)}` : ""}
              </pre>
            ) : (
              <p>No command output was reported.</p>
            )}
          </article>
        ))}
      </div>
    ) : (
      <Empty icon="check" title="No checks reported">
        Add explicit commands in Team settings to make validation part of the
        run.
      </Empty>
    );
  if (tab === "settings")
    return (
      <div className="settings-results">
        <div className="section-heading">
          <div>
            <h3>Effective run settings</h3>
            <p>The configuration recorded by the runtime for this run.</p>
          </div>
        </div>
        <pre className="raw-data">{json(run.spec)}</pre>
        <div className="section-heading">
          <div>
            <h3>Provider sessions</h3>
            <p>Reported model, effort, usage, and provider diagnostics.</p>
          </div>
        </div>
        {run.sessions.length ? (
          run.sessions.map((session, i) => (
            <details key={i} className="session-detail">
              <summary>
                <span>
                  {LABELS[text(session.provider) as ProviderId] ||
                    text(session.provider, `Session ${i + 1}`)}
                </span>
                <Status value={text(session.status, "reported")} />
              </summary>
              <pre className="raw-data">{json(session)}</pre>
            </details>
          ))
        ) : (
          <p className="muted">No provider sessions have been reported.</p>
        )}
        <details className="session-detail">
          <summary>Usage data</summary>
          <pre className="raw-data">{json(run.usage)}</pre>
        </details>
        <details className="session-detail">
          <summary>Artifacts</summary>
          <pre className="raw-data">{json(run.artifacts)}</pre>
        </details>
      </div>
    );
  return (
    <>
      {run.reviews.length ? (
        <div className="review-findings">
          {run.reviews.map((review, i) => {
            const findings = Array.isArray(review.findings)
              ? review.findings
              : [];
            return (
              <article key={i} className="review-report">
                <div className="section-heading">
                  <div className="review-author">
                    <ProviderMark
                      provider={text(review.provider, "custom")}
                      size={32}
                    />
                    <div>
                      <span className="eyebrow">INDEPENDENT REVIEW</span>
                      <h3>
                        {LABELS[text(review.provider) as ProviderId] ||
                          text(review.provider, `Review ${i + 1}`)}
                      </h3>
                      {text(review.task_id) && (
                        <code className="review-task-context">
                          {text(review.task_id)}
                        </code>
                      )}
                    </div>
                  </div>
                  <Status
                    value={
                      review.ok === true
                        ? "approved"
                        : review.ok === false
                          ? "changes requested"
                          : text(review.status || review.verdict, "reported")
                    }
                  />
                </div>
                {text(
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
                {Boolean(review.error) && (
                  <p className="inline-error">{text(review.error)}</p>
                )}
                {findings.map((finding, n) => {
                  const f: Data =
                    finding && typeof finding === "object"
                      ? (finding as Data)
                      : { body: finding };
                  return (
                    <div className="finding" key={n}>
                      <div>
                        <span className="severity">
                          {text(f.priority || f.severity, "Finding")}
                        </span>
                        <h4>{text(f.title, `Finding ${n + 1}`)}</h4>
                      </div>
                      {Boolean(f.file || f.path) && (
                        <code>
                          {text(f.file || f.path)}
                          {f.line ? `:${text(f.line)}` : ""}
                        </code>
                      )}
                      <p>{text(f.body || f.description || f.message)}</p>
                    </div>
                  );
                })}
                <details>
                  <summary>Review data</summary>
                  <pre className="raw-data">{json(review)}</pre>
                </details>
              </article>
            );
          })}
        </div>
      ) : (
        <Empty icon="review" title="No reviews reported yet">
          Findings will appear when a participant returns a review. A run
          without findings is not an approval.
        </Empty>
      )}
      {run.errors.length > 0 && (
        <div className="run-errors">
          <h3>Runtime diagnostics</h3>
          {run.errors.map((error, i) => (
            <div key={i} className="diagnostic">
              <Icon name="warning" />
              <div>
                <strong>
                  {human(error.kind || error.type || error.code || "Error")}
                </strong>
                <p>{text(error.message || error.error || error)}</p>
                <details>
                  <summary>Details</summary>
                  <pre>{json(error)}</pre>
                </details>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function App({
  execution,
  executionControls,
  accountControl,
}: {
  execution?: {
    name: string;
    workspace?: string;
    platform?: string;
    online?: boolean;
    paired?: boolean;
  };
  executionControls?: ReactNode;
  accountControl?: ReactNode;
} = {}) {
  const hostedWorkspace = import.meta.env.MODE === "cloud";
  const [tab, setTab] = useState<Tab>("workflows");
  const [reviewTab, setReviewTab] = useState<ReviewTab>("findings");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionsOpen, setConnectionsOpen] = useState(false);
  const [workspaceOverlay, setWorkspaceOverlay] = useState(false);
  const closeConnections = useCallback(() => setConnectionsOpen(false), []);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [run, setRun] = useState<RunResult | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [spec, setSpec] = useState<RunSpec>(() => ({
    ...structuredClone(INITIAL_SPEC),
    workspace:
      execution?.workspace ||
      new URLSearchParams(location.search).get("workspace") ||
      "",
  }));
  const [loading, setLoading] = useState(true);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogNote, setCatalogNote] = useState("");
  const [connected, setConnected] = useState(false);
  const [streamStatus, setStreamStatus] = useState("idle");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [profileName, setProfileName] = useState("");
  const [steering, setSteering] = useState("");
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("parallax-theme") || "dark",
  );
  const [motion, setMotion] = useState(
    () => localStorage.getItem("parallax-motion") || "system",
  );
  const cursor = useRef(0);
  const activeId = useRef<string | null>(null);
  const debounce = useRef<number | undefined>(undefined);
  const mainRef = useRef<HTMLElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const mounted = useRef(true);
  const lifecycle = useRef(0);
  const providerRequest = useRef<{
    promise: Promise<void>;
    controller: AbortController;
    force: boolean;
  } | null>(null);

  useEffect(() => {
    lifecycle.current += 1;
    mounted.current = true;
    return () => {
      mounted.current = false;
      lifecycle.current += 1;
      providerRequest.current?.controller.abort();
      providerRequest.current = null;
    };
  }, []);

  const refreshProviders = useCallback(function refreshProviders(
    force = false,
  ): Promise<void> {
    const current = providerRequest.current;
    if (current) {
      if (!force || current.force) return current.promise;
      return current.promise
        .catch(() => undefined)
        .then(() => {
          if (mounted.current) return refreshProviders(true);
        });
    }
    if (!mounted.current) return Promise.resolve();
    const controller = new AbortController();
    setCatalogLoading(true);
    setCatalogError("");
    setCatalogNote("");
    const promise = api<Provider[]>(
      force ? "/providers?refresh=true" : "/providers",
      {
        signal: controller.signal,
      },
    )
      .then((providers) => {
        if (!mounted.current || controller.signal.aborted) return;
        const list = providers.map((provider) => ({
          ...provider,
          id: provider.provider || provider.id,
        }));
        setProviders(list);
        if (force)
          setCatalogNote(
            `${list.reduce((count, provider) => count + (provider.models?.length || 0), 0)} models reported across ${list.length} local CLIs.`,
          );
      })
      .catch((failure) => {
        if (mounted.current && !controller.signal.aborted)
          setCatalogError(`Model refresh failed: ${messageOf(failure)}`);
        throw failure;
      })
      .finally(() => {
        if (providerRequest.current?.controller === controller) {
          providerRequest.current = null;
          if (mounted.current) setCatalogLoading(false);
        }
      });
    providerRequest.current = { promise, controller, force };
    return promise;
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("parallax-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.motion = motion;
    localStorage.setItem("parallax-motion", motion);
  }, [motion]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        !connectionsOpen &&
        !workspaceOverlay &&
        event.altKey &&
        ["1", "2", "3", "4"].includes(event.key)
      ) {
        event.preventDefault();
        setTab((["team", "run", "review", "workflows"] as Tab[])[Number(event.key) - 1]);
        mainRef.current?.focus();
      }
      if (event.key === "Escape") {
        setSelectedTask(null);
        setNotice("");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [connectionsOpen, workspaceOverlay]);

  const toast = useCallback((message: string) => {
    setNotice(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setNotice(""), 5500);
  }, []);
  const updateRun = useCallback((next: RunResult) => {
    setRun(next);
    setRuns((previous) => [
      next,
      ...previous.filter((item) => item.run_id !== next.run_id),
    ]);
  }, []);

  const [historyLoading, setHistoryLoading] = useState(true);
  const load = useCallback(
    async (forceProviders = false) => {
      const generation = lifecycle.current;
      const current = () => mounted.current && lifecycle.current === generation;
      setLoading(true);
      setHistoryLoading(true);
      setError("");
      const labels = [
        "Providers",
        "Profiles",
        "Runs",
        "Workspace",
        "Connections",
      ];
      const results = await Promise.allSettled([
        refreshProviders(forceProviders),
        api<Profile[]>("/profiles").then((profiles) => {
          if (current()) setProfiles(profiles);
        }),
        api<RunResult[]>("/runs")
          .then(async (history) => {
            if (!current()) return;
            setConnected(true);
            setRuns(history);
            if (history.length && !activeId.current) {
              const linked = new URLSearchParams(location.search).get(
                "workspace",
              );
              const pool = linked
                ? history.filter((item) => item.spec.workspace === linked)
                : history;
              const preferred =
                pool.find(
                  (item) =>
                    !isFinished(item.status) &&
                    !["needs_attention", "interrupted", "paused"].includes(
                      item.status,
                    ),
                ) ||
                pool.find((item) =>
                  ["needs_attention", "interrupted", "paused"].includes(
                    item.status,
                  ),
                ) ||
                pool[0];
              if (preferred) {
                const result = await api<RunResult>(
                  `/runs/${encodeURIComponent(preferred.run_id)}`,
                );
                if (current()) updateRun(result);
              }
            }
          })
          .finally(() => {
            if (current()) setHistoryLoading(false);
          }),
        api<{ workspace: string }>("/context").then(({ workspace }) => {
          if (current())
            setSpec((previous) => ({
              ...previous,
              workspace: previous.workspace || workspace,
            }));
        }),
        api<Connection[]>("/connections").then((connections) => {
          if (current()) setConnections(connections);
        }),
      ]);
      if (!current()) return;
      const failures = results.flatMap((result, index) =>
        result.status === "rejected"
          ? [`${labels[index]}: ${messageOf(result.reason)}`]
          : [],
      );
      if (results[2].status === "rejected") setConnected(false);
      if (failures.length) setError([...new Set(failures)].join(" "));
      setLoading(false);
    },
    [updateRun, refreshProviders],
  );

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (tab === "team") void refreshProviders().catch(() => undefined);
  }, [tab, refreshProviders]);
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible")
        void refreshProviders().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshProviders]);
  useEffect(() => {
    if (!run?.run_id) return;
    activeId.current = run.run_id;
    cursor.current = 0;
    setEvents([]);
    setSelectedTask(null);
    setStreamStatus("connecting");
    const id = run.run_id;
    const source = new EventSource(
      apiUrl(`/runs/${encodeURIComponent(id)}/events?cursor=0`),
      { withCredentials: true },
    );
    let disposed = false;
    source.onopen = () => setStreamStatus("live");
    source.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as RunEvent;
        if (!next.kind || next.run_id !== id || next.sequence <= cursor.current)
          return;
        cursor.current = next.sequence;
        setEvents((previous) =>
          [
            ...previous.filter((item) => item.sequence !== next.sequence),
            next,
          ].sort((a, b) => a.sequence - b.sequence),
        );
        // Locally, refresh shortly after events settle. Through a paired machine, refresh at most every
        // two seconds instead, so busy runs and several tabs stay within the workspace's relay rate.
        if (viaMachine() && debounce.current) return;
        window.clearTimeout(debounce.current);
        debounce.current = window.setTimeout(() => {
          debounce.current = undefined;
          void api<RunResult>(`/runs/${encodeURIComponent(id)}`)
            .then((result) => {
              if (!disposed && activeId.current === id) updateRun(result);
            })
            .catch((err) => {
              if (!disposed) setError(messageOf(err));
            });
        }, viaMachine() ? 2000 : 220);
      } catch {
        setStreamStatus("invalid event");
      }
    };
    source.onerror = () => setStreamStatus("reconnecting");
    const poll = window.setInterval(() => {
      void api<RunResult>(`/runs/${encodeURIComponent(id)}`)
        .then((result) => {
          if (!disposed && activeId.current === id) updateRun(result);
        })
        .catch(() => {
          if (!disposed) setStreamStatus("disconnected");
        });
    }, 6000);
    return () => {
      disposed = true;
      source.close();
      window.clearInterval(poll);
      window.clearTimeout(debounce.current);
      debounce.current = undefined;
    };
  }, [run?.run_id, updateRun]);

  async function chooseRun(id: string, target: Tab = "run") {
    setBusy("open");
    setError("");
    try {
      const next = await api<RunResult>(`/runs/${encodeURIComponent(id)}`);
      updateRun(next);
      setTab(target);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  function participantValidationError() {
    if (loading || catalogLoading) return "Wait for model discovery to finish.";
    for (const participant of [spec.coordinator, ...spec.team]) {
      const provider = connectionProvider(participant, providers, connections);
      const modelError = modelSelectionError(participant, provider);
      if (modelError)
        return `${provider?.label || LABELS[participant.provider] || participant.provider}: ${modelError}`;
      const model = selectedModel(participant, provider);
      if (participant.effort && !model?.efforts?.includes(participant.effort))
        return "Choose a supported effort for each selected model.";
    }
    return "";
  }

  async function start() {
    setError("");
    if (
      mainRef.current?.querySelector('.check-editor input[aria-invalid="true"]')
    ) {
      setError(
        "Fix the command arguments before starting. Use a nonempty JSON array of strings.",
      );
      return;
    }
    if (!spec.workspace.trim()) {
      setError("Choose the linked workspace before starting.");
      return;
    }
    if (!spec.prompt.trim()) {
      setError("Describe the task before starting.");
      return;
    }
    if (spec.prompt.length > 200000) {
      setError("Keep the task description under 200,000 characters.");
      return;
    }
    const limitRanges: Record<keyof RunSpec["limits"], [number, number]> = {
      workers: [1, 8],
      repairs: [0, 5],
      minutes: [1, 240],
      attempt_seconds: [10, 3600],
      coordinator_turns: [2, 60],
    };
    if (
      (Object.keys(limitRanges) as Array<keyof RunSpec["limits"]>).some(
        (key) =>
          !Number.isInteger(spec.limits[key]) ||
          spec.limits[key] < limitRanges[key][0] ||
          spec.limits[key] > limitRanges[key][1],
      )
    ) {
      setError("Each run limit must be a whole number within its shown range.");
      return;
    }
    if (!spec.team.length) {
      setError("Add at least one participant.");
      return;
    }
    const unusable = [spec.coordinator, ...spec.team].filter(
      (participant) =>
        !available(connectionProvider(participant, providers, connections)),
    );
    if (unusable.length) {
      setError(
        `Configure or sign in to ${[...new Set(unusable.map((p) => connectionProvider(p, providers, connections)?.label || LABELS[p.provider] || p.provider))].join(", ")}. You can also remove an unavailable participant.`,
      );
      return;
    }
    const selectionError = participantValidationError();
    if (selectionError) {
      setError(selectionError);
      return;
    }
    if (
      spec.checks.some(
        (check) =>
          !check.name.trim() ||
          !check.argv.length ||
          check.argv.some((arg) => typeof arg !== "string") ||
          !Number.isInteger(check.timeout) ||
          check.timeout < 1 ||
          check.timeout > 1800,
      )
    ) {
      setError(
        "Each check needs a name, command arguments, and a timeout from 1 to 1,800 seconds.",
      );
      return;
    }
    setBusy("start");
    try {
      const next = await api<RunResult>("/runs", {
        method: "POST",
        body: JSON.stringify(spec),
      });
      updateRun(next);
      setTab("run");
      toast("Team run started.");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  async function action(kind: "pause" | "cancel" | "resume") {
    if (!run) return;
    setBusy(kind);
    setError("");
    try {
      const next = await api<RunResult>(
        `/runs/${encodeURIComponent(run.run_id)}/${kind}`,
        { method: "POST" },
      );
      if (next?.run_id) updateRun(next);
      else
        updateRun(
          await api<RunResult>(`/runs/${encodeURIComponent(run.run_id)}`),
        );
      toast(
        kind === "pause"
          ? "Pause requested. Active attempts may finish first."
          : kind === "resume"
            ? "Resume requested."
            : "Cancellation requested.",
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  async function steer() {
    if (!run || !steering.trim()) return;
    setBusy("steer");
    setError("");
    try {
      await api(`/runs/${encodeURIComponent(run.run_id)}/steer`, {
        method: "POST",
        body: JSON.stringify({ message: steering }),
      });
      setSteering("");
      toast("Guidance sent to the coordinator.");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  async function saveProfile() {
    const selectionError = participantValidationError();
    if (selectionError) {
      setError(selectionError);
      return;
    }
    if (
      mainRef.current?.querySelector('.check-editor input[aria-invalid="true"]')
    ) {
      setError("Fix the command arguments before saving this profile.");
      return;
    }
    const name = (profileName || spec.profile).trim();
    if (!name) {
      setError("Give the profile a name.");
      return;
    }
    setBusy("profile");
    setError("");
    try {
      const updated = { ...spec, profile: name };
      await api(`/profiles/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify(updated),
      });
      setSpec(updated);
      setProfiles(await api<Profile[]>("/profiles"));
      setProfileName("");
      toast(`Saved “${name}”.`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  async function deleteProfile() {
    setBusy("profile");
    setError("");
    try {
      await api(`/profiles/${encodeURIComponent(spec.profile)}`, {
        method: "DELETE",
      });
      setProfiles(await api<Profile[]>("/profiles"));
      setSpec((previous) => ({ ...previous, profile: "Quality first" }));
      toast("Profile removed.");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast("Copied to clipboard.");
    } catch {
      setError("Clipboard access is unavailable in this browser.");
    }
  }

  const readyCount = providers.filter(available).length;
  const savedProfile = profiles.some((p) => p.name === spec.profile);
  const activeRun =
    run && !isFinished(run.status) && run.status !== "needs_attention";
  const runTitle = requestTitle(run?.spec.prompt || "");

  return (
    <div className={`app-shell studio-workspace tab-${tab}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {connectionsOpen && (
        <ConnectionsPanel
          execution={execution}
          connections={connections}
          onChanged={load}
          onClose={closeConnections}
        />
      )}
      <aside
        className="sidebar"
        inert={connectionsOpen || workspaceOverlay || undefined}
      >
        <a
          href="#workflows"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            setTab("workflows");
          }}
          aria-label="Parallax Studio home"
        >
          <span className="brand-mark">
            <Icon name="orbit" size={28} />
          </span>
          <span>
            Parallax<small>STUDIO</small>
          </span>
        </a>
        <div className="sidebar-group-label">WORKSPACE</div>
        <nav aria-label="Studio navigation">
          {(
            [
              { id: "workflows", name: "Workflows", icon: "orbit", key: "4" },
              { id: "run", name: "Workspace", icon: "run", key: "2" },
              { id: "team", name: "New run", icon: "plus", key: "1" },
              { id: "review", name: "Review", icon: "review", key: "3" },
            ] as { id: Tab; name: string; icon: IconName; key: string }[]
          ).map((item) => (
            <button
              key={item.id}
              className={`nav-item ${tab === item.id ? "selected" : ""}`}
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? "page" : undefined}
              title={item.name}
              aria-label={item.name}
              aria-keyshortcuts={`Alt+${item.key}`}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.name}</span>
              <kbd>{item.key}</kbd>
              {item.id === "run" && activeRun && <i className="nav-run-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-provider-list">
          <div className="sidebar-group-label">
            LOCAL PROVIDERS{" "}
            <span>
              {readyCount}/{providers.length || 4}
            </span>
          </div>
          {PROVIDERS.map((id) => {
            const provider = providers.find((p) => providerId(p) === id);
            return (
              <div key={id} className="sidebar-provider">
                <ProviderMark provider={id} size={24} />
                <span>{LABELS[id]}</span>
                <i
                  className={available(provider) ? "online-dot" : "offline-dot"}
                  title={provider?.status || "Not checked"}
                />
              </div>
            );
          })}
          <button
            className="text-button refresh-providers"
            onClick={() => void load(true)}
            disabled={loading || catalogLoading}
          >
            <Icon name="refresh" size={13} className={loading ? "spin" : ""} />
            {loading ? "Checking providers…" : "Refresh connections"}
          </button>
          <button
            className="text-button manage-connections"
            onClick={() => setConnectionsOpen(true)}
          >
            <Icon name="settings" size={13} /> Manage connections
          </button>
        </div>
        <div className="sidebar-bottom">
          <div className="workspace-chip">
            <Icon name="folder" size={19} />
            <div>
              <strong title={spec.workspace}>
                {shortPath(spec.workspace)}
              </strong>
              <span>Linked by the plugin</span>
            </div>
          </div>
          <div className="sidebar-options">
            <button
              className="icon-button"
              aria-label={
                theme === "dark"
                  ? "Switch to light mode"
                  : "Switch to dark mode"
              }
              title={
                theme === "dark"
                  ? "Switch to light mode"
                  : "Switch to dark mode"
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
            </button>
            <button
              className={`icon-button motion-button ${motion === "reduce" ? "enabled" : ""}`}
              aria-pressed={motion === "reduce"}
              title="Reduce motion"
              aria-label="Reduce motion"
              onClick={() =>
                setMotion(motion === "reduce" ? "system" : "reduce")
              }
            >
              <Icon name="pause" size={17} />
            </button>
            <span>v{__PARALLAX_VERSION__}</span>
          </div>
        </div>
      </aside>
      <div className="main-shell" inert={connectionsOpen || undefined}>
        <header className="topbar" inert={workspaceOverlay || undefined}>
          <div className="breadcrumb">
            <span>
              {shortPath(
                (tab === "run" || tab === "review") && run
                  ? run.spec.workspace
                  : spec.workspace,
              )}
            </span>
            <Icon name="chevron" size={13} />
            <strong>
              {tab === "run" ? "Runs" : tab === "team" ? "New run" : tab === "workflows" ? "Workflows" : "Review"}
            </strong>
          </div>
          <div className="topbar-right">
            {executionControls}
            <button
              className="work-button"
              onClick={() => setConnectionsOpen(true)}
            >
              Connections
            </button>
            <span className={`connection ${connected ? "connected" : ""}`}>
              <i />
              {historyLoading
                ? "Connecting"
                : connected
                  ? hostedWorkspace
                    ? "Hosted connection"
                    : "Local connection"
                  : "Connection unavailable"}
            </span>
            <span className="local-only">
              <Icon name="command" size={13} />{" "}
              {execution?.paired
                ? `On ${execution.name}`
                : hostedWorkspace
                  ? "On Railway"
                  : "On your machine"}
            </span>
            {accountControl}
          </div>
        </header>
        <main id="main" className="main-content" ref={mainRef} tabIndex={-1}>
          {error && (
            <div className="alert" role="alert">
              <Icon name="warning" size={19} />
              <p>{error}</p>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="Dismiss error"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {tab === "workflows" && (
            <Workflows
              workspace={spec.workspace}
              onWorkspace={workspace => setSpec(previous => ({...previous, workspace}))}
              online={execution?.online !== false}
              onInspect={id => void chooseRun(id, "review")}
              onConnections={() => setConnectionsOpen(true)}
              renderParticipant={(participant, onChange, coordinator) => (
                <ParticipantEditor participant={participant} providers={providers} connections={connections}
                  onChange={onChange} coordinator={coordinator} checking={catalogLoading} />
              )}
              renderCheck={(check, index, onChange, onRemove, onValidity) => (
                <CheckEditor check={check} index={index} onChange={onChange} onRemove={onRemove} onValidity={onValidity} />
              )}
            />
          )}
          {tab === "team" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">PROJECT WORKFLOW</span>
                  <h1>New run</h1>
                  <p>
                    Describe the outcome. Choose a saved team or adjust its
                    settings.
                  </p>
                </div>
                <span className="heading-tag">
                  <Icon name="orbit" size={16} /> Local orchestration
                </span>
              </div>
              <div className="team-intro">
                <section className="mission-panel">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">TASK</span>
                      <h2>What should the team deliver?</h2>
                    </div>
                    <Icon name="arrow" size={22} />
                  </div>
                  <label className="workspace-field">
                    <span>Workspace</span>
                    <div className="input-with-icon">
                      <Icon name="folder" size={15} />
                      <input
                        value={spec.workspace}
                        onChange={(e) =>
                          setSpec({ ...spec, workspace: e.target.value })
                        }
                        aria-label="Workspace path"
                        placeholder="Workspace linked by the plugin"
                      />
                    </div>
                  </label>
                  <label className="prompt-label">
                    <span className="sr-only">Task prompt</span>
                    <textarea
                      value={spec.prompt}
                      onChange={(e) =>
                        setSpec({ ...spec, prompt: e.target.value })
                      }
                      placeholder="Describe the outcome you want. Include context, constraints, and what a good result looks like…"
                      rows={5}
                    />
                  </label>
                  <div className="mode-selector" aria-label="Run mode">
                    {(["build", "review", "compare"] as const).map((mode) => (
                      <button
                        key={mode}
                        className={spec.mode === mode ? "selected" : ""}
                        onClick={() => setSpec({ ...spec, mode })}
                        aria-pressed={spec.mode === mode}
                      >
                        <Icon
                          name={
                            mode === "build"
                              ? "command"
                              : mode === "review"
                                ? "review"
                                : "team"
                          }
                          size={15}
                        />
                        {human(mode)}
                      </button>
                    ))}
                  </div>
                  <p className="mode-description">
                    {spec.mode === "build"
                      ? "Coordinate implementation and review in isolated workspaces."
                      : spec.mode === "review"
                        ? "Inspect the workspace and collect independent reviews."
                        : "Compare independent approaches before choosing a result."}
                  </p>
                </section>
              </div>
              <div className="connections-strip">
                <div>
                  <span className="connections-strip-icon">
                    <Icon name="connection" size={19} />
                  </span>
                  <div>
                    <strong>Your connection layer</strong>
                    <span>
                      {readyCount} local CLIs available ·{" "}
                      {connections.filter((c) => c.transport === "api").length}{" "}
                      API connections
                    </span>
                  </div>
                </div>
                <button
                  className="secondary-button small"
                  onClick={() => setConnectionsOpen(true)}
                >
                  Manage connections <Icon name="arrow" size={14} />
                </button>
              </div>
              <ProjectReadiness
                spec={spec}
                onChange={setSpec}
                providers={providers}
                connections={connections}
              />
              <ProjectMemory workspace={spec.workspace} />
              <div className="team-section-heading">
                <div>
                  <h2>
                    The team <span>{spec.team.length + 1}</span>
                  </h2>
                  <p>
                    The coordinator assigns work and reconciles the results.
                  </p>
                </div>
                <div className="profile-controls">
                  <button
                    className="secondary-button small"
                    onClick={() =>
                      void refreshProviders(true).catch(() => undefined)
                    }
                    disabled={catalogLoading}
                    aria-busy={catalogLoading}
                  >
                    <Icon
                      name="refresh"
                      size={14}
                      className={catalogLoading ? "spin" : ""}
                    />
                    {catalogLoading ? "Refreshing models…" : "Refresh models"}
                  </button>
                  <label className="sr-only" htmlFor="profile-select">
                    Saved profile
                  </label>
                  <select
                    id="profile-select"
                    value={savedProfile ? spec.profile : ""}
                    onChange={(e) => {
                      const profile = profiles.find(
                        (p) => p.name === e.target.value,
                      );
                      if (profile)
                        setSpec({
                          ...structuredClone(profile.spec),
                          workspace: spec.workspace || profile.spec.workspace,
                          prompt: spec.prompt,
                        });
                    }}
                  >
                    <option value="">{spec.profile} · custom</option>
                    {profiles.map((profile) => (
                      <option key={profile.name} value={profile.name}>
                        {profile.name}
                      </option>
                    ))}
                  </select>
                  <input
                    className="profile-name"
                    aria-label="Profile name"
                    placeholder="Profile name"
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                  />
                  <button
                    className="icon-button bordered"
                    onClick={() => void saveProfile()}
                    disabled={!!busy || loading || catalogLoading}
                    title="Save profile"
                    aria-label="Save profile"
                  >
                    <Icon name="save" size={16} />
                  </button>
                  {savedProfile && (
                    <button
                      className="icon-button bordered"
                      onClick={() => void deleteProfile()}
                      disabled={!!busy}
                      title="Delete saved profile"
                      aria-label="Delete saved profile"
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  )}
                </div>
              </div>
              <div
                className={`model-refresh-feedback ${catalogError ? "error" : ""}`}
                aria-live="polite"
              >
                {catalogLoading
                  ? "Discovering local CLI model catalogs…"
                  : catalogError || catalogNote}
              </div>
              <ParticipantEditor
                checking={loading || catalogLoading}
                connections={connections}
                participant={spec.coordinator}
                providers={providers}
                coordinator
                onChange={(coordinator) => setSpec({ ...spec, coordinator })}
              />
              <div className="team-grid">
                {spec.team.map((participant, i) => (
                  <ParticipantEditor
                    checking={loading || catalogLoading}
                    connections={connections}
                    key={i}
                    participant={participant}
                    providers={providers}
                    onChange={(next) =>
                      setSpec({
                        ...spec,
                        team: spec.team.map((p, index) =>
                          index === i ? next : p,
                        ),
                      })
                    }
                    onRemove={() =>
                      setSpec({
                        ...spec,
                        team: spec.team.filter((_, index) => index !== i),
                      })
                    }
                  />
                ))}
              </div>
              <div className="add-participant">
                <Icon name="plus" size={15} />
                <select
                  aria-label="Add team participant"
                  value=""
                  disabled={spec.team.length >= 8}
                  onChange={(e) =>
                    e.target.value &&
                    setSpec({
                      ...spec,
                      team: [
                        ...spec.team,
                        {
                          provider: e.target.value.startsWith("api:")
                            ? connections.find(
                                (c) => c.id === e.target.value.slice(4),
                              )!.provider
                            : e.target.value,
                          transport: e.target.value.startsWith("api:")
                            ? "api"
                            : "cli",
                          connection_id: e.target.value.startsWith("api:")
                            ? e.target.value.slice(4)
                            : null,
                          model: null,
                          effort: null,
                          role: "generalist",
                        },
                      ],
                    })
                  }
                >
                  <option value="">
                    {spec.team.length >= 8
                      ? "Team limit reached"
                      : "Add a participant"}
                  </option>
                  {PROVIDERS.map((id) => (
                    <option key={id} value={id}>
                      {LABELS[id]} · CLI
                    </option>
                  ))}
                  {connections
                    .filter((c) => c.transport === "api")
                    .map((c) => (
                      <option key={c.id} value={`api:${c.id}`}>
                        {c.name} · API
                      </option>
                    ))}
                </select>
              </div>
              <section className="run-settings">
                <details>
                  <summary>
                    <span>
                      <Icon name="settings" size={18} />
                      Run limits & validation
                    </span>
                    <span className="settings-summary">
                      {spec.limits.workers} concurrent workers ·{" "}
                      {spec.limits.minutes} min · {spec.checks.length}{" "}
                      {spec.checks.length === 1 ? "check" : "checks"}
                      <Icon name="chevron" size={15} />
                    </span>
                  </summary>
                  <div className="settings-body">
                    <div className="limits-grid">
                      {(
                        [
                          {
                            key: "workers",
                            label: "Concurrent workers",
                            min: 1,
                            max: 8,
                          },
                          {
                            key: "repairs",
                            label: "Repair attempts",
                            min: 0,
                            max: 5,
                          },
                          {
                            key: "minutes",
                            label: "Run budget (minutes)",
                            min: 1,
                            max: 240,
                          },
                          {
                            key: "attempt_seconds",
                            label: "Attempt timeout (seconds)",
                            min: 10,
                            max: 3600,
                          },
                          {
                            key: "coordinator_turns",
                            label: "Coordinator turns",
                            min: 2,
                            max: 60,
                          },
                        ] as const
                      ).map((field) => (
                        <label key={field.key}>
                          {field.label}
                          <input
                            type="number"
                            min={field.min}
                            max={field.max}
                            value={spec.limits[field.key]}
                            onChange={(e) =>
                              setSpec({
                                ...spec,
                                limits: {
                                  ...spec.limits,
                                  [field.key]: Number(e.target.value),
                                },
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <div className="checks-heading">
                      <div>
                        <h3>Validation commands</h3>
                        <p>
                          Commands run as explicit argument arrays, without
                          shell expansion.
                        </p>
                      </div>
                      <button
                        className="secondary-button small"
                        onClick={() =>
                          setSpec({
                            ...spec,
                            checks: [
                              ...spec.checks,
                              { name: "", argv: [], timeout: 120 },
                            ],
                          })
                        }
                      >
                        <Icon name="plus" size={14} /> Add check
                      </button>
                    </div>
                    {spec.checks.map((check, i) => (
                      <CheckEditor
                        key={i}
                        index={i}
                        check={check}
                        onChange={(next) =>
                          setSpec({
                            ...spec,
                            checks: spec.checks.map((c, index) =>
                              index === i ? next : c,
                            ),
                          })
                        }
                        onRemove={() =>
                          setSpec({
                            ...spec,
                            checks: spec.checks.filter(
                              (_, index) => index !== i,
                            ),
                          })
                        }
                      />
                    ))}
                    {!spec.checks.length && (
                      <p className="empty-checks">
                        No explicit checks configured.
                      </p>
                    )}
                  </div>
                </details>
              </section>
              <div className="launch-bar">
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={spec.integrate}
                    onChange={(e) =>
                      setSpec({ ...spec, integrate: e.target.checked })
                    }
                  />
                  <span className="toggle" />
                  <span>
                    <strong>Integrate accepted changes</strong>
                    <small>
                      The runtime applies the selected result after validation.
                    </small>
                  </span>
                </label>
                <button
                  className="primary-button start-button"
                  onClick={() => void start()}
                  disabled={!connected || !!busy || loading || catalogLoading}
                >
                  <span>
                    {busy === "start" ? "Starting…" : "Start team run"}
                  </span>
                  <Icon name="arrow" size={18} />
                </button>
              </div>
            </>
          )}
          {tab === "run" && (
            <RunWorkspace
              run={run}
              runs={runs}
              events={events}
              loading={historyLoading}
              busy={busy}
              streamStatus={
                execution?.paired && execution.online === false
                  ? "worker offline · saved evidence"
                  : streamStatus
              }
              selected={selectedTask}
              onOverlayChange={setWorkspaceOverlay}
              onSelect={setSelectedTask}
              onChoose={(id) => void chooseRun(id)}
              onNew={() => setTab("team")}
              onReload={() => void load()}
              onReview={(section) => {
                if (section) setReviewTab(section);
                setTab("review");
                if (section)
                  requestAnimationFrame(() => {
                    const panel = document.getElementById(`review-${section}`);
                    panel?.scrollIntoView({ block: "nearest" });
                    panel?.focus();
                  });
              }}
              onAction={(kind) => void action(kind)}
              steering={steering}
              onSteering={setSteering}
              onSteer={() => void steer()}
              recovery={
                run &&
                ["needs_attention", "interrupted"].includes(run.status) ? (
                  <Recovery
                    run={run}
                    onUpdate={updateRun}
                    onConfigure={() => {
                      setSpec({
                        ...structuredClone(run.spec),
                        schema_version: "1.1",
                      });
                      setTab("team");
                    }}
                  />
                ) : null
              }
              renderTask={(task) => (
                <TaskDetail
                  task={task}
                  tasks={run?.tasks}
                  events={events}
                  onSelect={setSelectedTask}
                  onClose={() => setSelectedTask(null)}
                />
              )}
            />
          )}
          {tab === "review" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">EXAMINE THE RESULT</span>
                  <h1>
                    Inspect the verification record
                    <span className="title-dot">.</span>
                  </h1>
                  <p>
                    Independent reviews, project checks, and the recorded
                    integration outcome.
                  </p>
                </div>
                {runs.length > 0 && (
                  <select
                    className="run-select"
                    aria-label="Select run to review"
                    value={run?.run_id || ""}
                    onChange={(e) => void chooseRun(e.target.value, "review")}
                  >
                    <option value="" disabled>
                      Select a run
                    </option>
                    {runs.map((item) => (
                      <option value={item.run_id} key={item.run_id}>
                        {item.spec.prompt.slice(0, 70)} · {human(item.status)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {run ? (
                <>
                  <section className="review-run-heading">
                    <div>
                      <span className="eyebrow">{run.run_id.slice(0, 14)}</span>
                      <h2>{runTitle}</h2>
                      <p>{run.summary || "No summary reported."}</p>
                    </div>
                    <Status value={run.status} />
                  </section>
                  <div className="review-evidence-stack">
                    <details className="review-evidence-disclosure">
                      <summary>
                        <span>Verification record</span>
                        <small>
                          {run.artifacts.integration_applied
                            ? "Integration applied"
                            : "Recorded gates and artifacts"}
                        </small>
                      </summary>
                      <Verification run={run} />
                    </details>
                    <details className="review-evidence-disclosure">
                      <summary>
                        <span>Baseline and final checks</span>
                        <small>
                          {run.checks.length
                            ? `${run.checks.filter((check) => check.ok === true).length}/${run.checks.length} final checks passed`
                            : "No final checks recorded"}
                        </small>
                      </summary>
                      <Baseline run={run} />
                    </details>
                  </div>
                  <div
                    className="review-tabs"
                    role="tablist"
                    aria-label="Review sections"
                  >
                    {(
                      [
                        {
                          id: "findings",
                          label: "Reviews",
                          icon: "review",
                          count: run.reviews.length,
                        },
                        {
                          id: "changes",
                          label: "Changes",
                          icon: "folder",
                          count: run.changed_files.length,
                        },
                        {
                          id: "checks",
                          label: "Checks",
                          icon: "check",
                          count: run.checks.length,
                        },
                        {
                          id: "settings",
                          label: "Settings & usage",
                          icon: "settings",
                        },
                      ] as {
                        id: ReviewTab;
                        label: string;
                        icon: IconName;
                        count?: number;
                      }[]
                    ).map((item) => (
                      <button
                        role="tab"
                        aria-selected={reviewTab === item.id}
                        aria-controls={`review-${item.id}`}
                        id={`tab-${item.id}`}
                        key={item.id}
                        className={reviewTab === item.id ? "selected" : ""}
                        onClick={() => setReviewTab(item.id)}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                            const tabs: ReviewTab[] = [
                              "findings",
                              "changes",
                              "checks",
                              "settings",
                            ];
                            const next =
                              tabs[
                                (tabs.indexOf(reviewTab) +
                                  (e.key === "ArrowRight" ? 1 : 3)) %
                                  tabs.length
                              ];
                            setReviewTab(next);
                            requestAnimationFrame(() =>
                              document.getElementById(`tab-${next}`)?.focus(),
                            );
                          }
                        }}
                      >
                        <Icon name={item.icon} size={16} />
                        {item.label}
                        {item.count !== undefined && <span>{item.count}</span>}
                      </button>
                    ))}
                  </div>
                  <section
                    className="review-body"
                    role="tabpanel"
                    tabIndex={-1}
                    id={`review-${reviewTab}`}
                    aria-labelledby={`tab-${reviewTab}`}
                  >
                    <ReviewContent run={run} tab={reviewTab} />
                  </section>
                  <div className="review-footer">
                    <button
                      className="text-button"
                      onClick={() => void copy(json(run))}
                    >
                      <Icon name="copy" size={15} /> Copy run JSON
                    </button>
                    <button
                      className="text-button"
                      onClick={() => setTab("run")}
                    >
                      Back to workspace <Icon name="arrow" size={15} />
                    </button>
                  </div>
                  <AlphaFeedback run={run} />
                </>
              ) : (
                <section className="panel review-placeholder">
                  <Empty icon="review" title="A clear view of the result">
                    Select a recorded run to inspect its findings, file changes,
                    and checks.
                  </Empty>
                  {runs.length ? (
                    <button
                      className="primary-button"
                      onClick={() => void chooseRun(runs[0].run_id, "review")}
                    >
                      Open latest run <Icon name="arrow" size={17} />
                    </button>
                  ) : (
                    <button
                      className="primary-button"
                      onClick={() => setTab("team")}
                    >
                      Create a team run <Icon name="arrow" size={17} />
                    </button>
                  )}
                </section>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>
              <Icon name="orbit" size={15} /> Parallax Studio
            </span>
            <span>Local agents. Recorded evidence. Your workspace.</span>
            <span className="keyboard-hint">Alt + 1 / 2 / 3 / 4 to navigate</span>
          </footer>
        </main>
      </div>
      {notice && (
        <div className="toast" role="status">
          <span className="toast-check">
            <Icon name="check" size={15} />
          </span>
          {notice}
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
