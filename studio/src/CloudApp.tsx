import { useEffect, useState, type FormEvent } from "react";
import App from "./App";
import "./hosted.css";

export default function CloudApp() {
  const [state, setState] = useState<"checking" | "locked" | "ready">(
    "checking",
  );
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function check() {
    setError("");
    setState("checking");
    try {
      const response = await fetch("/api/session", {
        credentials: "same-origin",
      });
      if (response.ok && (await response.json()).ok) setState("ready");
      else {
        setState("locked");
        if (response.status !== 401)
          setError(
            "The hosted runtime is unavailable. Check the Railway service and its domain settings.",
          );
      }
    } catch {
      setState("locked");
      setError("Unable to reach the hosted runtime. Check Railway and retry.");
    }
  }
  useEffect(() => {
    void check();
  }, []);
  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: key }),
      });
      if (!response.ok)
        throw new Error(
          response.status === 401
            ? "The access key was not accepted."
            : response.status === 429
              ? "Too many attempts. Try again in one minute."
              : "Sign-in failed. Check the Railway service configuration.",
        );
      setKey("");
      setState("ready");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    setBusy(true);
    try {
      const response = await fetch("/api/session", {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Sign-out failed. Please retry.");
      setState("locked");
      setError("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-out failed.");
    } finally {
      setBusy(false);
    }
  }
  if (state === "ready")
    return (
      <>
        <App />
        <div className="cloud-session">
          <button onClick={signOut} disabled={busy}>
            Sign out of hosted workspace
          </button>
          <span role="alert">{error}</span>
        </div>
      </>
    );
  return (
    <main className="cloud-gate">
      <section className="hosted-launch" aria-labelledby="cloud-title">
        <span className="hosted-eyebrow">
          PARALLAX · DEDICATED TEAM WORKSPACE
        </span>
        <h1 id="cloud-title">Open your Studio</h1>
        <p>
          This workspace runs on your team’s Railway service. Projects and
          provider connections belong to that service.
        </p>
        {state === "checking" ? (
          <p role="status">Checking your session…</p>
        ) : (
          <form onSubmit={signIn}>
            <label htmlFor="access-key">Workspace access key</label>
            <input
              id="access-key"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              aria-describedby="access-help"
            />
            <p id="access-help" className="hosted-help">
              Ask the workspace owner for access. Your key is exchanged for a
              secure session cookie.
            </p>
            <button
              className="hosted-open"
              disabled={busy || !key}
              type="submit"
            >
              {busy ? "Signing in…" : "Open Studio"}
            </button>
          </form>
        )}
        <p role="alert" className="hosted-error">
          {error}
        </p>
        {error && (
          <button
            className="hosted-copy"
            onClick={() => void check()}
            disabled={busy}
          >
            Retry connection
          </button>
        )}
      </section>
    </main>
  );
}
