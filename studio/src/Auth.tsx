import { useEffect, useState, type FormEvent } from "react";
import { Mark, ThemeToggle } from "./PublicChrome";
import { signInErrorMessage, signInMethods, type AuthConfig } from "./session";
import "./public.css";

export type AuthMode = "signup" | "login" | "forgot" | "reset";
type Sent = { kind: "confirm" | "reset"; email: string } | null;

const PASSWORD_MIN = 10;

/** The runtime answers sign-in requests with a refusal code; anything else is a generic failure. */
async function post(path: string, body: unknown): Promise<{ ok: boolean; code?: string; data?: Record<string, unknown> }> {
  try {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) return { ok: true, data };
    const code = typeof data.detail === "string" ? data.detail : response.status === 422 ? "invalid_email" : "failed";
    return { ok: false, code };
  } catch {
    return { ok: false, code: "failed" };
  }
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

export default function Auth({
  mode: initialMode,
  config,
  error,
  onSignedIn,
}: {
  mode: AuthMode;
  config: AuthConfig | null;
  error?: string | null;
  onSignedIn: () => void;
}) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [problem, setProblem] = useState(error ? signInErrorMessage(error) : "");
  const [sent, setSent] = useState<Sent>(null);
  const methods = signInMethods(config);
  const emailEnabled = methods.includes("email");
  const oauth = methods.filter((method) => method === "github" || method === "google");
  const closed = config?.signup === "closed";
  const token = new URLSearchParams(location.search).get("token_hash") || "";

  // The page title belongs to this card only while it is shown.
  useEffect(() => {
    const previous = document.title;
    return () => {
      document.title = previous;
    };
  }, []);
  // Keep the address bar in step with the form, without reloading, so back and refresh behave.
  useEffect(() => {
    const path = `/${mode}`;
    if (location.pathname !== path) window.history.replaceState(null, "", path + (mode === "reset" ? location.search : ""));
    document.title =
      mode === "signup" ? "Create your account · Parallax" : mode === "login" ? "Log in · Parallax" : "Reset password · Parallax";
  }, [mode]);
  // Returning from GitHub or Google with the Back button restores this page from the back-forward cache.
  useEffect(() => {
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted) setBusy("");
    };
    window.addEventListener("pageshow", restore);
    return () => window.removeEventListener("pageshow", restore);
  }, []);

  function switchTo(next: AuthMode) {
    setMode(next);
    setProblem("");
    setSent(null);
    setPassword("");
    setRepeat("");
  }

  async function continueWith(provider: string) {
    setBusy(provider);
    setProblem("");
    const supabase = config?.identity === "supabase";
    const result = await post(supabase ? "/api/auth/oauth/start" : "/api/auth/github/start", supabase ? { provider } : {});
    const url = typeof result.data?.url === "string" ? result.data.url : "";
    let destination: URL | null = null;
    try {
      destination = url ? new URL(url) : null;
    } catch {
      destination = null;
    }
    if (!result.ok || !destination || destination.protocol !== "https:") {
      setProblem(signInErrorMessage(result.code || "failed"));
      setBusy("");
      return;
    }
    window.location.assign(destination.href);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setProblem("");
    if ((mode === "signup" || mode === "reset") && new TextEncoder().encode(password).length < PASSWORD_MIN) {
      setProblem(signInErrorMessage("weak_password"));
      return;
    }
    if (mode === "reset" && password !== repeat) {
      setProblem("The two passwords don't match.");
      return;
    }
    setBusy("form");
    const address = email.trim();
    const result =
      mode === "signup"
        ? await post("/api/auth/email/signup", { email: address, password, ...(name.trim() ? { name: name.trim() } : {}) })
        : mode === "login"
          ? await post("/api/auth/email/login", { email: address, password })
          : mode === "forgot"
            ? await post("/api/auth/password/forgot", { email: address })
            : await post("/api/auth/password/reset", { token_hash: token, password });
    setBusy("");
    if (!result.ok) {
      setProblem(signInErrorMessage(result.code || "failed"));
      return;
    }
    if (mode === "signup") setSent({ kind: "confirm", email: address });
    else if (mode === "forgot") setSent({ kind: "reset", email: address });
    else {
      window.history.replaceState(null, "", "/");
      onSignedIn();
    }
  }

  const heading =
    sent?.kind === "confirm"
      ? "Check your inbox"
      : sent?.kind === "reset"
        ? "Check your inbox"
        : mode === "signup"
          ? "Create your account"
          : mode === "login"
            ? "Log in to Parallax"
            : mode === "forgot"
              ? "Reset your password"
              : "Choose a new password";

  return (
    <div className="pub-page auth-page">
      <header className="pub-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark />
          Parallax
        </a>
        <nav aria-label="Site">
          <ThemeToggle />
        </nav>
      </header>
      <main className="auth-main" id="public-main" tabIndex={-1}>
        <section className="auth-card" aria-labelledby="auth-title">
          <h1 id="auth-title">{heading}</h1>
          {sent ? (
            <>
              <p className="auth-lead" role="status">
                {sent.kind === "confirm"
                  ? `We sent a confirmation link to ${sent.email}. Open it on any device to finish creating your account.`
                  : `If an account exists for ${sent.email}, we sent a link to choose a new password.`}
              </p>
              <p className="auth-note">The link works for an hour. Check spam if it doesn't arrive within a few minutes.</p>
              <button type="button" className="pub-secondary auth-wide" onClick={() => switchTo("login")}>
                Back to log in
              </button>
            </>
          ) : (
            <>
              <p className="auth-lead">
                {mode === "signup"
                  ? "A private workspace that runs coding teams on machines you connect."
                  : mode === "login"
                    ? "Welcome back."
                    : mode === "forgot"
                      ? "Enter your account's email and we'll send a link to choose a new password."
                      : "You'll be signed in once it's saved."}
              </p>
              {mode === "signup" && closed && (
                <p className="pub-alert" role="status">
                  New accounts are closed right now. Existing accounts can still log in.
                </p>
              )}
              {problem && (
                <p className="pub-alert" role="alert">
                  {problem}
                </p>
              )}
              {(mode === "signup" || mode === "login") && oauth.length > 0 && !(mode === "signup" && closed) && (
                <div className="auth-providers">
                  {oauth.map((provider) => (
                    <button
                      key={provider}
                      type="button"
                      className="pub-secondary auth-wide auth-provider"
                      onClick={() => void continueWith(provider)}
                      disabled={!!busy}
                    >
                      {provider === "github" ? <GitHubIcon /> : <GoogleIcon />}
                      {busy === provider
                        ? `Opening ${provider === "github" ? "GitHub" : "Google"}…`
                        : `Continue with ${provider === "github" ? "GitHub" : "Google"}`}
                    </button>
                  ))}
                </div>
              )}
              {emailEnabled && (mode === "signup" || mode === "login") && oauth.length > 0 && !(mode === "signup" && closed) && (
                <div className="auth-divider" role="separator">
                  <span>or</span>
                </div>
              )}
              {emailEnabled && !(mode === "signup" && closed) && (mode !== "reset" || token) && (
                <form className="auth-form" onSubmit={(event) => void submit(event)} noValidate>
                  {mode === "signup" && (
                    <label>
                      <span>Name <small>optional</small></span>
                      <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" maxLength={200} />
                    </label>
                  )}
                  {mode !== "reset" && (
                    <label>
                      <span>Email</span>
                      <input
                        type="email"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        autoComplete="email"
                        inputMode="email"
                        required
                        maxLength={320}
                      />
                    </label>
                  )}
                  {mode !== "forgot" && (
                    <label>
                      <span className="auth-label-row">
                        {mode === "reset" ? "New password" : "Password"}
                        {mode === "login" && (
                          <button type="button" className="auth-link" onClick={() => switchTo("forgot")}>
                            Forgot password?
                          </button>
                        )}
                      </span>
                      <input
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        autoComplete={mode === "login" ? "current-password" : "new-password"}
                        required
                        minLength={mode === "login" ? undefined : PASSWORD_MIN}
                        maxLength={72}
                        aria-describedby={mode === "login" ? undefined : "password-hint"}
                      />
                      {mode !== "login" && (
                        <small id="password-hint" className="auth-hint">
                          At least {PASSWORD_MIN} characters.
                        </small>
                      )}
                    </label>
                  )}
                  {mode === "reset" && (
                    <label>
                      <span>Repeat new password</span>
                      <input
                        type="password"
                        value={repeat}
                        onChange={(event) => setRepeat(event.target.value)}
                        autoComplete="new-password"
                        required
                        maxLength={72}
                      />
                    </label>
                  )}
                  <button type="submit" className="pub-primary auth-wide" disabled={!!busy}>
                    {busy === "form"
                      ? "Working…"
                      : mode === "signup"
                        ? "Create account"
                        : mode === "login"
                          ? "Log in"
                          : mode === "forgot"
                            ? "Send reset link"
                            : "Save password and sign in"}
                  </button>
                </form>
              )}
              {mode === "reset" && !token && (
                <p className="pub-alert" role="alert">
                  {signInErrorMessage("link_expired")}
                </p>
              )}
              <p className="auth-switch">
                {mode === "signup" ? (
                  <>
                    Already have an account?{" "}
                    <button type="button" className="auth-link" onClick={() => switchTo("login")}>
                      Log in
                    </button>
                  </>
                ) : mode === "login" ? (
                  closed ? null : (
                    <>
                      New to Parallax?{" "}
                      <button type="button" className="auth-link" onClick={() => switchTo("signup")}>
                        Create an account
                      </button>
                    </>
                  )
                ) : (
                  <button type="button" className="auth-link" onClick={() => switchTo("login")}>
                    Back to log in
                  </button>
                )}
              </p>
              {mode === "signup" && (
                <p className="auth-note">
                  Parallax never sees your repositories. Agents run on machines you connect, with your own provider sign-ins.
                </p>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
