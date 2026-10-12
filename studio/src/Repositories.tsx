import { useEffect, useRef, useState } from "react";
import { api, messageOf, relayApi } from "./api";
import { workflowAccess, type WorkflowAuthority } from "./workflow-state";
import "./repositories.css";
import { GitHubConnection } from "./GitHubConnection";
import type { GitHubProject } from "./github-connection-state";

type ProjectContext = {
  workspace?: string;
  authority?: (WorkflowAuthority & { projects?: string[] }) | null;
};
type Binding = {
  id: string;
  worker?: string;
  project: string;
  full_name: string;
  base: string;
};
type Snapshot = {
  scope: string;
  projects: string[];
  authority: WorkflowAuthority | null;
  bindings: Binding[];
  bindingError: string;
};

export function authorizedProjects(
  context: ProjectContext,
  paired: boolean,
): string[] {
  const paths = paired ? context.authority?.projects : [context.workspace];
  return Array.isArray(paths)
    ? [
        ...new Set(
          paths.filter((p): p is string => typeof p === "string" && !!p.trim()),
        ),
      ]
    : [];
}

export function repositoryBindings(
  bindings: Binding[],
  projects: string[],
  worker?: string,
): Binding[] {
  return bindings.filter(
    (binding) =>
      projects.includes(binding.project) &&
      (!worker || binding.worker === worker),
  );
}

