import { useCallback, useEffect, useRef, useState } from "react";
import App from "./App";
import { onUnauthorized, setApiExecutor, messageOf } from "./api";
import { ExecutionMachines } from "./ExecutionMachines";
import Onboarding from "./Onboarding";
import OperatorGate from "./OperatorGate";
import PublicEntry from "./PublicEntry";
import Auth, { type AuthMode } from "./Auth";
import { AccountMenu, DeleteAccountDialog, Mark, applyStoredTheme } from "./PublicChrome";
import {
  HOSTED_EXECUTOR,
  accountName,
  chooseMachine,
  deletionConfirmation,
  executorKey,
  forgetMachines,
  signInError,
  storedMachine,
  writeStored,
  type AuthConfig,
  type ExecutionMachine,
  type Session,
} from "./session";
import "./hosted.css";
import "./public.css";

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
  return { ok: true, mode: "hosted", auth: "operator", account: null, workspace: OPERATOR_SESSION };
}

export default function CloudApp() {
  const [view, setView] = useState<View>({ kind: "checking" });
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [machines, setMachines] = useState<ExecutionMachine[]>([]);
  const [machinesLoaded, setMachinesLoaded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
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
      try {
        const response = await fetch("/api/session", { credentials: "same-origin" });
        if (background && (viewRef.current !== "ready" || exiting.current)) return;
        if (response.status === 401) {
          if (background) return endSession("Your session has ended. Sign in again to continue.");
          return setView({ kind: "signed-out" });
        }
        if (!response.ok) throw new Error(String(response.status));
        const next = normalize(await response.json());
        if (background && (viewRef.current !== "ready" || exiting.current)) return;
        exiting.current = false;
        if (workspaceRef.current && workspaceRef.current !== next.workspace.id) {
          // A different account now owns this browser's session: drop every trace of the previous one.
          setApiExecutor(null);
          setMachines([]);
          setMachinesLoaded(false);
          setSelected(null);
          setDeleting(false);
          setOnboarding(false);
        }
        setView({ kind: "ready", session: next });
        if (["/operator", "/signup", "/login", "/forgot", "/reset"].includes(location.pathname))
          window.history.replaceState(null, "", "/");
      } catch {
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
      if (document.visibilityState === "visible" && viewRef.current === "ready" && !exiting.current)
        void checkSession(true);
    };
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("focus", recheck);
    return () => {
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("focus", recheck);
    };
  }, [checkSession]);

  useEffect(() => {
    if (view.kind !== "signed-out" || config) return;
    fetch("/api/auth/config", { credentials: "same-origin" })
      .then(async (response) =>
        setConfig(response.ok ? await response.json() : { github: false, signup: "closed" }),
      )
      .catch(() => setConfig({ github: false, signup: "closed" }));
  }, [view.kind, config]);

  const refreshMachines = useCallback(async () => {
    if (exiting.current) return;
    try {
      const response = await fetch("/api/executors", { credentials: "same-origin" });
      if (response.status === 401) {
        if (viewRef.current === "ready" && !exiting.current)
          endSession("Your session has ended. Sign in again to continue.");
        return;
      }
      if (!response.ok) throw new Error("Machines could not be loaded. Retrying.");
      const scope = response.headers.get("X-Parallax-Workspace");
      if (scope && scope !== workspaceRef.current) {
        // The cookie now belongs to a different workspace (another tab switched accounts).
        void checkSession(true);
        return;
      }
      setMachines((await response.json()) as ExecutionMachine[]);
      setMachinesLoaded(true);
      setError("");
    } catch (failure) {
      setError(messageOf(failure));
    }
  }, [checkSession, endSession]);

  useEffect(() => {
    if (!workspace) return;
    void refreshMachines();
    const timer = window.setInterval(() => void refreshMachines(), 4000);
    return () => window.clearInterval(timer);
  }, [workspace, refreshMachines]);

  useEffect(() => {
    if (workspace && machinesLoaded) writeStored(executorKey(workspace), resolved);
  }, [workspace, machinesLoaded, resolved]);

  useEffect(() => {
    if (machinesLoaded && resolved === null) setOnboarding(true);
  }, [machinesLoaded, resolved]);

  function select(id: string) {
    writeStored(executorKey(workspace), id);
    setSelected(id);
  }

  async function signOut() {
    exiting.current = true;
    let response: Response;
    try {
      response = await fetch("/api/session", { method: "DELETE", credentials: "same-origin" });
    } catch {
      exiting.current = false;
      throw new Error("Sign-out did not reach Parallax. Check your connection and try again.");
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
      view.kind === "ready" && view.session.account ? deletionConfirmation(view.session.account) : "";
    exiting.current = true;
    const response = await fetch("/api/account?confirm=" + encodeURIComponent(login), {
      method: "DELETE",
      credentials: "same-origin",
    }).catch(() => null);
    if (!response || !response.ok) {
      exiting.current = false;
      const body = response ? await response.json().catch(() => ({})) : {};
      if (response?.status === 409) void checkSession(true);
      throw new Error(
        typeof body.detail === "string" ? body.detail : "The account could not be deleted. Try again.",
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
        <button type="button" className="pub-secondary" onClick={() => void checkSession()}>
          Retry
        </button>
      </div>
    );

  if (view.kind === "signed-out")
    return operatorRoute ? (
      <OperatorGate onSignedIn={() => void checkSession()} />
    ) : authRoute ? (
      <Auth mode={authRoute} config={config} error={authError} onSignedIn={() => void checkSession()} />
    ) : (
      <PublicEntry config={config} error={authError} notice={view.notice} />
    );

  const active = view.session;
  const account = (
    <AccountMenu session={active} onSignOut={signOut} onDelete={() => setDeleting(true)} />
  );
  const dialog = deleting && active.account && (
    <DeleteAccountDialog
      login={deletionConfirmation(active.account)}
      provider={active.account.provider}
      onCancel={() => setDeleting(false)}
      onConfirm={deleteAccount}
    />
  );

  if (!machinesLoaded)
    return (
      <div className="pub-splash" role="status" aria-label="Opening your workspace">
        <Mark size={30} />
        {error && (
          <>
            <p role="alert">{error}</p>
            <button type="button" className="pub-secondary" onClick={() => void refreshMachines()}>
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
          workspaceName={active.account ? accountName(active.account) : active.workspace.name}
          machines={machines}
          loading={!machinesLoaded}
          account={account}
          onOpen={(id) => {
            setOnboarding(false);
            select(id);
          }}
        />
        {dialog}
      </>
    );

  // Requests made while rendering Studio go to the selected machine.
  setApiExecutor(resolved === HOSTED_EXECUTOR ? null : resolved);
  const machine = machines.find((m) => m.id === resolved);
  return (
    <>
      <App
        key={`${workspace}:${resolved}`}
        execution={
          resolved === HOSTED_EXECUTOR
            ? undefined
            : {
                name: machine?.name || "paired machine",
                workspace: machine?.workspaces[0],
                platform: machine?.platform,
                online: machine?.online,
                paired: true,
              }
        }
        executionControls={
          <ExecutionMachines
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
