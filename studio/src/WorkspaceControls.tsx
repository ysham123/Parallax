import { useEffect, useRef, useState } from "react";
import { relayApi, messageOf } from "./api";
import { CopyBlock } from "./Onboarding";
import type { Session, ExecutionMachine } from "./session";
import { invitationToken, rememberInvitation } from "./session";
import "./pilot.css";

type Space = { id: string; name: string; kind: string; role: string };
type Member = { account: string; role: string; login: string; name: string };
type ProjectBinding = {
  id: string;
  worker: string;
  path: string;
  members: string | string[];
};
function boundMembers(binding: ProjectBinding): string[] | null {
  try {
    const value =
      typeof binding.members === "string"
        ? JSON.parse(binding.members)
        : binding.members;
    return Array.isArray(value) &&
      value.every((member) => typeof member === "string")
      ? value
      : null;
  } catch {
    return null;
  }
}
export function WorkspaceControls({
  session,
  machines,
  onSwitch,
  openRequest,
  onRepositories,
}: {
  session: Session;
  machines: ExecutionMachine[];
  onSwitch: () => void;
  onRepositories?: () => void;
  openRequest?: {
    sequence: number;
    section: "workspace" | "projects" | "github";
  };
}) {
  const details = useRef<HTMLDetailsElement>(null);
  const openedRequest = useRef<number | undefined>(undefined);
  const openedFrom = useRef<HTMLElement | null>(null);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("developer");
  const [invitation, setInvitation] = useState("");
  const [incoming, setIncoming] = useState(() =>
    invitationToken(location.search),
  );
  const [panelOpen, setPanelOpen] = useState(!!incoming);
  const [project, setProject] = useState("");
  const [permittedMembers, setPermittedMembers] = useState<string[]>([]);
  const [bindings, setBindings] = useState<ProjectBinding[]>([]);
  const [bindingId, setBindingId] = useState("");
  const [policyMembers, setPolicyMembers] = useState<string[]>([]);
  const [policyScope, setPolicyScope] = useState("unknown");
  const pendingPolicies = useRef(
    new Map<string, { signature: string; id: string }>(),
  );
  const team = session.workspace.kind === "team";
  const owner = !team || session.workspace.role === "owner";
  const projects = machines.flatMap((m) =>
    m.workspaces.map((path) => ({
      key: JSON.stringify([m.id, path]),
      worker: m.id,
      path,
      name: m.name,
    })),
  );
  const selectedProject = projects.find((p) => p.key === project);
  const selectedBinding = bindings.find((binding) => binding.id === bindingId);
  function editPolicy(scope: string, nextMembers: string[]) {
    pendingPolicies.current.delete(bindingId);
    setPolicyScope(scope);
    setPolicyMembers(nextMembers);
  }
  async function savePolicy() {
    if (
      !team ||
      !owner ||
      busy ||
      !selectedBinding ||
      policyScope === "unknown" ||
      (policyScope === "selected" && !policyMembers.length)
    )
      return;
    const nextMembers =
      policyScope === "all" ? [] : [...new Set(policyMembers)].sort();
    const currentMembers = new Set(members.map((member) => member.account));
    if (nextMembers.some((member) => !currentMembers.has(member))) return;
    const signature = JSON.stringify([
      session.workspace.id,
      session.account?.id,
      selectedBinding.id,
      nextMembers,
    ]);
    if (
      pendingPolicies.current.get(selectedBinding.id)?.signature !== signature
    )
      pendingPolicies.current.set(selectedBinding.id, {
        signature,
        id: crypto.randomUUID(),
      });
    const operation = pendingPolicies.current.get(selectedBinding.id)!;
    await run(async () => {
      await relayApi(
        `/workspaces/projects/${encodeURIComponent(selectedBinding.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            request_id: operation.id,
            members: nextMembers,
          }),
        },
      );
      setBindings((prior) =>
        prior.map((binding) =>
          binding.id === selectedBinding.id
            ? { ...binding, members: nextMembers }
            : binding,
        ),
      );
      pendingPolicies.current.delete(selectedBinding.id);
      setNotice(
        "Project permissions saved. Archived records follow the same current permissions; disconnected machines remain revoked.",
      );
    });
  }
  function closePanel(restoreFocus = true) {
    setPanelOpen(false);
    if (restoreFocus) {
      if (openedFrom.current?.isConnected) openedFrom.current.focus();
      else details.current?.querySelector("summary")?.focus();
    }
    openedFrom.current = null;
  }
  useEffect(() => {
    if (!openRequest || openedRequest.current === openRequest.sequence) return;
    openedRequest.current = openRequest.sequence;
    openedFrom.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setPanelOpen(true);
  }, [openRequest]);
  useEffect(() => {
    if (!panelOpen || !openRequest) return;
    const target = details.current?.querySelector<HTMLElement>(
      `[data-workspace-section="${openRequest.section}"]`,
    );
    target?.scrollIntoView?.({ block: "nearest" });
    target?.focus({ preventScroll: true });
  }, [panelOpen, openRequest]);
  useEffect(() => {
    if (!panelOpen) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePanel();
      }
    };
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        details.current &&
        !details.current.contains(event.target)
      )
        closePanel(false);
    };
    window.addEventListener("keydown", escape);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.removeEventListener("keydown", escape);
      document.removeEventListener("pointerdown", outside);
    };
  }, [panelOpen]);
  useEffect(() => {
    if (!session.account) return;
    const abort = new AbortController();
    relayApi<Space[]>("/workspaces", { signal: abort.signal })
      .then((v) => {
        if (!abort.signal.aborted) setSpaces(v);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(messageOf(e));
      });
    if (team)
      relayApi<Member[]>("/workspaces/members", { signal: abort.signal })
        .then((v) => {
          if (!abort.signal.aborted) setMembers(v);
        })
        .catch((e) => {
          if (!abort.signal.aborted) setError(messageOf(e));
        });
    if (team)
      relayApi<ProjectBinding[]>("/workspaces/projects", {
        signal: abort.signal,
      })
        .then((value) => {
          if (!abort.signal.aborted) setBindings(value);
        })
        .catch((e) => {
          if (!abort.signal.aborted) {
            setBindings([]);
            setError(messageOf(e));
          }
        });
    return () => abort.abort();
  }, [session.workspace.id, session.account?.id, team, owner]);
  if (!session.account) return null;
  async function run(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details
      className="workspace-controls"
      ref={details}
      open={panelOpen}
      onToggle={(e) => setPanelOpen(e.currentTarget.open)}
    >
      <summary>
        <span className="workspace-control-name">{session.workspace.name}</span>
        <span className="workspace-control-separator"> · </span>
        <span className="workspace-control-role">
          {session.workspace.role || "owner"}
        </span>
      </summary>
      <div
        className="workspace-panel"
        role="region"
        aria-label="Workspace settings"
      >
        <h2 tabIndex={-1} data-workspace-section="workspace">
          Workspace
        </h2>
        <button className="secondary-button" onClick={() => closePanel()}>
          Close workspace settings
        </button>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        <fieldset disabled={busy}>
          <label>
            Switch workspace
            <select
              value={session.workspace.id}
              onChange={(e) =>
                void run(async () => {
                  await relayApi(`/workspaces/${e.target.value}/switch`, {
                    method: "POST",
                  });
                  onSwitch();
                })
              }
            >
              {spaces.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.kind}
                </option>
              ))}
            </select>
          </label>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const created = await relayApi<Space>("/workspaces", {
                  method: "POST",
                  body: JSON.stringify({ name }),
                });
                setSpaces((s) => [...s, created]);
                setName("");
                setNotice(
                  "Team created. Switch into it to invite members and pair a worker explicitly.",
                );
              });
            }}
          >
            <label>
              New team name
              <input
                value={name}
                maxLength={80}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <button>Create team workspace</button>
          </form>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await relayApi("/invitations/accept", {
                  method: "POST",
                  body: JSON.stringify({ token: incoming }),
                });
                const destination = new URL(location.href);
                destination.searchParams.delete("invite");
                history.replaceState(
                  null,
                  "",
                  destination.pathname + destination.search + destination.hash,
                );
                rememberInvitation(null);
                setIncoming("");
                setSpaces(await relayApi<Space[]>("/workspaces"));
                setNotice(
                  "Invitation accepted. Select the team workspace above.",
                );
              });
            }}
          >
            <label>
              Invitation code
              <input
                value={incoming}
                onChange={(e) => setIncoming(e.target.value)}
                required
              />
            </label>
            <button>Accept invitation</button>
          </form>
          {team && owner && (
            <>
              <h3>Membership</h3>
              <label>
                Invitation role
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="developer">Developer</option>
                  <option value="reviewer">Reviewer</option>
                </select>
              </label>
              <button
                onClick={() =>
                  void run(async () => {
                    const v = await relayApi<{ token: string }>(
                      "/workspaces/invitations",
                      { method: "POST", body: JSON.stringify({ role }) },
                    );
                    setInvitation(
                      `${location.origin}/?invite=${encodeURIComponent(v.token)}`,
                    );
                  })
                }
              >
                Create invitation link
              </button>
              <p>
                Links expire after seven days and work once. Copy the link and
                send it yourself.
              </p>
              {invitation && (
                <CopyBlock
                  label="Workspace invitation link"
                  text={invitation}
                />
              )}
              {members.map((m) => (
                <div className="member-row" key={m.account}>
                  <span>{m.name || m.login}</span>
                  <select
                    aria-label={`Role for ${m.login}`}
                    value={m.role}
                    onChange={(e) =>
                      void run(async () => {
                        await relayApi(`/workspaces/members/${m.account}`, {
                          method: "PATCH",
                          body: JSON.stringify({ role: e.target.value }),
                        });
                        setMembers(
                          await relayApi<Member[]>("/workspaces/members"),
                        );
                      })
                    }
                  >
                    <option value="owner">Owner</option>
                    <option value="developer">Developer</option>
                    <option value="reviewer">Reviewer</option>
                  </select>
                  <button
                    type="button"
                    aria-label={`Remove ${m.name || m.login} from workspace`}
                    onClick={() =>
                      void run(async () => {
                        await relayApi(`/workspaces/members/${m.account}`, {
                          method: "DELETE",
                        });
                        setMembers(
                          await relayApi<Member[]>("/workspaces/members"),
                        );
                      })
                    }
                  >
                    Remove
                  </button>
                </div>
              ))}
            </>
          )}
          {team && (
            <>
              <h3>Existing project permissions</h3>
              <p>
                Project permissions also control read-only archives from
                disconnected machines. Editing permissions never reconnects or
                restores a revoked machine. Workspace owners retain project
                access.
              </p>
              {!bindings.length && (
                <p>
                  No project bindings are available for your current
                  permissions.
                </p>
              )}
              {owner ? (
                <>
                  <label>
                    Existing project binding
                    <select
                      aria-label="Existing project binding"
                      value={bindingId}
                      onChange={(e) => {
                        const binding = bindings.find(
                          (item) => item.id === e.target.value,
                        );
                        const saved = binding ? boundMembers(binding) : null;
                        setBindingId(e.target.value);
                        setPolicyMembers(
                          (saved || []).filter((id) =>
                            members.some((member) => member.account === id),
                          ),
                        );
                        setPolicyScope(
                          saved === null
                            ? "unknown"
                            : saved.length
                              ? "selected"
                              : "all",
                        );
                      }}
                    >
                      <option value="">Choose an existing project</option>
                      {bindings.map((binding) => (
                        <option key={binding.id} value={binding.id}>
                          {machines.find(
                            (machine) => machine.id === binding.worker,
                          )?.name || "Disconnected machine"}
                          : {binding.path}
                        </option>
                      ))}
                    </select>
                  </label>
                  {selectedBinding && (
                    <>
                      {!machines.some(
                        (machine) => machine.id === selectedBinding.worker,
                      ) && (
                        <p>
                          This machine is disconnected. These permissions govern
                          its archived receipts only.
                        </p>
                      )}
                      <label>
                        Project access
                        <select
                          aria-label="Existing project access"
                          value={policyScope}
                          onChange={(e) =>
                            editPolicy(e.target.value, policyMembers)
                          }
                        >
                          <option value="unknown" disabled>
                            Choose project access
                          </option>
                          <option value="all">All workspace members</option>
                          <option value="selected">
                            Selected current members
                          </option>
                        </select>
                      </label>
                      {policyScope === "selected" &&
                        members.map((member) => (
                          <label className="member-choice" key={member.account}>
                            <input
                              type="checkbox"
                              aria-label={`Project access for ${member.name || member.login}`}
                              checked={policyMembers.includes(member.account)}
                              onChange={(e) =>
                                editPolicy(
                                  "selected",
                                  e.target.checked
                                    ? [...policyMembers, member.account]
                                    : policyMembers.filter(
                                        (id) => id !== member.account,
                                      ),
                                )
                              }
                            />
                            {member.name || member.login}
                          </label>
                        ))}
                      {policyScope === "selected" && !policyMembers.length && (
                        <p>
                          Select at least one current member. Choose All
                          workspace members explicitly to open access.
                        </p>
                      )}
                      <button
                        disabled={
                          busy ||
                          policyScope === "unknown" ||
                          (policyScope === "selected" && !policyMembers.length)
                        }
                        onClick={() => void savePolicy()}
                      >
                        Save existing project permissions
                      </button>
                    </>
                  )}
                </>
              ) : (
                bindings.map((binding) => (
                  <p key={binding.id}>
                    {binding.path} ·{" "}
                    {boundMembers(binding)?.length === 0
                      ? "All workspace members"
                      : "Selected workspace members"}{" "}
                    · Read-only policy
                  </p>
                ))
              )}
            </>
          )}
          {owner && (
            <>
              <h3 tabIndex={-1} data-workspace-section="projects">
                Approved project
              </h3>
              <label>
                Worker and project
                <select
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                >
                  <option value="">Choose an approved project</option>
                  {projects.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.name}: {p.path}
                    </option>
                  ))}
                </select>
              </label>
              {team && (
                <>
                  <p>
                    Allow all workspace members, or select the people who can
                    access this project.
                  </p>
                  {members.map((m) => (
                    <label className="member-choice" key={m.account}>
                      <input
                        type="checkbox"
                        checked={permittedMembers.includes(m.account)}
                        onChange={(e) =>
                          setPermittedMembers((a) =>
                            e.target.checked
                              ? [...a, m.account]
                              : a.filter((id) => id !== m.account),
                          )
                        }
                      />
                      {m.name || m.login}
                    </label>
                  ))}
                  <button
                    disabled={!selectedProject}
                    onClick={() =>
                      void run(async () => {
                        const bound = await relayApi<ProjectBinding[]>(
                          "/workspaces/projects",
                          {
                            method: "POST",
                            body: JSON.stringify({
                              worker: selectedProject!.worker,
                              path: selectedProject!.path,
                              members: permittedMembers,
                            }),
                          },
                        );
                        setBindings(bound);
                        setNotice("Project policy saved.");
                      })
                    }
                  >
                    Bind team project
                  </button>
                </>
              )}
              <h3 tabIndex={-1} data-workspace-section="github">
                GitHub delivery
              </h3>
              <p>
                Connect GitHub delivery from an approved project in
                Repositories. GitHub sign-in and delivery authorization are
                separate.
              </p>
              {onRepositories && (
                <button
                  disabled={!machines.length}
                  onClick={() => {
                    closePanel(false);
                    onRepositories();
                  }}
                >
                  Open repositories
                </button>
              )}
              {!machines.length && (
                <p>Pair a machine with an approved project folder first.</p>
              )}
            </>
          )}
        </fieldset>
      </div>
    </details>
  );
}
