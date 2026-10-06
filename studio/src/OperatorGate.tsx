import { useState, type FormEvent } from "react";
import { Mark, ThemeToggle } from "./PublicChrome";
import "./public.css";

/** Access-key sign-in for the deployment operator. Not linked from the public entry. */
export default function OperatorGate({ onSignedIn }: { onSignedIn: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
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
            ? "That access key was not accepted."
            : response.status === 429
              ? "Too many attempts. Try again in one minute."
              : "Sign-in failed. Check the runtime configuration.",
        );
      setKey("");
      window.history.replaceState(null, "", "/");
      onSignedIn();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="pub-page">
      <header className="pub-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark />
          Parallax
        </a>
        <nav aria-label="Site">
          <ThemeToggle />
        </nav>
      </header>
      <main className="operator-main">
        <p className="pub-eyebrow">Operator access</p>
        <h1>Operator sign-in</h1>
        <p className="pub-lead">
          For the operator of this deployment. Everyone else signs in with GitHub from the{" "}
          <a href="/">home page</a>.
        </p>
        <form onSubmit={submit} className="operator-form">
          <label htmlFor="access-key">Deployment access key</label>
          <input
            id="access-key"
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            aria-describedby="access-help"
          />
          <p id="access-help" className="onb-muted">
            Exchanged for a secure session cookie. The key is never stored in the browser.
          </p>
          <button className="pub-primary" disabled={busy || !key} type="submit">
            {busy ? "Signing in…" : "Open operator workspace"}
          </button>
          {error && (
            <p role="alert" className="pub-alert">
              {error}
            </p>
          )}
        </form>
      </main>
    </div>
  );
}
