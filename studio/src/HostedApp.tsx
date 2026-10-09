import { useState, type FormEvent } from "react";
import { ProviderMark } from "./Brand";
import { localStudioUrl } from "./hosted-link";
import { legalPage } from "./session";
import Legal from "./Legal";
import OAuthConsent, { ConnectedApps } from "./OAuthConsent";
import "./hosted.css";

const repository = "https://github.com/ysham123/Parallax";
const command =
  "python3 scripts/parallax.py studio --workspace /path/to/project";

export default function HostedApp() {
  if (location.pathname === "/oauth/consent") return <OAuthConsent />;
  if (location.pathname === "/connections") return <ConnectedApps />;
  const page = legalPage(location.pathname);
  return page ? <Legal page={page} /> : <HostedEntry />;
}

function HostedEntry() {
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [light, setLight] = useState(false);
  function open(event: FormEvent) {
    event.preventDefault();
    try {
      window.location.assign(localStudioUrl(link));
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Unable to open Studio.",
      );
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setError("Select the command below and copy it to your terminal.");
    }
  }
  return (
    <div className="hosted-page">
      <header className="hosted-header">
        <a className="hosted-brand" href="/" aria-label="Parallax home">
          <svg viewBox="0 0 40 40" width="32" height="32" aria-hidden="true">
            <ellipse
              cx="20"
              cy="20"
              rx="17"
              ry="8"
              transform="rotate(-42 20 20)"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
            <circle cx="20" cy="20" r="4" fill="currentColor" />
          </svg>
          Parallax
        </a>
        <nav aria-label="Site navigation">
          <a href={`${repository}#readme`}>Documentation</a>
          <a href={repository}>GitHub ↗</a>
          <button
            className="hosted-theme"
            aria-label={light ? "Use dark mode" : "Use light mode"}
            onClick={() => {
              document.documentElement.dataset.theme = light ? "dark" : "light";
              setLight(!light);
            }}
          >
            {light ? "Dark" : "Light"}
          </button>
        </nav>
      </header>
      <main className="hosted-main">
        <div className="hosted-intro">
          <span className="hosted-eyebrow">
            VERIFIED CODING TEAMS · LOCAL EXECUTION
          </span>
          <h1>
            A coding team.
            <br />
            Your workspace.
          </h1>
          <p>
            Choose your models, follow each agent’s work, and review the
            evidence before changes reach your project.
          </p>
          <div className="hosted-providers" aria-label="Supported providers">
            {(
              [
                ["codex", "Codex"],
                ["claude", "Claude Code"],
                ["grok", "Grok Build"],
                ["antigravity", "Antigravity"],
              ] as const
            ).map(([id, name]) => (
              <span key={id}>
                <ProviderMark provider={id} size={25} />
                {name}
              </span>
            ))}
          </div>
          <div className="hosted-workflow" aria-label="Run workflow">
            <span>Plan</span>
            <span aria-hidden="true">→</span>
            <span>Build</span>
            <span aria-hidden="true">→</span>
            <span>Review</span>
            <span aria-hidden="true">→</span>
            <span>Verify</span>
          </div>
          <p className="hosted-local-note">
            Agent processes, project files, and run history stay on your
            machine. Inference uses your selected provider’s service.
          </p>
        </div>
        <section className="hosted-launch" aria-labelledby="launch-title">
          <span className="hosted-eyebrow">OPEN YOUR WORKSPACE</span>
          <h2 id="launch-title">Start in Claude Code or Codex</h2>
          <p>
            With the Parallax plugin installed, run <code>/parallax-team:studio</code> in Claude
            Code, or ask Codex:
          </p>
          <blockquote>“Open Parallax Studio for this project.”</blockquote>
          <p>
            The plugin returns an authenticated local link. Open it directly, or
            paste it here.
          </p>
          <form onSubmit={open}>
            <label htmlFor="studio-link">Local Studio URL</label>
            <input
              id="studio-link"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={link}
              onChange={(event) => {
                setLink(event.target.value);
                setError("");
              }}
              placeholder="http://127.0.0.1:…/?token=…"
              aria-describedby="link-help"
              aria-invalid={!!error}
            />
            <p id="link-help" className="hosted-help">
              This link stays in this tab. It is never uploaded or saved.
            </p>
            <button
              className="hosted-open"
              type="submit"
              disabled={!link.trim()}
            >
              Open local Studio <span aria-hidden="true">↗</span>
            </button>
            <div className="hosted-error" role="alert">
              {error}
            </div>
          </form>
          <details>
            <summary>Starting from a cloned repository?</summary>
            <p>
              From the repository folder, run this command with your project
              path:
            </p>
            <code className="hosted-command">{command}</code>
            <button className="hosted-copy" onClick={copy}>
              {copied ? "Copied" : "Copy command"}
            </button>
            <span className="hosted-help" role="status">
              {copied ? "Command copied to clipboard." : ""}
            </span>
          </details>
          <a className="hosted-install" href={`${repository}#install`}>
            Install the Parallax plugin ↗
          </a>
        </section>
      </main>
      <footer className="hosted-footer">
        <span>Parallax {__PARALLAX_VERSION__} · Studio runs locally</span>
        <nav aria-label="Legal and support">
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
          <a href="/support">Support</a>
        </nav>
      </footer>
    </div>
  );
}
