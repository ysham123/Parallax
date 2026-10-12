import { useCallback, useEffect, useRef, useState } from "react";
import App from "./App";
import { onUnauthorized, setApiExecutor, messageOf } from "./api";
import { WorkspaceControls } from "./WorkspaceControls";
import { ExecutionMachines } from "./ExecutionMachines";
import { ArchivedHistory } from "./ArchivedHistory";
import Onboarding from "./Onboarding";
import OperatorGate from "./OperatorGate";
import PublicEntry from "./PublicEntry";
import PublicSite from "./PublicSite";
import { publicWebsite } from "./entry-routing";
import Auth, { type AuthMode } from "./Auth";
import Legal from "./Legal";
import OAuthConsent, { ConnectedApps } from "./OAuthConsent";
import {
  AccountMenu,
  DeleteAccountDialog,
  Mark,
  applyStoredTheme,
} from "./PublicChrome";
import {
  HOSTED_EXECUTOR,
  accountName,
  chooseMachine,
  deletionConfirmation,
  executorKey,
  forgetMachines,
  invitationToken,
  rememberInvitation,
  legalPage,
  signInError,
  storedMachine,
  writeStored,
  type AuthConfig,
  type ExecutionMachine,
  type Session,
} from "./session";
import "./hosted.css";
import "./public.css";
import {
  parseReviewTarget,
  resolveReviewEntry,
  type ReviewSpace,
  type ReviewTarget,
} from "./review-link";
import {
  githubReturn,
  clearGitHubReturn,
  type GitHubProject,
} from "./github-connection-state";

type View =
  | { kind: "checking" }
  | { kind: "signed-out"; notice?: string }
  | { kind: "unavailable" }
  | { kind: "ready"; session: Session };

const OPERATOR_SESSION: Session["workspace"] = {
  id: "owner",
  name: "Operator workspace",
  kind: "operator",
  hosted_execution: true,
};

/** Accept older runtimes, whose session response only reported that a session exists. */
function normalize(value: Partial<Session>): Session {
  if (value.workspace && value.auth) return value as Session;
  return {
    ok: true,
    mode: "hosted",
    auth: "operator",
    account: null,
    workspace: OPERATOR_SESSION,
  };
}

export default function CloudApp() {
  if (location.pathname === "/oauth/consent") return <OAuthConsent />;
  if (location.pathname === "/connections") return <ConnectedApps />;
  // Policy and support pages are static and never wait on the runtime or a session.
  const page = legalPage(location.pathname);
  if (page) return <Legal page={page} />;
  return publicWebsite(location.pathname, location.search) ? (
    <PublicSite hosted />
  ) : (
    <CloudWorkspace />
  );
}