export function Repositories({
  active,
  worker,
  machineName,
  paired,
  online,
  workspace,
  canManage,
  onNewTask,
  onManage,
  accountIdentity,
  connectionRequest,
  onBindingUpdated,
}: {
  active: boolean;
  worker?: string;
  machineName: string;
  paired: boolean;
  online: boolean;
  workspace: string;
  canManage: boolean;
  onNewTask: (project: string) => void;
  onManage?: (section: "projects" | "github") => void;
  accountIdentity?: { actor?: string; workspace: string };
  connectionRequest?: { sequence: number; target?: GitHubProject };
  onBindingUpdated?: () => void;
}) {
  const scope = JSON.stringify([
    worker,
    paired,
    online,
    workspace,
    accountIdentity?.actor,
    accountIdentity?.workspace,
  ]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [connection, setConnection] = useState<{
    scope: string;
    path: string;
  } | null>(null);
  const [returnNotice, setReturnNotice] = useState("");
  const handledRequest = useRef<number | undefined>(undefined);
  const opener = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    setSnapshot(null);
    setError("");
    if (!online) return () => abort.abort();
    void api<ProjectContext>("/context", { signal: abort.signal })
      .then(async (context) => {
        if (abort.signal.aborted) return;
        if (paired && !context.authority)
          throw new Error(
            "Workspace permissions are unavailable. Update or reconnect this worker before choosing a repository.",
          );
        if (
          paired &&
          accountIdentity &&
          (context.authority?.actor !== accountIdentity.actor ||
            (context.authority as WorkflowAuthority & { workspace?: string })
              ?.workspace !== accountIdentity.workspace)
        )
          throw new Error(
            "Workspace access changed. Reload Studio before choosing a repository.",
          );
        const projects = authorizedProjects(context, paired);
        let bindings: Binding[] = [];
        let bindingError = "";
        if (paired) {
          try {
            bindings = await relayApi<Binding[]>("/github/bindings", {
              signal: abort.signal,
            });
          } catch (failure) {
            bindingError = messageOf(failure);
          }
        }
        if (!abort.signal.aborted)
          setSnapshot({
            scope,
            projects,
            authority: context.authority || null,
            bindings: repositoryBindings(bindings, projects, worker),
            bindingError,
          });
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setError(messageOf(failure));
      });
    return () => abort.abort();
  }, [active, scope, revision, paired, online, worker]);
  // Never render a previous worker/project snapshot while a fresh request runs.
  const current = online && snapshot?.scope === scope ? snapshot : null;
  const access = workflowAccess(current?.authority || null, paired);
  const managementAvailable =
    active &&
    !!current &&
    canManage &&
    (!paired || current.authority?.role === "owner");
  const connectedPath =
    connection?.scope === scope && managementAvailable ? connection.path : "";
  useEffect(() => {
    if (
      !connectionRequest ||
      handledRequest.current === connectionRequest.sequence ||
      !current
    )
      return;
    handledRequest.current = connectionRequest.sequence;
    if (!connectionRequest.target) {
      if (document.activeElement === document.body)
        document.getElementById("repositories-title")?.focus();
      return;
    }
    if (
      !managementAvailable ||
      connectionRequest.target.worker !== worker ||
      !current.projects.includes(connectionRequest.target.path)
    ) {
      setReturnNotice(
        "GitHub authorization returned, but this project is no longer available here. Choose a currently approved project to continue.",
      );
      return;
    }
    setConnection({ scope, path: connectionRequest.target.path });
  }, [connectionRequest, current, managementAvailable, worker, scope]);
  useEffect(() => {
    if (connectedPath) heading.current?.focus();
  }, [connectedPath]);
  function closeConnection() {
    setConnection(null);
    if (opener.current?.isConnected) opener.current.focus();
    else document.getElementById("repositories-title")?.focus();
    opener.current = null;
  }
  return (
    <section className="repositories-page" aria-labelledby="repositories-title">
      <header className="studio-page-heading">
        <div>
          <h1 id="repositories-title" tabIndex={-1}>
            Repositories
          </h1>
          <p>
            Your approved project folders on {machineName}. GitHub delivery is a
            separate connection.
          </p>
        </div>
        {onManage && managementAvailable && (
          <button
            className="primary-button"
            onClick={() => onManage("projects")}
          >
            Manage project access
          </button>
        )}
      </header>
      {returnNotice && <p role="status">{returnNotice}</p>}
      {!online ? (
        <div className="repository-empty" role="status">
          <h2>Worker offline</h2>
          <p>
            Reconnect {machineName} to refresh project permissions. Cached
            folders cannot start a task.
          </p>
        </div>
      ) : error ? (
        <div className="repository-empty" role="alert">
          <h2>Repositories unavailable</h2>
          <p>{error}</p>
          <button
            className="secondary-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      ) : !current ? (
        <p role="status">Checking approved project folders…</p>
      ) : !current.projects.length ? (
        <div className="repository-empty">
          <h2>No approved projects</h2>
          <p>
            {canManage
              ? "Approve a folder on the worker, then bind its workspace access."
              : "Ask the workspace Owner to grant access to a project on this worker."}
          </p>
        </div>
      ) : (
        <div className="repository-list">
          {current.projects.map((project) => {
            const bindings = current.bindings.filter(
              (binding) => binding.project === project,
            );
            return (
              <article className="repository-project" key={project}>
                <div className="repository-identity">
                  <h2>{project.split("/").filter(Boolean).at(-1)}</h2>
                  <code>{project}</code>
                  <p>{machineName} · Approved project folder</p>
                </div>
                <div className="repository-delivery">
                  <h3>GitHub delivery</h3>
                  {current.bindingError ? (
                    <div role="status">
                      <p>
                        Connection status unavailable.{" "}
                        <button
                          className="text-button"
                          onClick={() => setRevision((n) => n + 1)}
                        >
                          Refresh
                        </button>
                      </p>
                      <details>
                        <summary>Connection details</summary>
                        <p>{current.bindingError}</p>
                      </details>
                    </div>
                  ) : bindings.length ? (
                    <ul>
                      {bindings.map((binding) => (
                        <li key={binding.id}>
                          <strong>{binding.full_name}</strong>
                          <span>Base: {binding.base}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>
                      No repository bound. Local delivery is available after
                      approval.
                    </p>
                  )}
                </div>
                <div className="repository-actions">
                  {access.deliver && (
                    <button
                      className="primary-button"
                      onClick={() => onNewTask(project)}
                    >
                      New task
                    </button>
                  )}
                  {paired &&
                    worker &&
                    accountIdentity?.actor &&
                    managementAvailable && (
                      <button
                        className="secondary-button"
                        aria-expanded={connectedPath === project}
                        onClick={(event) => {
                          if (connectedPath === project) closeConnection();
                          else {
                            opener.current = event.currentTarget;
                            setReturnNotice("");
                            setConnection({ scope, path: project });
                          }
                        }}
                      >
                        Connect GitHub delivery
                      </button>
                    )}
                </div>
                {connectedPath === project &&
                  worker &&
                  accountIdentity?.actor && (
                    <section
                      className="repository-connection-panel"
                      aria-labelledby="github-connection-title"
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          event.preventDefault();
                          closeConnection();
                        }
                      }}
                    >
                      <header>
                        <h3
                          id="github-connection-title"
                          ref={heading}
                          tabIndex={-1}
                        >
                          Connect GitHub delivery
                        </h3>
                        <button
                          className="text-button"
                          onClick={closeConnection}
                        >
                          Close connection setup
                        </button>
                      </header>
                      <GitHubConnection
                        identity={{
                          actor: accountIdentity.actor,
                          workspace: accountIdentity.workspace,
                        }}
                        target={{ worker, path: project, machineName }}
                        online={online}
                        canManage={managementAvailable}
                        onConnected={(binding) => {
                          setSnapshot((previous) =>
                            previous?.scope === scope
                              ? {
                                  ...previous,
                                  bindings: [
                                    ...previous.bindings.filter(
                                      (item) => item.id !== binding.id,
                                    ),
                                    binding,
                                  ],
                                }
                              : previous,
                          );
                        onBindingUpdated?.();
                        }}
                      />
                    </section>
                  )}
              </article>
            );
          })}
        </div>
      )}
      <aside className="repository-setup-note">
        <h2>
          {paired ? "Use an existing project" : "Open another local project"}
        </h2>
        <p>
          {paired
            ? "Approve an existing folder on its worker, then manage who can access it here. GitHub delivery connects that folder to a repository for draft pull requests; it does not clone a repository."
            : "Choose an existing folder in the Parallax launcher, or start local Studio with that project path. Browser Studio cannot browse your filesystem or clone a repository."}
        </p>
        {paired && !canManage && (
          <p>
            Workspace Owners manage project access and GitHub installations.
          </p>
        )}
      </aside>
    </section>
  );
}
