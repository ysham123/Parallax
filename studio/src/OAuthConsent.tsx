import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Mark, PublicFooter, ThemeToggle } from "./PublicChrome";
import { signInErrorMessage } from "./session";
import { consentIdentifier, oauthDestination } from "./oauth";
import "./public.css";

type Details = {
  client: { id: string; name: string };
  redirect_uri: string;
  scope: string;
};
type Grant = { client: string; name: string; created: number };
type Config = { remote_mcp?: boolean; providers?: string[] };

async function api(path: string, method = "GET", body?: unknown) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => ({}));
  return { response, data };
}

function Frame({ title, children }: { title: string; children: ReactNode }) {
  useEffect(() => {
    const before = document.title;
    document.title = `${title} · Parallax`;
    return () => {
      document.title = before;
    };
  }, [title]);
  return (
    <div className="pub-page auth-page">
      <header className="pub-header">
        <a className="pub-brand" href="/">
          <Mark />
          Parallax
        </a>
        <nav aria-label="Site">
          <ThemeToggle />
        </nav>
      </header>
      <main className="auth-main">
        <section className="auth-card" aria-labelledby="consent-title">
          <h1 id="consent-title">{title}</h1>
          {children}
        </section>
      </main>
      <PublicFooter />
    </div>
  );
}

export default function OAuthConsent() {
  const [identifier] = useState(() => consentIdentifier(location.search));
  const [config, setConfig] = useState<Config | null>(null);
  const [details, setDetails] = useState<Details | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState(() => {
    const code = new URLSearchParams(location.search).get("auth_error");
    return code ? signInErrorMessage(code) : "";
  });

  async function loadDetails() {
    const { response, data } = await api(
      "/api/oauth/consent?authorization_id=" + identifier,
    );
    if (response.status === 401) {
      setDetails(null);
      return;
    }
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Unable to read this connection request.",
      );
    if (data.redirect_url) {
      location.assign(oauthDestination(data.redirect_url));
      return;
    }
    if (!data.client?.name || typeof data.scope !== "string")
      throw new Error("Invalid connection request.");
    setDetails(data as Details);
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { data } = await api("/api/auth/config");
        if (!active) return;
        setConfig(data);
        if (data.remote_mcp && identifier) await loadDetails();
      } catch {
        if (active)
          setProblem(
            "Unable to load the connection request. Try again shortly.",
          );
      } finally {
        if (active) setChecking(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [identifier]);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const { response, data } = await api("/api/oauth/password", "POST", {
        authorization_id: identifier,
        email,
        password,
      });
      setPassword("");
      if (!response.ok) throw new Error(signInErrorMessage(data.detail));
      await loadDetails();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  async function provider(name: string) {
    setBusy(true);
    setProblem("");
    try {
      const { response, data } = await api("/api/oauth/start", "POST", {
        authorization_id: identifier,
        provider: name,
      });
      if (!response.ok) throw new Error(signInErrorMessage(data.detail));
      location.assign(oauthDestination(data.url));
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Unable to sign in.");
      setBusy(false);
    }
  }

  async function decide(approve: boolean) {
    setBusy(true);
    setProblem("");
    try {
      const { response, data } = await api(
        "/api/oauth/consent?authorization_id=" + identifier,
        "POST",
        { approve },
      );
      if (!response.ok)
        throw new Error(
          response.status === 401
            ? "This sign-in expired. Reload and sign in again."
            : "Unable to complete this request. Restart the connection from your app.",
        );
      location.assign(oauthDestination(data.redirect_url));
    } catch (error) {
      setProblem(
        error instanceof Error
          ? error.message
          : "Unable to complete this request.",
      );
      setBusy(false);
    }
  }

  return (
    <Frame
      title={
        details ? `Connect ${details.client.name}?` : "Connect to Parallax"
      }
    >
      {problem && (
        <p className="pub-alert" role="alert">
          {problem}
        </p>
      )}
      {checking ? (
        <p role="status">Loading connection request…</p>
      ) : !identifier ? (
        <p className="auth-lead">
          Start this connection from ChatGPT or Codex so Parallax can verify
          which app is requesting access.
        </p>
      ) : !config?.remote_mcp ? (
        <p className="auth-lead">
          Remote app connections are not available on this deployment yet.
        </p>
      ) : details ? (
        <>
          <p className="auth-lead">
            This app will be able to use your personal Parallax workspace:
          </p>
          <ul className="consent-access">
            <li>See paired machines, approved projects, and run summaries.</li>
            <li>
              Create pairing codes and start reviews or builds using your
              providers.
            </li>
            <li>
              Stop runs. Builds can apply changes after Parallax’s verification
              gates pass.
            </li>
          </ul>
          <p className="auth-note">
            Reviews and builds use your selected AI providers and may consume
            their quota. Connect only an app you trust.
          </p>
          <p className="auth-note">
            Requested identity access: {details.scope || "account identity"}.
            Returning to {new URL(details.redirect_uri).host}.
          </p>
          <div className="auth-providers">
            <button
              className="pub-primary auth-wide"
              disabled={busy}
              onClick={() => void decide(true)}
            >
              Allow connection
            </button>
            <button
              className="pub-secondary auth-wide"
              disabled={busy}
              onClick={() => void decide(false)}
            >
              Deny
            </button>
          </div>
          <p className="auth-note">
            Revoke access at any time in{" "}
            <a href="/connections">Connected apps</a>.
          </p>
        </>
      ) : (
        <>
          <p className="auth-lead">
            Sign in to confirm the account this app can use. You’ll review its
            access before connecting.
          </p>
          <div className="auth-providers">
            {(config.providers || [])
              .filter((p) => p === "github" || p === "google")
              .map((p) => (
                <button
                  className="pub-secondary auth-wide"
                  key={p}
                  disabled={busy}
                  onClick={() => void provider(p)}
                >
                  Continue with {p === "github" ? "GitHub" : "Google"}
                </button>
              ))}
          </div>
          {(config.providers || []).includes("email") && (
            <form
              className="auth-form"
              onSubmit={(event) => void signIn(event)}
            >
              <label>
                <span>Email</span>
                <input
                  type="email"
                  autoComplete="username"
                  required
                  maxLength={320}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  maxLength={1024}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <button
                className="pub-primary auth-wide"
                disabled={busy}
                type="submit"
              >
                {busy ? "Signing in…" : "Continue"}
              </button>
            </form>
          )}
          <p className="auth-note">
            <a href="/signup" target="_blank" rel="noreferrer">
              Create an account
            </a>{" "}
            or{" "}
            <a href="/forgot" target="_blank" rel="noreferrer">
              reset your password
            </a>
            , then return here.
          </p>
        </>
      )}
    </Frame>
  );
}

