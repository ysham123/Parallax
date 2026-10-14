import { useEffect, useState, type FormEvent } from "react";
import { ProviderMark } from "./Brand";
import { Mark, ThemeToggle, applyStoredTheme } from "./PublicChrome";
import { localStudioUrl } from "./hosted-link";
import { legalPage } from "./session";
import Legal from "./Legal";
import OAuthConsent, { ConnectedApps } from "./OAuthConsent";
import PublicSite from "./PublicSite";
import { publicWebsite } from "./entry-routing";
import { PREVIEW_GUIDES, PUBLIC_RELEASE } from "./public-release";
import "./hosted.css";

const repository = "https://github.com/ysham123/Parallax";
const command =
  "python3 scripts/parallax.py studio --workspace /path/to/project";

export default function HostedApp() {
  if (location.pathname === "/oauth/consent") return <OAuthConsent />;
  if (location.pathname === "/connections") return <ConnectedApps />;
  const page = legalPage(location.pathname);
  if (page) return <Legal page={page} />;
  return publicWebsite(location.pathname, location.search) ? (
    <PublicSite />
  ) : (
    <HostedEntry />
  );
}

function HostedEntry() {
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    applyStoredTheme();
  }, []);
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
          <Mark size={22} />
          Parallax
        </a>
        <nav aria-label="Site navigation">
          <a href={`${repository}#readme`}>Documentation</a>
          <a href={repository}>GitHub ↗</a>
          <ThemeToggle />
        </nav>
      </header>
      <main className="hosted-main">
        <div className="hosted-intro">
          <span className="hosted-eyebrow">Local Studio</span>
          <h1>
            Open Studio.
            <br />
            Work from your project.
          </h1>
          <p>
            Open the private link returned by Parallax. Your project, agents and
            run history stay on your machine. No hosted account is needed.
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
          <span className="hosted-eyebrow">Open your project</span>
          <h2 id="launch-title">Start in Claude Code or Codex</h2>
          <p>
            With the public Parallax plugin installed, run{" "}
            <code>{PUBLIC_RELEASE.claudeStudio}</code> in Claude Code, or ask
            Codex:
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
          <p className="hosted-help">
            Starting from scratch?{" "}
            <a href={PREVIEW_GUIDES.setup}>
              Install the preview and finish your first task
            </a>
            .
          </p>
          <p className="hosted-help">
            The {PUBLIC_RELEASE.version} tools are a development preview. Use
            New task in Studio for saved candidates and separate approval. Pilot
            enrollment is closed while live acceptance finishes.
          </p>
        </section>
      </main>
      <footer className="hosted-footer">
        <span>
          Parallax {__PARALLAX_VERSION__} development preview · Studio runs
          locally
        </span>
        <nav aria-label="Legal and support">
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
          <a href="/support">Support</a>
        </nav>
      </footer>
    </div>
  );
}