function CloudWorkspace() {
  useEffect(() => {
    const invitation = invitationToken(location.search);
    if (invitation) rememberInvitation(invitation);
  }, []);
  const [view, setView] = useState<View>({ kind: "checking" });
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [machines, setMachines] = useState<ExecutionMachine[]>([]);
  const [machinesLoaded, setMachinesLoaded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [machineDialogRequest, setMachineDialogRequest] = useState(0);
  const [workspaceSettingsRequest, setWorkspaceSettingsRequest] = useState<{
    scope: string;
    sequence: number;
    section: "workspace" | "projects" | "github";
  }>();
  const [repositoryRequest, setRepositoryRequest] = useState<{
    scope: string;
    sequence: number;
    target?: GitHubProject;
  }>();
  const returnedGitHub = useRef(false);
  // Set while a workspace with no machines is onboarding, so a newly paired machine is
  // announced in place and Studio opens only when the user chooses it.
  const [onboarding, setOnboarding] = useState(false);
  const [error, setError] = useState("");
  const [authError] = useState(() => signInError(location.search));
  const operatorRoute = location.pathname === "/operator";
  const authRoute = (["signup", "login", "forgot", "reset"] as AuthMode[]).find(
    (mode) => location.pathname === `/${mode}`,
  );
  const session = view.kind === "ready" ? view.session : null;
  const workspace = session?.workspace.id || "";
  const hosted = session?.workspace.hosted_execution === true;
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const scope = session
    ? `${session.account?.id || session.auth}:${workspace}:${session.workspace.role || ""}`
    : "";
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const sessionRequest = useRef(0);
  const machinesRequest = useRef(0);
  // The execution target is derived on every render: the explicit or remembered choice for
  // this workspace while it still exists, otherwise a connected machine. Personal
  // workspaces never fall back to the hosted runtime.
  const resolved =
    workspace && machinesLoaded
      ? chooseMachine(machines, selected ?? storedMachine(workspace), hosted)
      : null;
  // Tracks the view outside React state so late responses can be ignored after an intentional exit.
  const viewRef = useRef<View["kind"]>(view.kind);
  viewRef.current = view.kind;
  const exiting = useRef(false);

  useEffect(() => {
    applyStoredTheme();
    if (authError) window.history.replaceState(null, "", location.pathname);
  }, [authError]);

  const endSession = useCallback((notice?: string) => {
    sessionRequest.current += 1;
    machinesRequest.current += 1;
    viewRef.current = "signed-out";
    forgetMachines();
    setApiExecutor(null);
    setMachines([]);
    setMachinesLoaded(false);
    setSelected(null);
    setOnboarding(false);
    setView({ kind: "signed-out", notice });
  }, []);

  /** `background` checks run while Studio is open: they end or switch the session, but a transient
   *  failure leaves Studio as it is for the next poll or focus to retry. */
  const checkSession = useCallback(
    async (background = false) => {
      const request = ++sessionRequest.current;
      try {
        const response = await fetch("/api/session", {
          credentials: "same-origin",
        });
        if (request !== sessionRequest.current || exiting.current) return;
        if (background && (viewRef.current !== "ready" || exiting.current))
          return;
        if (response.status === 401) {
          if (background)
            return endSession(
              "Your session has ended. Sign in again to continue.",
            );
          return setView({ kind: "signed-out" });
        }
        if (!response.ok) throw new Error(String(response.status));
        const next = normalize(await response.json());
        if (request !== sessionRequest.current || exiting.current) return;
        if (background && (viewRef.current !== "ready" || exiting.current))
          return;
        exiting.current = false;
        const nextScope = `${next.account?.id || next.auth}:${next.workspace.id}:${next.workspace.role || ""}`;
        if (scopeRef.current && scopeRef.current !== nextScope) {
          // A different account now owns this browser's session: drop every trace of the previous one.
          setApiExecutor(null);
          setMachines([]);
          setMachinesLoaded(false);
          setSelected(null);
          setDeleting(false);
          setOnboarding(false);
        }
        setView({ kind: "ready", session: next });
        if (
          ["/operator", "/signup", "/login", "/forgot", "/reset"].includes(
            location.pathname,
          )
        )
          window.history.replaceState(null, "", "/studio");
      } catch {
        if (request !== sessionRequest.current || exiting.current) return;
        if (background) return;
        // The public page never dead-ends on the runtime; visitors keep the plugin install path.
        setView(
          location.pathname === "/operator"
            ? { kind: "unavailable" }
            : {
                kind: "signed-out",
                notice:
                  "Hosted workspaces are unavailable right now. The Claude Code and Codex plugins work as usual.",
              },
        );
      }
    },
    [endSession],
  );

  useEffect(() => {
    void checkSession();
    onUnauthorized(() => {
      // A poll that lands after an intentional sign-out or deletion must not replace its message.
      if (viewRef.current === "ready" && !exiting.current)
        endSession("Your session has ended. Sign in again to continue.");
    });
    return () => onUnauthorized(null);
  }, [checkSession, endSession]);

  // Another tab may have signed out or switched accounts; re-check when this tab returns.
  useEffect(() => {
    const recheck = () => {
      if (
        document.visibilityState === "visible" &&
        viewRef.current === "ready" &&
        !exiting.current
      )
        void checkSession(true);
    };
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("focus", recheck);
    const timer = window.setInterval(recheck, 15000);
    return () => {
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("focus", recheck);
      window.clearInterval(timer);
    };
  }, [checkSession]);

  useEffect(() => {
    if (view.kind !== "signed-out" || config) return;
    fetch("/api/auth/config", { credentials: "same-origin" })
      .then(async (response) =>
        setConfig(
          response.ok
            ? await response.json()
            : { github: false, signup: "closed" },
        ),
      )
      .catch(() => setConfig({ github: false, signup: "closed" }));
  }, [view.kind, config]);

  const refreshMachines = useCallback(async () => {
    if (exiting.current) return;
    const requestedScope = scopeRef.current;
    const requestedWorkspace = workspaceRef.current;
    const request = ++machinesRequest.current;
    const current = () =>
      request === machinesRequest.current &&
      requestedScope === scopeRef.current &&
      viewRef.current === "ready" &&
      !exiting.current;
    try {
      const response = await fetch("/api/executors", {
        credentials: "same-origin",
      });
      if (!current()) return;
      if (response.status === 401) {
        if (viewRef.current === "ready" && !exiting.current)
          endSession("Your session has ended. Sign in again to continue.");
        return;
      }
      if (!response.ok)
        throw new Error("Machines could not be loaded. Retrying.");
      const scope = response.headers.get("X-Parallax-Workspace");
      if (scope && scope !== requestedWorkspace) {
        // The cookie now belongs to a different workspace (another tab switched accounts).
        void checkSession(true);
        return;
      }
      const rows = (await response.json()) as ExecutionMachine[];
      if (!current()) return;
      setMachines(rows);
      setMachinesLoaded(true);
      setError("");
    } catch (failure) {
      if (current()) setError(messageOf(failure));
    }
  }, [checkSession, endSession]);

  useEffect(() => {
    if (!workspace) return;
    void refreshMachines();
    const timer = window.setInterval(() => void refreshMachines(), 4000);
    return () => window.clearInterval(timer);
  }, [scope, refreshMachines]);

  useEffect(() => {
    if (workspace && machinesLoaded)
      writeStored(executorKey(workspace), resolved);
  }, [workspace, machinesLoaded, resolved]);

  useEffect(() => {
    if (machinesLoaded && resolved === null) setOnboarding(true);
  }, [machinesLoaded, resolved]);

  function select(id: string) {
    writeStored(executorKey(workspace), id);
    setSelected(id);
  }

  // A review link is held until the person explicitly enters its workspace and machine.
  const [reviewTarget, setReviewTarget] = useState<ReviewTarget | null>(() =>
    parseReviewTarget(location.hash),
  );
  const [reviewSpaces, setReviewSpaces] = useState<{
    scope: string;
    spaces: ReviewSpace[] | null;
    error: string;
  } | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewOpened, setReviewOpened] = useState(0);
  useEffect(() => {
    // A link pasted into an open Studio tab changes only the hash.
    const follow = () => {
      const next = parseReviewTarget(location.hash);
      if (next) {
        setReviewSpaces(null);
        setReviewTarget(next);
      }
    };
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const reviewEntry =
    reviewTarget && session
      ? resolveReviewEntry(
          reviewTarget,
          session.workspace.id,
          reviewSpaces?.scope === scope ? reviewSpaces.spaces : null,
          machinesLoaded ? machines : null,
        )
      : null;
  const leaveReview = useCallback(() => {
    setReviewTarget(null);
    window.history.replaceState(null, "", "/studio");
  }, []);
  useEffect(() => {
    if (!reviewTarget || !session || !scope) return;
    if (session.workspace.id.toLowerCase() === reviewTarget.workspace) return;
    if (
      reviewSpaces?.scope === scope &&
      (reviewSpaces.spaces || reviewSpaces.error)
    )
      return;
    const requested = scope;
    fetch("/api/workspaces", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        const rows = (await response.json()) as ReviewSpace[];
        if (scopeRef.current === requested)
          setReviewSpaces({
            scope: requested,
            spaces: Array.isArray(rows) ? rows : [],
            error: "",
          });
      })
      .catch(() => {
        if (scopeRef.current === requested)
          setReviewSpaces({
            scope: requested,
            spaces: null,
            error: "Your workspaces could not be loaded.",
          });
      });
  }, [reviewTarget, session, scope, reviewSpaces]);
  useEffect(() => {
    if (reviewEntry?.kind !== "open") return;
    select(reviewEntry.worker);
    // Workflows opens an exact #task on its first history load, including tasks beyond the latest page.
    window.history.replaceState(null, "", `/studio#task=${reviewEntry.task}`);
    // A fresh Studio mount reads the exact task even when this machine was already open.
    setReviewOpened((value) => value + 1);
    setReviewTarget(null);
  }, [
    reviewEntry?.kind,
    reviewEntry?.kind === "open" ? reviewEntry.worker : "",
  ]);
  async function enterReviewWorkspace(space: ReviewSpace) {
    setReviewBusy(true);
    try {
      const response = await fetch(
        `/api/workspaces/${encodeURIComponent(space.id)}/switch`,
        { method: "POST", credentials: "same-origin" },
      );
      if (!response.ok) throw new Error(String(response.status));
      await checkSession();
    } catch {
      setReviewSpaces({
        scope,
        spaces: null,
        error: `Studio could not switch to ${space.name}. Try again.`,
      });
    } finally {
      setReviewBusy(false);
    }
  }

  useEffect(() => {
    if (
      returnedGitHub.current ||
      !session?.account?.id ||
      !machinesLoaded ||
      new URLSearchParams(location.search).get("github_connected") !== "1"
    )
      return;
    returnedGitHub.current = true;
    const saved = githubReturn({
      actor: session.account.id,
      workspace: session.workspace.id,
    });
    if (!saved) return;
    clearGitHubReturn();
    const machine = machines.find(
      (value) =>
        value.id === saved.target.worker &&
        value.online &&
        value.workspaces.includes(saved.target.path),
    );
    if (
      !machine ||
      (session.workspace.kind === "team" && session.workspace.role !== "owner")
    ) {
      setError(
        "GitHub authorization returned. Reconnect the approved machine or ask an Owner to continue from Repositories.",
      );
      return;
    }
    select(machine.id);
    setRepositoryRequest((previous) => ({
      scope,
      sequence: (previous?.sequence || 0) + 1,
      target: saved.target,
    }));
    window.history.replaceState(null, "", "/studio");
  }, [scope, machinesLoaded, machines, session]);

  async function signOut() {
    exiting.current = true;
    let response: Response;
    try {
      response = await fetch("/api/session", {
        method: "DELETE",
        credentials: "same-origin",
      });
    } catch {
      exiting.current = false;
      throw new Error(
        "Sign-out did not reach Parallax. Check your connection and try again.",
      );
    }
    // Only a confirmed revocation (or an already ended session) counts as signed out.
    if (!response.ok && response.status !== 401) {
      exiting.current = false;
      throw new Error("Sign-out failed. Try again.");
    }
    endSession();
  }

  async function deleteAccount() {
    const login =
      view.kind === "ready" && view.session.account
        ? deletionConfirmation(view.session.account)
        : "";
    exiting.current = true;
    const response = await fetch(
      "/api/account?confirm=" + encodeURIComponent(login),
      {
        method: "DELETE",
        credentials: "same-origin",
      },
    ).catch(() => null);
    if (!response || !response.ok) {
      exiting.current = false;
      const body = response ? await response.json().catch(() => ({})) : {};
      if (response?.status === 409) void checkSession(true);
      throw new Error(
        typeof body.detail === "string"
          ? body.detail
          : "The account could not be deleted. Try again.",
      );
    }
    setDeleting(false);
    endSession("Your account, workspace, and mirrored evidence were deleted.");
  }

  if (view.kind === "checking")
    return (
      <div className="pub-splash" role="status" aria-label="Opening Parallax">
        <Mark size={30} />
      </div>
    );

  if (view.kind === "unavailable")
    return (
      <div className="pub-splash">
        <Mark size={30} />
        <p role="alert">Parallax could not reach its runtime.</p>
        <button
          type="button"
          className="pub-secondary"
          onClick={() => void checkSession()}
        >
          Retry
        </button>
      </div>
    );

  if (view.kind === "signed-out")
    return operatorRoute ? (
      <OperatorGate onSignedIn={() => void checkSession()} />
    ) : authRoute ? (
      <Auth
        mode={authRoute}
        config={config}
        error={authError}
        onSignedIn={() => void checkSession()}
      />
    ) : (
      <PublicEntry config={config} error={authError} notice={view.notice} />
    );

  const active = view.session;
  const account = (
    <>
      <WorkspaceControls
        key={scope}
        session={active}
        machines={machines}
        onSwitch={() => void checkSession(true)}
        onRepositories={() =>
          setRepositoryRequest((previous) => ({
            scope,
            sequence: (previous?.sequence || 0) + 1,
          }))
        }
        openRequest={
          workspaceSettingsRequest?.scope === scope
            ? workspaceSettingsRequest
            : undefined
        }
      />
      <AccountMenu
        session={active}
        onSignOut={signOut}
        onDelete={() => setDeleting(true)}
      />
    </>
  );
  const dialog = deleting && active.account && (
    <DeleteAccountDialog
      login={deletionConfirmation(active.account)}
      provider={active.account.provider}
      onCancel={() => setDeleting(false)}
      onConfirm={deleteAccount}
    />
  );

  if (reviewTarget && reviewEntry?.kind === "open")
    return (
      <div className="pub-splash" role="status" aria-label="Opening the review">
        <Mark size={30} />
      </div>
    );
  if (reviewTarget && reviewEntry && reviewEntry.kind !== "open")
    return (
      <div className="pub-page review-entry-page">
        <header className="pub-header">
          <a className="pub-brand" href="/" aria-label="Parallax home">
            <Mark size={22} />
            Parallax
          </a>
        </header>
        <main className="review-entry" aria-labelledby="review-entry-title">
          {reviewEntry.kind === "checking" ? (
            <>
              <h1 id="review-entry-title">Opening a review</h1>
              {reviewSpaces?.scope === scope && reviewSpaces.error ? (
                <>
                  <p role="alert">{reviewSpaces.error}</p>
                  <div className="review-entry-actions">
                    <button
                      type="button"
                      className="pub-primary"
                      onClick={() => setReviewSpaces(null)}
                    >
                      Try again
                    </button>
                    <button
                      type="button"
                      className="pub-secondary"
                      onClick={leaveReview}
                    >
                      Open Studio instead
                    </button>
                  </div>
                </>
              ) : (
                <p role="status">
                  Checking which workspace this review belongs to…
                </p>
              )}
            </>
          ) : reviewEntry.kind === "switch" ? (
            <>
              <h1 id="review-entry-title">
                Review in {reviewEntry.space.name}
              </h1>
              <p>
                You are in{" "}
                {active.workspace.kind === "team"
                  ? active.workspace.name
                  : "your personal workspace"}
                . This review belongs to {reviewEntry.space.name}, where your
                role is {reviewEntry.space.role || "member"}. Switching changes
                the workspace for this browser. Nothing is approved or run.
              </p>
              <div className="review-entry-actions">
                <button
                  type="button"
                  className="pub-primary"
                  disabled={reviewBusy}
                  onClick={() => void enterReviewWorkspace(reviewEntry.space)}
                >
                  {reviewBusy
                    ? "Switching…"
                    : `Switch to ${reviewEntry.space.name}`}
                </button>
                <button
                  type="button"
                  className="pub-secondary"
                  disabled={reviewBusy}
                  onClick={leaveReview}
                >
                  {active.workspace.kind === "team"
                    ? `Stay in ${active.workspace.name}`
                    : "Stay in my workspace"}
                </button>
              </div>
            </>
          ) : (
            <>
              <h1 id="review-entry-title">This review link is unavailable</h1>
              <p>
                {reviewEntry.reason === "workspace"
                  ? "It belongs to a workspace your account is not a member of, or your membership was removed. Ask the person who shared it to check your access."
                  : "The machine that holds this task is not available to you. It may have been disconnected, or your project access changed."}
              </p>
              <div className="review-entry-actions">
                <button
                  type="button"
                  className="pub-primary"
                  onClick={leaveReview}
                >
                  Open Studio
                </button>
              </div>
            </>
          )}
        </main>
      </div>
    );

  if (!machinesLoaded)
    return (
      <div
        className="pub-splash"
        role="status"
        aria-label="Opening your workspace"
      >
        <Mark size={30} />
        {error && (
          <>
            <p role="alert">{error}</p>
            <button
              type="button"
              className="pub-secondary"
              onClick={() => void refreshMachines()}
            >
              Retry
            </button>
          </>
        )}
      </div>
    );

  if (resolved === null || onboarding)
    return (
      <>
        <Onboarding
          workspaceName={
            active.workspace.kind === "team" || !active.account
              ? active.workspace.name
              : accountName(active.account)
          }
          machines={machines}
          canManageMachines={
            active.workspace.kind !== "team" ||
            active.workspace.role === "owner"
          }
          loading={!machinesLoaded}
          account={account}
          onOpen={(id) => {
            setOnboarding(false);
            select(id);
          }}
        />
        <details className="onboarding-archives" key={`archives:${scope}`}>
          <summary>Archived records from disconnected machines</summary>
          <ArchivedHistory />
        </details>
        {dialog}
      </>
    );

  // Requests made while rendering Studio go to the selected machine.
  setApiExecutor(resolved === HOSTED_EXECUTOR ? null : resolved);
  const machine = machines.find((m) => m.id === resolved);
  return (
    <>
      <App
        teamWorkspace={active.workspace.kind === "team"}
        workspaceName={active.workspace.name}
        workspaceRole={active.workspace.role}
        accountIdentity={{
          actor: active.account?.id,
          workspace: active.workspace.id,
        }}
        repositoryRequest={
          repositoryRequest?.scope === scope ? repositoryRequest : undefined
        }
        onManageWorkspace={(section) =>
          setWorkspaceSettingsRequest((previous) => ({
            scope,
            sequence: (previous?.sequence || 0) + 1,
            section,
          }))
        }
        onReconnect={() => setMachineDialogRequest((value) => value + 1)}
        key={
          reviewOpened
            ? `${scope}:${resolved}:${reviewOpened}`
            : `${scope}:${resolved}`
        }
        execution={
          resolved === HOSTED_EXECUTOR
            ? undefined
            : {
                id: resolved,
                name: machine?.name || "paired machine",
                workspace: machine?.workspaces[0],
                platform: machine?.platform,
                online: machine?.online,
                transport_status: machine?.transport_status,
                paired: true,
              }
        }
        executionControls={
          <ExecutionMachines
            reconnectSignal={machineDialogRequest}
            teamWorkspace={active.workspace.kind === "team"}
            canManageMachines={
              active.workspace.kind !== "team" ||
              active.workspace.role === "owner"
            }
            machines={machines}
            selected={resolved}
            onSelect={select}
            refresh={refreshMachines}
            hostedExecution={hosted}
          />
        }
        accountControl={account}
      />
      {dialog}
    </>
  );
}
