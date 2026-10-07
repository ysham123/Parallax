import { useEffect, useState } from "react";
import { ProviderMark } from "./Brand";
import { Mark, ThemeToggle } from "./PublicChrome";
import {
  REPOSITORY,
  signInErrorMessage,
  type AuthConfig,
} from "./session";
import "./public.css";

const PROVIDERS = [
  ["codex", "Codex"],
  ["claude", "Claude Code"],
  ["grok", "Grok Build"],
  ["antigravity", "Antigravity"],
] as const;

type Node = {
  id: string;
  provider: (typeof PROVIDERS)[number][0];
  role: string;
  name: string;
  x: number;
  y: number;
};

// An illustration of the graph Studio draws for a run. It shows roles, not activity.
const NODES: Node[] = [
  { id: "lead", provider: "codex", role: "Coordinator", name: "Codex", x: 17, y: 50 },
  { id: "build-a", provider: "claude", role: "Implementer", name: "Claude Code", x: 53, y: 22 },
  { id: "build-b", provider: "antigravity", role: "Implementer", name: "Antigravity", x: 53, y: 78 },
  { id: "review", provider: "grok", role: "Reviewer", name: "Grok Build", x: 85, y: 50 },
];
const EDGES: [string, string, "assign" | "review"][] = [
  ["lead", "build-a", "assign"],
  ["lead", "build-b", "assign"],
  ["build-a", "review", "review"],
  ["build-b", "review", "review"],
];