export function ConnectedApps() {
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [problem, setProblem] = useState("");
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    let active = true;
    void api("/api/oauth/grants")
      .then(({ response, data }) => {
        if (!active) return;
        if (response.status === 401) setSignedOut(true);
        else if (response.ok && Array.isArray(data)) setGrants(data);
        else setProblem("Connected apps are not available on this deployment.");
      })
      .catch(() => {
        if (active) setProblem("Unable to load connected apps.");
      });
    return () => {
      active = false;
    };
  }, []);
  async function revoke(client: string) {
    setBusy(client);
    setProblem("");
    try {
      const { response } = await api(
        `/api/oauth/grants/${encodeURIComponent(client)}`,
        "DELETE",
      );
      if (!response.ok)
        throw new Error("Unable to revoke access. Sign in again and retry.");
      setGrants((current) => current?.filter((g) => g.client !== client) || []);
    } catch (error) {
      setProblem(
        error instanceof Error ? error.message : "Unable to revoke access.",
      );
    } finally {
      setBusy("");
    }
  }
  return (
    <Frame title="Connected apps">
      <p className="auth-lead">
        Revoking access blocks new requests immediately. Runs already started
        continue on your machine; stop them in Studio if needed.
      </p>
      {problem && (
        <p className="pub-alert" role="alert">
          {problem}
        </p>
      )}
      {signedOut ? (
        <p>
          <a href="/login">Sign in</a>, then return to this page.
        </p>
      ) : grants ? (
        grants.length ? (
          <ul className="consent-grants">
            {grants.map((g) => (
              <li key={g.client}>
                <span>{g.name}</span>
                <button
                  className="pub-secondary"
                  disabled={!!busy}
                  onClick={() => void revoke(g.client)}
                >
                  Revoke access
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p>No connected apps.</p>
        )
      ) : (
        !problem && <p role="status">Loading…</p>
      )}
      <a className="pub-secondary auth-wide" href="/">
        Return to Studio
      </a>
    </Frame>
  );
}
