import { useEffect, useRef, useState } from "react";
import { api, messageOf } from "./api";
import { ProviderMark } from "./Brand";
import { LABELS, type Connection, type Model } from "./types";

const API_NAMES: Record<string, string> = {
  codex: "OpenAI API",
  claude: "Claude API",
  grok: "Grok API",
  antigravity: "Gemini API",
  custom: "Custom API",
};
type Draft = {
  id: string;
  provider: string;
  name: string;
  protocol: string;
  endpoint: string;
  key: string;
  env: string;
  models: string;
  default_model: string;
  advanced: boolean;
};
const fresh = (): Draft => ({
  id: "codex-api",
  provider: "codex",
  name: "OpenAI API",
  protocol: "responses",
  endpoint: "",
  key: "",
  env: "",
  models: "",
  default_model: "",
  advanced: false,
});

export function Connections({
  connections,
  onChanged,
  onClose,
}: {
  connections: Connection[];
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const [tests, setTests] = useState<
    Record<string, { ok: boolean; message: string }>
  >({});
  const [draft, setDraft] = useState<Draft>(fresh);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [remove, setRemove] = useState<string | null>(null);
  const [credential, setCredential] = useState<"key" | "env">("key");
  const initialFocus = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    initialFocus.current?.focus();
    const handle = (e: KeyboardEvent) => {
      if (e.altKey && ["1", "2", "3"].includes(e.key)) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
      if (e.key === "Tab") {
        const list = Array.from(
          panel.current?.querySelectorAll<HTMLElement>(
            "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]",
          ) || [],
        ).filter((el) => el.offsetParent !== null);
        const first = list[0],
          last = list.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, [onClose]);
  function edit(c: Connection) {
    setDraft({
      id: c.id,
      provider: c.provider,
      name: c.name,
      protocol: c.protocol || "openai",
      endpoint: c.endpoint || "",
      key: "",
      env: c.api_key_env || "",
      models: JSON.stringify(c.models || [], null, 2),
      default_model: c.default_model || "",
      advanced: true,
    });
    setCredential(c.api_key_env ? "env" : "key");
    setError("");
    setNotice("");
    setRemove(null);
  }
  async function save() {
    setError("");
    let models: Model[] | undefined;
    if (draft.models.trim()) {
      try {
        const value: unknown = JSON.parse(draft.models);
        if (
          !Array.isArray(value) ||
          !value.length ||
          value.some(
            (v) =>
              !v ||
              typeof v.id !== "string" ||
              !v.id.trim() ||
              !Array.isArray(v.efforts) ||
              v.efforts.some((e: unknown) => typeof e !== "string"),
          )
        )
          throw Error();
        models = value as Model[];
      } catch {
        setError(
          "Use a nonempty model array, with an id and efforts array for each model.",
        );
        return;
      }
    }
    if (
      !/^[a-z][a-z0-9_-]{0,63}$/.test(draft.id) ||
      draft.id.endsWith("-cli")
    ) {
      setError(
        "Use a connection ID containing lowercase letters, numbers, underscores, or hyphens.",
      );
      return;
    }
    if (
      draft.provider === "custom" &&
      (!draft.endpoint.trim() || !models || !draft.default_model)
    ) {
      setError(
        "Custom APIs need an endpoint, model catalog, and default model.",
      );
      return;
    }
    if (
      !connections.some((c) => c.id === draft.id) &&
      !(credential === "key" ? draft.key.trim() : draft.env.trim())
    ) {
      setError("Enter an API key or an environment variable name.");
      return;
    }
    setBusy("save");
    try {
      const body = {
        provider: draft.provider,
        name: draft.name,
        protocol: draft.protocol,
        ...(draft.endpoint.trim() ? { endpoint: draft.endpoint.trim() } : {}),
        ...(credential === "key" && draft.key.trim()
          ? { api_key: draft.key }
          : {}),
        ...(credential === "env" && draft.env.trim()
          ? { api_key_env: draft.env.trim() }
          : {}),
        ...(models ? { models } : {}),
        ...(draft.default_model.trim()
          ? { default_model: draft.default_model.trim() }
          : {}),
      };
      await api(`/connections/${encodeURIComponent(draft.id)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setDraft((current) => ({ ...current, key: "" }));
      setNotice(
        "Connection saved. Credentials stay separate from run records.",
      );
      await onChanged();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }
  async function deleteConnection(id: string) {
    setBusy(id);
    setError("");
    try {
      await api(`/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
      setRemove(null);
      if (draft.id === id) setDraft(fresh());
      await onChanged();
      setNotice("API connection removed.");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }
  async function testConnection(c: Connection) {
    setBusy(`test:${c.id}`);
    setError("");
    try {
      const result = await api<{
        ok: boolean;
        connection?: Connection;
        default_model_available?: boolean;
        status?: string;
        message?: string;
      }>(`/connections/${encodeURIComponent(c.id)}/test`, { method: "POST" });
      setTests((current) => ({
        ...current,
        [c.id]: {
          ok: result.ok && result.default_model_available !== false,
          message: result.ok
            ? result.default_model_available === false
              ? "Models discovered, but the configured default model is unavailable. Choose a default from the discovered catalog."
              : `Models discovered${result.connection?.models ? ` · ${result.connection.models.length} available` : ""}. No inference was requested.`
            : result.message || result.status || "Model discovery failed.",
        },
      }));
      if (result.ok) {
        await onChanged();
        if (draft.id === c.id && result.connection) {
          const updated = result.connection;
          setDraft((current) => ({
            ...current,
            models: JSON.stringify(updated.models || [], null, 2),
            default_model: updated.default_model || current.default_model,
          }));
        }
      }
    } catch (err) {
      setTests((current) => ({
        ...current,
        [c.id]: { ok: false, message: messageOf(err) },
      }));
    } finally {
      setBusy("");
    }
  }
  const editing = connections.find(
    (c) => c.id === draft.id && c.transport === "api",
  );
  const apiConnections = connections.filter((c) => c.transport === "api");
  return (
    <div
      className="connection-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="connections-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="connections-title"
        ref={panel}
      >
        <header className="connection-drawer-header">
          <div>
            <span className="eyebrow">YOUR MODELS. YOUR CONNECTIONS.</span>
            <h2 id="connections-title">Connect your workspace</h2>
            <p>Use signed-in local CLIs or bring an API connection.</p>
          </div>
          <button
            className="icon-button"
            ref={initialFocus}
            onClick={onClose}
            aria-label="Close connections"
          >
            ✕
          </button>
        </header>
        <div className="connection-drawer-body">
          <section className="native-connections">
            <div className="section-heading">
              <div>
                <h3>Local agents</h3>
                <p>
                  Run on this machine with the CLI’s existing authentication.
                </p>
              </div>
              <span className="connection-section-tag">LOCAL CLI</span>
            </div>
            <div className="native-connection-grid">
              {connections
                .filter((c) => c.transport === "cli")
                .map((c) => (
                  <article key={c.id}>
                    <ProviderMark provider={c.provider} size={34} />
                    <div>
                      <strong>{LABELS[c.provider] || c.name}</strong>
                      <span
                        className={`status ${c.status === "ready" ? "good" : "pending"}`}
                      >
                        <i />
                        {c.status.replaceAll("_", " ")}
                      </span>
                      <small>
                        {c.cli_status?.version || "Version not reported"}
                      </small>
                    </div>
                    <details>
                      <summary>Details</summary>
                      <code>
                        {c.cli_status?.executable || "CLI not detected"}
                      </code>
                      <p>
                        {c.cli_status?.authenticated === false
                          ? "Sign in through the CLI, then refresh connections."
                          : "Authentication is managed by the CLI."}
                      </p>
                    </details>
                  </article>
                ))}
            </div>
          </section>
          <section className="api-connections">
            <div className="section-heading">
              <div>
                <h3>API connections</h3>
                <p>
                  Remote inference, with execution inside the run’s local
                  workspace.
                </p>
              </div>
              <button
                className="secondary-button small"
                onClick={() => {
                  setDraft({
                    ...fresh(),
                    id: connections.some((c) => c.id === "codex-api")
                      ? `codex-api-${Date.now().toString(36)}`
                      : "codex-api",
                  });
                  setError("");
                  setNotice("");
                  setRemove(null);
                }}
              >
                ＋ New connection
              </button>
            </div>
            {apiConnections.length ? (
              <div className="saved-connections">
                {apiConnections.map((c) => (
                  <article
                    key={c.id}
                    className={draft.id === c.id ? "selected" : ""}
                  >
                    <button
                      onClick={() => edit(c)}
                      className="connection-select"
                    >
                      <ProviderMark
                        provider={
                          c.provider === "antigravity" ? "gemini" : c.provider
                        }
                        size={32}
                      />
                      <span>
                        <strong>{c.name}</strong>
                        <small>
                          {c.api_configured
                            ? `${c.credential_storage || "Credentials configured"} · ${c.key_hint || "configured"}`
                            : "Credentials missing"}
                        </small>
                      </span>
                      <span
                        className={`status ${c.api_configured ? "neutral" : "pending"}`}
                      >
                        {c.status.replaceAll("_", " ")}
                      </span>
                    </button>
                    <button
                      className="text-button connection-test"
                      disabled={!!busy || !c.api_configured}
                      onClick={() => void testConnection(c)}
                    >
                      {busy === `test:${c.id}`
                        ? "Discovering…"
                        : "Test & discover"}
                    </button>
                    <button
                      className="text-button connection-remove"
                      onClick={() => setRemove(c.id)}
                      aria-label={`Remove ${c.name}`}
                    >
                      Remove
                    </button>
                    {tests[c.id] && (
                      <p
                        className={`connection-test-result ${tests[c.id].ok ? "success" : "error"}`}
                        role="status"
                      >
                        {tests[c.id].message}
                      </p>
                    )}
                    {remove === c.id && (
                      <div className="connection-delete-confirm">
                        <p>Remove this connection and its stored key?</p>
                        <button
                          className="danger-button"
                          disabled={!!busy}
                          onClick={() => void deleteConnection(c.id)}
                        >
                          Remove connection
                        </button>
                        <button
                          className="text-button"
                          onClick={() => setRemove(null)}
                        >
                          Keep it
                        </button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="connection-empty">
                No API connections yet. Your local agents remain available
                above.
              </p>
            )}
          </section>
          <section className="connection-form">
            <div className="connection-form-title">
              <span className="eyebrow">
                {editing ? "EDIT CONNECTION" : "ADD AN API"}
              </span>
              <h3>{draft.name || "New connection"}</h3>
            </div>
            <div className="connection-form-grid">
              <label>
                Provider
                <select
                  value={draft.provider}
                  onChange={(e) => {
                    const provider = e.target.value;
                    setDraft({
                      ...fresh(),
                      id: connections.some((c) => c.id === `${provider}-api`)
                        ? `${provider}-api-${Date.now().toString(36)}`
                        : `${provider}-api`,
                      provider,
                      name: API_NAMES[provider],
                      protocol:
                        provider === "claude"
                          ? "anthropic"
                          : provider === "antigravity" || provider === "custom"
                            ? "openai"
                            : "responses",
                      advanced: provider === "custom",
                    });
                  }}
                >
                  {Object.entries(API_NAMES).map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Connection name
                <input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
            </div>
            <div className="credential-choice" aria-label="Credential source">
              <button
                aria-pressed={credential === "key"}
                className={credential === "key" ? "selected" : ""}
                onClick={() => setCredential("key")}
              >
                API key
              </button>
              <button
                aria-pressed={credential === "env"}
                className={credential === "env" ? "selected" : ""}
                onClick={() => setCredential("env")}
              >
                Environment variable
              </button>
            </div>
            {credential === "key" ? (
              <label>
                API key
                {editing && <small>Leave blank to keep the current key.</small>}
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={draft.key}
                  onChange={(e) => setDraft({ ...draft, key: e.target.value })}
                  placeholder={
                    editing
                      ? "Current key is stored securely"
                      : "Paste your API key"
                  }
                />
              </label>
            ) : (
              <label>
                Environment variable name
                <input
                  className="mono"
                  spellCheck={false}
                  value={draft.env}
                  onChange={(e) => setDraft({ ...draft, env: e.target.value })}
                  placeholder="OPENAI_API_KEY"
                />
              </label>
            )}
            <p className="credential-help">
              Keys are stored in macOS Keychain on Mac. Other platforms use an
              environment reference. Keys are never included in profiles or run
              records.
            </p>
            {draft.provider === "antigravity" && (
              <p className="connection-note">
                This connects to the Gemini API. Antigravity CLI uses its own
                signed-in account.
              </p>
            )}
            <details
              className="connection-advanced"
              open={draft.advanced}
              onToggle={(e) => {
                const open = e.currentTarget.open;
                setDraft((d) =>
                  d.advanced === open ? d : { ...d, advanced: open },
                );
              }}
            >
              <summary>
                Endpoint & model catalog <span>Advanced</span>
              </summary>
              <div className="connection-form-grid">
                <label>
                  Connection ID
                  <input
                    className="mono"
                    value={draft.id}
                    disabled={!!editing}
                    onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                  />
                </label>
                <label>
                  API protocol
                  <select
                    value={draft.protocol}
                    onChange={(e) =>
                      setDraft({ ...draft, protocol: e.target.value })
                    }
                  >
                    <option value="responses">Responses API</option>
                    <option value="anthropic">Anthropic Messages</option>
                    <option value="openai">OpenAI-compatible Chat</option>
                  </select>
                </label>
              </div>
              <label>
                Inference endpoint
                <input
                  className="mono"
                  value={draft.endpoint}
                  onChange={(e) =>
                    setDraft({ ...draft, endpoint: e.target.value })
                  }
                  placeholder={
                    draft.provider === "custom"
                      ? "https://your-provider.example/v1"
                      : "Official provider endpoint (default)"
                  }
                />
              </label>
              <label>
                Model catalog{" "}
                <small>JSON array; declare supported efforts explicitly.</small>
                <textarea
                  className="mono"
                  rows={5}
                  value={draft.models}
                  onChange={(e) =>
                    setDraft({ ...draft, models: e.target.value })
                  }
                  placeholder={
                    '[{"id":"your-model","label":"Your model","efforts":[]}]'
                  }
                />
              </label>
              <label>
                Default model ID
                <input
                  className="mono"
                  value={draft.default_model}
                  onChange={(e) =>
                    setDraft({ ...draft, default_model: e.target.value })
                  }
                  placeholder="Use the provider catalog default"
                />
              </label>
              <p className="muted">
                An empty catalog uses the maintained provider catalog. Custom
                endpoints require explicit models and capabilities.
              </p>
            </details>
            {error && (
              <p className="connection-feedback error" role="alert">
                {error}
              </p>
            )}
            {notice && (
              <p className="connection-feedback success" role="status">
                {notice}
              </p>
            )}
            <div className="connection-form-footer">
              <span>SSH and remote execution are not supported.</span>
              <button
                className="primary-button"
                onClick={() => void save()}
                disabled={!!busy}
              >
                {busy === "save"
                  ? "Saving…"
                  : editing
                    ? "Update connection"
                    : "Save connection"}{" "}
                <span>↗</span>
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