function GraphPreview() {
  const at = (id: string) => NODES.find((node) => node.id === id)!;
  return (
    <figure className="pub-graph">
      <div
        className="pub-graph-canvas"
        role="img"
        aria-label="Example team graph: a Codex coordinator assigns work to Claude Code and Antigravity, and Grok Build reviews both changes independently."
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {EDGES.map(([from, to, kind]) => {
            const a = at(from),
              b = at(to);
            const mid = (a.x + b.x) / 2;
            return (
              <path
                key={from + to}
                className={`pub-edge ${kind}`}
                d={`M ${a.x} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x} ${b.y}`}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
        {NODES.map((node) => (
          <div
            key={node.id}
            className="pub-node"
            style={{ left: `${node.x}%`, top: `${node.y}%` }}
            aria-hidden="true"
          >
            <ProviderMark provider={node.provider} size={22} />
            <span>
              <small>{node.role}</small>
              {node.name}
            </span>
          </div>
        ))}
      </div>
      <figcaption>
        <span>
          <i className="assign" /> Assigns work
        </span>
        <span>
          <i className="review" /> Independent review
        </span>
        <span className="pub-graph-note">Illustration</span>
      </figcaption>
    </figure>
  );
}

export default function PublicEntry({
  config,
  error,
  notice,
}: {
  config: AuthConfig | null;
  error: string | null;
  notice?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(error ? signInErrorMessage(error) : "");
  useEffect(() => {
    if (error) setFailure(signInErrorMessage(error));
  }, [error]);
  // Returning from GitHub with the Back button restores this page from the back-forward cache.
  useEffect(() => {
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted) setBusy(false);
    };
    window.addEventListener("pageshow", restore);
    return () => window.removeEventListener("pageshow", restore);
  }, []);
  const available = config?.github === true;

  async function signIn() {
    setBusy(true);
    setFailure("");
    try {
      const response = await fetch("/api/auth/github/start", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.url !== "string")
        throw new Error(
          signInErrorMessage(typeof body.detail === "string" ? body.detail : "failed"),
        );
      const destination = new URL(body.url);
      if (destination.origin !== "https://github.com")
        throw new Error(signInErrorMessage("failed"));
      window.location.assign(destination.href);
    } catch (problem) {
      setFailure(problem instanceof Error ? problem.message : signInErrorMessage("failed"));
      setBusy(false);
    }
  }

  const signInButton = (label: string, className: string) => (
    <button
      className={className}
      onClick={() => void signIn()}
      disabled={busy || !available}
      aria-describedby={!available ? "sign-in-unavailable" : undefined}
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path
          fill="currentColor"
          d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
        />
      </svg>
      {busy ? "Opening GitHub…" : label}
    </button>
  );

  return (
    <div className="pub-page">
      <a className="skip-link" href="#public-main">
        Skip to content
      </a>
      <header className="pub-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark />
          Parallax
        </a>
        <nav aria-label="Site">
          <a href={`${REPOSITORY}#readme`}>Docs</a>
          <a href={REPOSITORY}>GitHub</a>
          <ThemeToggle />
          {signInButton("Sign in", "pub-signin-link")}
        </nav>
      </header>

      <main id="public-main" tabIndex={-1}>
        <section className="pub-hero" aria-labelledby="hero-title">
          <div className="pub-hero-copy">
            <p className="pub-eyebrow">Verified coding teams</p>
            <h1 id="hero-title">
              Many perspectives.
              <br />
              One verified result.
            </h1>
            <p className="pub-lead">
              Parallax coordinates Codex, Claude Code, Grok Build, and Antigravity on a machine you
              control. Follow each agent in a live graph, then review the evidence before a change
              reaches your project.
            </p>
            {(failure || notice) && (
              <p className="pub-alert" role="alert">
                {failure || notice}
              </p>
            )}
            <div className="pub-actions">
              {signInButton("Continue with GitHub", "pub-primary")}
              <a className="pub-secondary" href="#how">
                How it works
              </a>
            </div>
            <p className="pub-fineprint" id="sign-in-unavailable">
              {config === null
                ? "Checking sign-in availability…"
                : available
                  ? config.signup === "open"
                    ? "Parallax reads only your public GitHub profile. It cannot see your repositories."
                    : config.signup === "allowlist"
                      ? "Invite only during the developer alpha. Parallax reads only your public GitHub profile."
                      : "New accounts are closed right now. Existing accounts can still sign in."
                  : "GitHub sign-in is not configured on this deployment yet. You can still run Parallax entirely on your machine."}
            </p>
            <ul className="pub-providers" aria-label="Supported agents">
              {PROVIDERS.map(([id, name]) => (
                <li key={id}>
                  <ProviderMark provider={id} size={20} />
                  {name}
                </li>
              ))}
            </ul>
          </div>
          <GraphPreview />
        </section>

        <section className="pub-section" id="how" aria-labelledby="how-title">
          <h2 id="how-title">How it works</h2>
          <ol className="pub-steps">
            <li>
              <span>01</span>
              <h3>Sign in</h3>
              <p>
                Your GitHub account opens a private workspace. Other accounts cannot see or
                control your machines, runs, or evidence.
              </p>
            </li>
            <li>
              <span>02</span>
              <h3>Connect your machine</h3>
              <p>
                Run one command next to the project you approve. The worker connects outward over
                HTTPS and uses the CLIs you are already signed in to.
              </p>
            </li>
            <li>
              <span>03</span>
              <h3>Run and review</h3>
              <p>
                Choose a coordinator, models, and effort. Inspect assignments, independent reviews,
                and checks, then download the verification record and patch.
              </p>
            </li>
          </ol>
        </section>

        <section className="pub-section" aria-labelledby="data-title">
          <h2 id="data-title">Where your work runs</h2>
          <div className="pub-columns">
            <div>
              <h3>On your machine</h3>
              <ul>
                <li>Project files, worktrees, and integration</li>
                <li>CLI sign-ins and API keys</li>
                <li>Agent processes and project checks</li>
              </ul>
            </div>
            <div>
              <h3>In your workspace</h3>
              <ul>
                <li>Run results, diffs, check output, and ordered events, mirrored for the graph</li>
                <li>Machine names and approved project paths</li>
                <li>Your GitHub ID, username, display name, avatar URL, and sign-in times</li>
              </ul>
            </div>
            <div>
              <h3>Not available yet</h3>
              <ul>
                <li>Running agents on Parallax servers. New workspaces use machines you connect.</li>
                <li>Shared team workspaces</li>
              </ul>
            </div>
          </div>
          <p className="pub-fineprint">
            Prompts and relevant project content go to the inference providers you choose. The
            operator of this deployment administers its hosted data. Deleting your account removes
            your workspace, its machines, and mirrored evidence.
          </p>
        </section>

        <section className="pub-section pub-local" aria-labelledby="local-title">
          <div>
            <h2 id="local-title">Prefer fully local?</h2>
            <p>
              Install the Codex plugin and open Studio on your own computer. Nothing is mirrored and
              no account is needed.
            </p>
          </div>
          <a className="pub-secondary" href={`${REPOSITORY}#install`}>
            Local install guide
          </a>
        </section>
      </main>

      <footer className="pub-footer">
        <span>Parallax 1.1 · Developer alpha · MIT</span>
        <a href={REPOSITORY}>Source</a>
      </footer>
    </div>
  );
}
