import { useEffect, useRef, useState } from "react";
import { relayApi, messageOf } from "./api";
import type { Session } from "./session";
import { workflowOperationId, type WorkflowAuthority } from "./workflow-state";
import {
  rememberGitHubReturn,
  type GitHubIdentity,
  type GitHubProject,
} from "./github-connection-state";

export type GitHubBinding = {
  id: string;
  worker: string;
  project: string;
  installation: number;
  repository: number;
  full_name: string;
  base: string;
};
type Config = {
  configured: boolean;
  installation_url: string;
  features?: string[];
};
type Repo = { id: number; full_name: string; default_branch: string };
type Setup = { scope: string; config: Config; installations: number[] };
const githubLink = (value: string, path: string) => {
  try {
    const url = new URL(value);
    return url.origin === "https://github.com" &&
      url.pathname.startsWith(path) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
};

export function GitHubConnection({
  identity,
  target,
  online,
  canManage,
  onConnected,
}: {
  identity: GitHubIdentity;
  target: GitHubProject;
  online: boolean;
  canManage: boolean;
  onConnected: (binding: GitHubBinding) => void;
}) {
  const scope = JSON.stringify([
    identity.actor,
    identity.workspace,
    target.worker,
    target.path,
    online,
    canManage,
  ]);
  const current = useRef(scope);
  current.current = scope;
  const mounted = useRef(true);
  const action = useRef(false);
  const selection = useRef(0);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [repoError, setRepoError] = useState("");
  const [busy, setBusy] = useState("");
  const [installation, setInstallation] = useState(0);
  const [repository, setRepository] = useState(0);
  const [base, setBase] = useState("");
  const [repos, setRepos] = useState<{
    scope: string;
    installation: number;
    values: Repo[];
  } | null>(null);
  const [repoLoading, setRepoLoading] = useState(false);
  const [connected, setConnected] = useState<{
    scope: string;
    value: GitHubBinding;
  } | null>(null);
  const generation = useRef({ scope, revision, value: 0 });
  if (generation.current.scope !== scope || generation.current.revision !== revision)
    generation.current = { scope, revision, value: generation.current.value + 1 };
  const epoch = generation.current.value;
  const live = () =>
    mounted.current && current.current === scope && generation.current.value === epoch && online && canManage;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    setSetup(null);
    setError("");
    setRepoError("");
    setRepos(null);
    setInstallation(0);
    setRepository(0);
    setBase("");
    setBusy("");
    setRepoLoading(false);
    setConnected(null);
    action.current = false;
    selection.current++;
    if (!online || !canManage) return () => abort.abort();
    void (async () => {
      try {
        const config = await relayApi<Config>("/github/config", {
          signal: abort.signal,
        });
        if (!live() || abort.signal.aborted) return;
        const installations = config.configured
          ? await relayApi<number[]>("/github/installations", {
              signal: abort.signal,
            })
          : [];
        if (live() && !abort.signal.aborted)
          setSetup({ scope, config, installations });
      } catch (failure) {
        if (live() && !abort.signal.aborted) setError(messageOf(failure));
      }
    })();
    return () => abort.abort();
  }, [scope, revision]);
  const ready = setup?.scope === scope ? setup : null;
  const choices =
    repos?.scope === scope && repos.installation === installation
      ? repos.values
      : [];
  const selected = choices.find((value) => value.id === repository);
  const saved = connected?.scope === scope ? connected.value : null;
  const supported = ready?.config.features?.includes(
    "github-binding-idempotency-v1",
  );
  const formIdentity = JSON.stringify([scope, installation, repository, base]);
  const formRef = useRef(formIdentity);
  formRef.current = formIdentity;
  async function loadRepositories(id: number) {
    if (!live() || action.current || !ready?.installations.includes(id)) return;
    const request = ++selection.current;
    setInstallation(id);
    setRepository(0);
    setBase("");
    setRepos(null);
    setRepoError("");
    setRepoLoading(true);
    try {
      const values = await relayApi<Repo[]>(
        `/github/installations/${id}/repositories`,
      );
      if (live() && selection.current === request)
        setRepos({ scope, installation: id, values });
    } catch (failure) {
      if (live() && selection.current === request)
        setRepoError(messageOf(failure));
    } finally {
      if (live() && selection.current === request) setRepoLoading(false);
    }
  }
  async function permission() {
    const session = await relayApi<Session>("/session");
    if (!live()) return false;
    if (
      session.account?.id !== identity.actor ||
      session.workspace.id !== identity.workspace ||
      (session.workspace.kind === "team" && session.workspace.role !== "owner")
    )
      throw new Error(
        "Workspace access changed. Reload Studio before connecting a repository.",
      );
    const context = await relayApi<{
      authority?: WorkflowAuthority & {
        workspace?: string;
        projects?: string[];
      };
    }>(`/executors/${encodeURIComponent(target.worker)}/proxy/context`);
    if (!live()) return false;
    const authority = context.authority;
    if (
      !authority ||
      authority.actor !== identity.actor ||
      authority.workspace !== identity.workspace ||
      authority.role !== "owner" ||
      !authority.projects?.includes(target.path)
    )
      throw new Error(
        "This project is no longer available to you as an Owner. Refresh its workspace access.",
      );
    return true;
  }
  async function authorize() {
    if (!live() || action.current || !ready?.config.configured) return;
    action.current = true;
    setBusy("authorize");
    setError("");
    try {
      if (!(await permission())) return;
      const response = await relayApi<{ url: string }>(
        "/github/connect/start",
        { method: "POST" },
      );
      if (!live()) return;
      const url = githubLink(response.url, "/login/oauth/authorize");
      if (!url)
        throw new Error(
          "GitHub returned an unexpected authorization address. Retry the connection.",
        );
      rememberGitHubReturn(identity, target);
      location.assign(url);
    } catch (failure) {
      if (live()) setError(messageOf(failure));
    } finally {
      if (live()) {
        action.current = false;
        setBusy("");
      }
    }
  }
  async function bind() {
    if (
      !live() ||
      formRef.current !== formIdentity ||
      action.current ||
      !supported ||
      !selected ||
      !base.trim() ||
      repoLoading ||
      repoError ||
      saved
    )
      return;
    const signature = JSON.stringify([
      target.worker,
      target.path,
      installation,
      selected.id,
      base.trim(),
    ]);
    const requestId = workflowOperationId(
      JSON.stringify([identity.actor, identity.workspace]),
      "github-binding",
      signature,
    );
    action.current = true;
    setBusy("bind");
    setError("");
    try {
      if (!(await permission())) return;
      if (formRef.current !== formIdentity) return;
      const value = await relayApi<GitHubBinding>("/github/bindings", {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          installation,
          repository: selected.id,
          worker: target.worker,
          project: target.path,
          base: base.trim(),
        }),
      });
      if (!live()) return;
      if (
        value.worker !== target.worker ||
        value.project !== target.path ||
        value.installation !== installation ||
        value.repository !== selected.id ||
        value.base !== base.trim()
      )
        throw new Error(
          "The returned connection does not match this project. Refresh before continuing.",
        );
      setConnected({ scope, value });
      onConnected(value);
    } catch (failure) {
      if (live()) setError(messageOf(failure));
    } finally {
      if (live()) {
        action.current = false;
        setBusy("");
      }
    }
  }
  if (!online)
    return (
      <p role="status">
        Reconnect {target.machineName} to connect this project.
      </p>
    );
  if (!canManage)
    return <p role="status">A workspace Owner must connect GitHub delivery.</p>;
  return (
    <div className="github-connection">
      <p>
        Choose where approved changes from this folder can be published as draft
        pull requests.
      </p>
      <dl className="github-connection-target">
        <div>
          <dt>Machine</dt>
          <dd>{target.machineName}</dd>
        </div>
        <div>
          <dt>Project folder</dt>
          <dd>
            <code>{target.path}</code>
          </dd>
        </div>
      </dl>
      {error && (
        <div role="alert">
          <p>{error}</p>
          {!ready && (
            <button
              className="secondary-button"
              onClick={() => {
                if (live()) setRevision((n) => n + 1);
              }}
            >
              Retry connection setup
            </button>
          )}
        </div>
      )}
      {!ready ? (
        !error && <p role="status">Loading GitHub connection…</p>
      ) : !ready.config.configured ? (
        <div className="github-connection-note">
          <p>
            GitHub delivery is not enabled on this deployment. Its operator must
            configure the GitHub App.
          </p>
          <p>You can still prepare a task for local delivery.</p>
          <button
            className="secondary-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Check again
          </button>
        </div>
      ) : saved ? (
        <div className="github-connection-success" role="status">
          <h4>Repository connected</h4>
          <p>
            {saved.full_name} · {saved.base}
          </p>
          <p>
            Choose GitHub delivery when starting a new task. Each candidate
            still needs checks, review and human approval before publication.
          </p>
        </div>
      ) : (
        <>
          <div className="github-authorization">
            {!ready.installations.length && (
              <p>
                No GitHub App installations are connected to this workspace.
              </p>
            )}
            <div className="github-connection-actions">
              <button
                className={
                  ready.installations.length
                    ? "secondary-button"
                    : "primary-button"
                }
                disabled={!!busy}
                onClick={() => void authorize()}
              >
                {busy === "authorize"
                  ? "Opening GitHub…"
                  : ready.installations.length
                    ? "Authorize another installation"
                    : "Authorize GitHub delivery"}
              </button>
              {githubLink(ready.config.installation_url, "/apps/") && (
                <a
                  href={githubLink(ready.config.installation_url, "/apps/")}
                  target="_blank"
                  rel="noreferrer"
                >
                  Install or manage the GitHub App
                </a>
              )}
            </div>
            <p>
              GitHub sign-in and delivery authorization are separate. This
              connects an existing folder; it does not clone a repository.
            </p>
          </div>
          {ready.installations.length > 0 && (
            <fieldset disabled={!!busy}>
              <legend>Delivery destination</legend>
              <label>
                Installation
                <select
                  value={installation}
                  onChange={(e) => {
                    const id = Number(e.target.value);
                    if (id) void loadRepositories(id);
                    else {
                      selection.current++;
                      setInstallation(0);
                      setRepository(0);
                      setBase("");
                      setRepos(null);
                      setRepoLoading(false);
                      setRepoError("");
                    }
                  }}
                >
                  <option value={0}>Choose installation</option>
                  {ready.installations.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              </label>
              {repoLoading && (
                <p role="status">Loading selected repositories…</p>
              )}
              {repoError && (
                <div role="alert">
                  <p>Repositories could not load: {repoError}</p>
                  <button
                    className="secondary-button"
                    onClick={() => void loadRepositories(installation)}
                  >
                    Retry repositories
                  </button>
                </div>
              )}
              {installation > 0 &&
                !repoLoading &&
                !repoError &&
                repos &&
                choices.length === 0 && (
                  <p role="status">
                    No repositories are available for this installation. Select
                    repositories in the GitHub App settings, then retry.
                    <button
                      className="text-button"
                      onClick={() => void loadRepositories(installation)}
                    >
                      Refresh repositories
                    </button>
                  </p>
                )}
              {choices.length > 0 && (
                <>
                  <label>
                    Repository
                    <select
                      value={repository}
                      onChange={(e) => {
                        const id = Number(e.target.value);
                        setRepository(id);
                        setBase(
                          choices.find((repo) => repo.id === id)
                            ?.default_branch || "",
                        );
                      }}
                    >
                      <option value={0}>Choose repository</option>
                      {choices.map((repo) => (
                        <option key={repo.id} value={repo.id}>
                          {repo.full_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {selected && (
                    <>
                      <label>
                        Remote base branch
                        <input
                          value={base}
                          onChange={(e) => setBase(e.target.value)}
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </label>
                      <p>
                        The captured project must match this remote base when
                        starting a GitHub task and publishing its approved
                        candidate.
                      </p>
                    </>
                  )}
                </>
              )}
              {!supported && (
                <p role="status">
                  Update the relay to connect repositories with safe retry
                  support.
                </p>
              )}
              <button
                className="primary-button"
                disabled={
                  !supported ||
                  !selected ||
                  !base.trim() ||
                  repoLoading ||
                  !!repoError ||
                  !!busy
                }
                onClick={() => void bind()}
              >
                {busy === "bind"
                  ? "Connecting repository…"
                  : "Connect repository"}
              </button>
            </fieldset>
          )}
        </>
      )}
    </div>
  );
}
