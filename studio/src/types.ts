export type ProviderId = string;
export type Mode = "review" | "build" | "compare";
export type Role = "generalist" | "implementer" | "reviewer";
export type Participant = {
  provider: ProviderId;
  transport?: "cli" | "api";
  connection_id?: string | null;
  model: string | null;
  effort: string | null;
  role: Role;
};
export type Model = {
  id: string;
  label: string;
  efforts?: string[];
  default_effort?: string | null;
  source?: string;
};
export type Provider = {
  provider?: ProviderId;
  id: ProviderId;
  label: string;
  executable?: string | null;
  version?: string | null;
  authenticated?: boolean | null;
  status: string;
  error?: string | null;
  capabilities?: Record<string, unknown>;
  models?: Model[];
  default_model?: string | null;
  catalog_source?: string;
  default_model_source?: string | null;
  default_model_error?: string | null;
};
export type CheckSpec = {
  name: string;
  argv: string[];
  timeout: number;
  cwd?: string;
};
export type Connection = {
  id: string;
  provider: string;
  name: string;
  transport: "cli" | "api";
  protocol?: "responses" | "anthropic" | "openai";
  endpoint?: string;
  api_configured?: boolean;
  key_hint?: string | null;
  status: string;
  models?: Model[];
  default_model?: string;
  credential_storage?: string;
  source?: string;
  api_key_env?: string | null;
  cli_status?: Provider;
};
export function connectionProvider(
  participant: Participant,
  providers: Provider[],
  connections: Connection[],
): Provider | undefined {
  if (participant.transport !== "api")
    return providers.find((p) => (p.provider || p.id) === participant.provider);
  const c = connections.find(
    (c) =>
      c.id === (participant.connection_id || `${participant.provider}-api`),
  );
  return c
    ? {
        id: c.provider,
        provider: c.provider,
        label: c.name,
        executable: c.endpoint,
        authenticated: c.api_configured,
        status: c.status,
        models: (c.models || []).map((m) => ({ ...m, label: m.label || m.id })),
        default_model: c.default_model,
        default_model_source: "saved connection",
        catalog_source: c.source,
        version: "API connection",
      }
    : undefined;
}
export type RunSpec = {
  schema_version: "1.0" | "1.1";
  workspace: string;
  prompt: string;
  mode: Mode;
  coordinator: Participant;
  team: Participant[];
  limits: {
    workers: number;
    repairs: number;
    minutes: number;
    attempt_seconds: number;
    coordinator_turns: number;
  };
  checks: CheckSpec[];
  profile: string;
  integrate: boolean;
  package_roots?: string[];
};
export type Profile = { name: string; spec: RunSpec };
export type Data = Record<string, unknown>;
export type RunResult = {
  schema_version: "1.0" | "1.1";
  run_id: string;
  status: string;
  spec: RunSpec;
  summary: string;
  tasks: Data[];
  sessions: Data[];
  changed_files: string[];
  diff: string;
  reviews: Data[];
  checks: Data[];
  usage: Data;
  errors: Data[];
  artifacts: Data;
};
export type RunEvent = {
  schema_version: "1.0" | "1.1";
  sequence: number;
  run_id: string;
  timestamp: string;
  kind: string;
  task_id?: string | null;
  data: Data;
};

export const PROVIDERS: ProviderId[] = [
  "codex",
  "claude",
  "grok",
  "antigravity",
];
export const LABELS: Record<ProviderId, string> = {
  codex: "Codex",
  claude: "Claude",
  grok: "Grok",
  antigravity: "Antigravity",
};
export const INITIAL_SPEC: RunSpec = {
  schema_version: "1.1",
  workspace: "",
  prompt: "",
  mode: "build",
  coordinator: {
    provider: "codex",
    model: null,
    effort: "high",
    role: "generalist",
  },
  team: [
    { provider: "claude", model: null, effort: "high", role: "implementer" },
    { provider: "grok", model: null, effort: "high", role: "reviewer" },
    {
      provider: "antigravity",
      model: null,
      effort: "high",
      role: "generalist",
    },
  ],
  limits: {
    workers: 3,
    repairs: 2,
    minutes: 45,
    attempt_seconds: 600,
    coordinator_turns: 20,
  },
  checks: [],
  profile: "Quality first",
  integrate: true,
};
