import { useCallback, useEffect, useState } from "react";
import App from "./App";
import { onUnauthorized, relayApi, setApiExecutor, messageOf } from "./api";
import { ExecutionMachines } from "./ExecutionMachines";
import Onboarding from "./Onboarding";
import OperatorGate from "./OperatorGate";
import PublicEntry from "./PublicEntry";
import { AccountMenu, DeleteAccountDialog, Mark, applyStoredTheme } from "./PublicChrome";
import {
  HOSTED_EXECUTOR,
  chooseMachine,
  executorKey,
  forgetMachines,
  readStored,
  signInError,
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
  const [error, setError] = useState("");
  const [authError] = useState(() => signInError(location.search));
  const operatorRoute = location.pathname === "/operator";
  const session = view.kind === "ready" ? view.session : null;
  const workspace = session?.workspace.id || "";
  const hosted = session?.workspace.hosted_execution === true;
  // The execution target is derived on every render: the explicit or remembered choice for
  // this workspace while it still exists, otherwise a connected machine. Personal
  // workspaces never fall back to the hosted runtime.
  const resolved =
    workspace && machinesLoaded
      ? chooseMachine(machines, selected ?? readStored(executorKey(workspace)), hosted)
      : null;

  useEffect(() => {
    applyStoredTheme();
    if (authError) window.history.replaceState(null, "", location.pathname);
  }, [authError]);

  const endSession = useCallback((notice?: string) => {
    forgetMachines();
    setApiExecutor(null);
    setMachines([]);
    setMachinesLoaded(false);
    setSelected(null);
    setView({ kind: "signed-out", notice });
  }, []);

  const checkSession = useCallback(async () => {
    try {
      const response = await fetch("/api/session", { credentials: "same-origin" });
      if (response.status === 401) return setView({ kind: "signed-out" });
      if (!response.ok) throw new Error(String(response.status));
      setView({ kind: "ready", session: normalize(await response.json()) });
      if (location.pathname === "/operator") window.history.replaceState(null, "", "/");
    } catch {
      setView({ kind: "unavailable" });
    }
  }, []);

  useEffect(() => {
    void checkSession();
    onUnauthorized(() => endSession("Your session has ended. Sign in again to continue."));
    return () => onUnauthorized(null);
  }, [checkSession, endSession]);

  useEffect(() => {
    if (view.kind !== "signed-out" || config) return;
    fetch("/api/auth/config", { credentials: "same-origin" })
      .then(async (response) =>
        setConfig(response.ok ? await response.json() : { github: false, signup: "closed" }),
      )
      .catch(() => setConfig({ github: false, signup: "closed" }));
  }, [view.kind, config]);

  const refreshMachines = useCallback(async () => {
    try {
      const list = await relayApi<ExecutionMachine[]>("/executors");
      setMachines(list);
      setMachinesLoaded(true);
      setError("");
    } catch (failure) {
      setError(messageOf(failure));
    }
  }, []);

  useEffect(() => {
    if (!workspace) return;
    void refreshMachines();
    const timer = window.setInterval(() => void refreshMachines(), 4000);
    return () => window.clearInterval(timer);
  }, [workspace, refreshMachines]);

  useEffect(() => {
    if (workspace && machinesLoaded) writeStored(executorKey(workspace), resolved);
  }, [workspace, machinesLoaded, resolved]);

  function select(id: string) {
    writeStored(executorKey(workspace), id);
    setSelected(id);
  }

  async function signOut() {
    await fetch("/api/session", { method: "DELETE", credentials: "same-origin" }).catch(() => undefined);
    endSession();
  }

  async function deleteAccount() {
    const response = await fetch("/api/account", { method: "DELETE", credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "The account could not be deleted. Try again.");
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
    ) : (
      <PublicEntry config={config} error={authError} notice={view.notice} />
    );

  const active = view.session;
  const account = (
    <AccountMenu session={active} onSignOut={signOut} onDelete={() => setDeleting(true)} />
  );
  const dialog = deleting && active.account && (
    <DeleteAccountDialog
      login={active.account.login}
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

  if (resolved === null)
    return (
      <>
        <Onboarding
          workspaceName={active.account ? `@${active.account.login}` : active.workspace.name}
          machines={machines}
          loading={!machinesLoaded}
          account={account}
          onOpen={select}
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
