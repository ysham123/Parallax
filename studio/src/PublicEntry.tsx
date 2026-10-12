import { useEffect, useRef, useState } from "react";
import { ProviderMark } from "./Brand";
import { CopyBlock } from "./Onboarding";
import { Mark, PublicFooter, ThemeToggle } from "./PublicChrome";
import WorkflowPreview from "./WorkflowPreview";
import {
  REPOSITORY,
  signInErrorMessage,
  signInMethods,
  type AuthConfig,
} from "./session";
import {
  PUBLIC_RELEASE,
  CLAUDE_INSTALL,
  CODEX_INSTALL,
  SOURCE_INSTALL,
  SOURCE_DOWNLOAD,
  PREVIEW_GUIDES,
} from "./public-release";
import "./public.css";
import "./perspective.css";
export { SOURCE_DOWNLOAD } from "./public-release";

const LOCAL_STUDIO =
  "python3 scripts/parallax.py studio \\\n  --workspace /absolute/path/to/project";
const INSTALL_METHODS = ["Claude Code", "Codex", "Source & terminal"];

function CandidateIllustration() {
  const [corrected, setCorrected] = useState(true);
  return (
    <figure
      className="px-artifact"
      aria-label="Illustrated candidate and independent review"
    >
      <div className="px-artifact-stage">
        <div className="px-request-plane" aria-hidden="true">
          <strong>Requested change</strong>
          <span>Reject empty input. Keep numeric results.</span>
          <i />
          <i />
          <i />
        </div>
        <div className="px-patch-plane">
          <div className="px-patch-heading">
            <code>maths.py</code>
            <span>Candidate {corrected ? "02" : "01"}</span>
          </div>
          <pre
            className="px-patch"
            aria-label={
              corrected ? "Corrected example diff" : "Initial example diff"
            }
          >
            <code>
              <span>{" def average(values):"}</span>
              <span className={corrected ? undefined : "px-code-add"}>
                {corrected ? "     if not values:" : "+    if not values:"}
              </span>
              {corrected ? (
                <>
                  <span className="px-code-remove">{"-        return 0"}</span>
                  <span className="px-code-add">
                    {'+        raise ValueError("empty input")'}
                  </span>
                </>
              ) : (
                <span className="px-code-remove">{"+        return 0"}</span>
              )}
              <span>{"     return sum(values) / len(values)"}</span>
            </code>
          </pre>
          <div
            className={`px-artifact-evidence ${corrected ? "" : "px-failed"}`}
          >
            <span aria-hidden="true">{corrected ? "✓" : "×"}</span>
            {corrected ? "Required check passed" : "Required check failed"}
          </div>
        </div>
        <aside className="px-review-plane">
          <strong>A second perspective</strong>
          <p>
            {corrected
              ? "Empty input now raises a clear error. Existing numeric behavior is preserved."
              : "Returning zero hides invalid input. The task requires an explicit error."}
          </p>
          <span>
            {corrected
              ? "Finding resolved in candidate 02"
              : "Finding at maths.py:2–3"}
          </span>
        </aside>
      </div>
      <div
        className="px-artifact-switch"
        role="group"
        aria-label="Explore the illustrated correction"
      >
        <button
          type="button"
          aria-pressed={!corrected}
          onClick={() => setCorrected(false)}
        >
          Before correction
        </button>
        <button
          type="button"
          aria-pressed={corrected}
          onClick={() => setCorrected(true)}
        >
          After correction
        </button>
      </div>
      <figcaption>
        Illustrated preview with simulated evidence. No agents run here.
      </figcaption>
      <span className="px-artifact-status" role="status">
        {corrected
          ? "Corrected candidate: required check passed; human approval pending."
          : "Initial candidate: required check failed; approval blocked."}
      </span>
    </figure>
  );
}

function Install() {
  const [selected, setSelected] = useState(0);
  return (
    <section
      className="px-section px-install"
      id="install"
      aria-labelledby="install-title"
    >
      <div className="px-section-intro">
        <h2 id="install-title">
          Start where
          <br />
          you already work.
        </h2>
        <p>
          Install the public local tools on macOS or Linux. Bring your agent
          sign-ins and project commands. No Parallax account is required
          locally.
        </p>
      </div>
      <div className="px-install-workbench">
        <div
          role="tablist"
          aria-label="Installation method"
          className="px-install-tabs"
        >
          {INSTALL_METHODS.map((name, index) => (
            <button
              type="button"
              role="tab"
              id={`install-tab-${index}`}
              aria-controls={`install-panel-${index}`}
              aria-selected={selected === index}
              tabIndex={selected === index ? 0 : -1}
              key={name}
              onClick={() => setSelected(index)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % 3
                    : event.key === "ArrowLeft"
                      ? (index + 2) % 3
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? 2
                          : null;
                if (next !== null) {
                  event.preventDefault();
                  setSelected(next);
                  event.currentTarget.parentElement
                    ?.querySelectorAll<HTMLButtonElement>("[role=tab]")
                    [next]?.focus();
                }
              }}
            >
              {index < 2 && (
                <ProviderMark
                  provider={index === 0 ? "claude" : "codex"}
                  size={22}
                />
              )}
              {name}
            </button>
          ))}
        </div>
        <div
          id="install-panel-0"
          role="tabpanel"
          aria-labelledby="install-tab-0"
          tabIndex={0}
          hidden={selected !== 0}
          className="px-install-panel"
        >
          <h3>Install the Parallax plugin.</h3>
          <CopyBlock
            label="Claude Code install commands"
            text={CLAUDE_INSTALL}
          />
          <p>
            Start a new chat, then use{" "}
            <code>{PUBLIC_RELEASE.claudeStudio}</code>,{" "}
            <code>{PUBLIC_RELEASE.claudeReview}</code> or{" "}
            <code>{PUBLIC_RELEASE.claudeBuild}</code>.
          </p>
        </div>
        <div
          id="install-panel-1"
          role="tabpanel"
          aria-labelledby="install-tab-1"
          tabIndex={0}
          hidden={selected !== 1}
          className="px-install-panel"
        >
          <h3>Bring the team into Codex.</h3>
          <CopyBlock label="Codex install commands" text={CODEX_INSTALL} />
          <p>
            Start a new chat and ask: “Use Parallax to review this change” or
            “Open Parallax Studio for this project.”
          </p>
        </div>
        <div
          id="install-panel-2"
          role="tabpanel"
          aria-labelledby="install-tab-2"
          tabIndex={0}
          hidden={selected !== 2}
          className="px-install-panel"
        >
          <h3>Run the tools from source.</h3>
          <CopyBlock label="Source install commands" text={SOURCE_INSTALL} />
          <p>
            A source archive requires Python and project tools. It is not a
            native installer.
          </p>
          <details>
            <summary>Open the existing local Studio</summary>
            <p>
              Run this in the Parallax source folder. Open the authenticated URL
              it prints and keep that access link private.
            </p>
            <CopyBlock label="Open local Studio command" text={LOCAL_STUDIO} />
          </details>
        </div>
        <div className="px-install-foot">
          <span>Pinned public source {PUBLIC_RELEASE.version}</span>
          <a href={SOURCE_DOWNLOAD}>Download source ZIP</a>
        </div>
      </div>
      <div className="px-release-notes">
        <div>
          <h3>Saved-candidate preview</h3>
          <p>
            The correction, human approval and team delivery screens shown here
            belong to the supplied development preview. They are not included in
            the public {PUBLIC_RELEASE.version} download.
          </p>
          <a href={PREVIEW_GUIDES.setup}>Read the preview setup guide</a>
        </div>
        <div>
          <h3>Mac application</h3>
          <p>
            The Apple Silicon, macOS 15+ app is in preparation. Its official
            download awaits signing, notarization and release validation.
          </p>
          <span className="px-unavailable">Download not available yet</span>
        </div>
      </div>
      <details className="px-practical">
        <summary>Installation requirements and provider limits</summary>
        <p>
          Public tools require macOS, or Linux with bubblewrap and user
          namespaces; Python 3.10+, Git 2.38+, and supported signed-in agent
          CLIs or API connections. Build and Compare require an independent
          provider outside the implementing team. Your provider usage and quota
          remain yours.
        </p>
        <p>
          The preview checks adapter versions and isolation before execution.
          Native Grok is currently unavailable in that preview. Claude Code and
          Antigravity use restricted file tools, with shell and content-search
          tools disabled. Detection does not prove remaining quota.{" "}
          <a href={`${REPOSITORY}#install`}>Read the installation details</a>.
        </p>
      </details>
    </section>
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
  const [failure, setFailure] = useState(
    error ? signInErrorMessage(error) : "",
  );
  const [menu, setMenu] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (error) setFailure(signInErrorMessage(error));
  }, [error]);
  useEffect(() => {
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted) setBusy(false);
    };
    window.addEventListener("pageshow", restore);
    return () => window.removeEventListener("pageshow", restore);
  }, []);
  useEffect(() => {
    if (!menu) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenu(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [menu]);
  const accounts =
    config?.identity === "supabase" && signInMethods(config).length > 0;
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
          signInErrorMessage(
            typeof body.detail === "string" ? body.detail : "failed",
          ),
        );
      const destination = new URL(body.url);
      if (destination.origin !== "https://github.com")
        throw new Error(signInErrorMessage("failed"));
      window.location.assign(destination.href);
    } catch (problem) {
      setFailure(
        problem instanceof Error
          ? problem.message
          : signInErrorMessage("failed"),
      );
      setBusy(false);
    }
  }
  const accountEntry = accounts ? (
    <a href="/login">Sign in</a>
  ) : config?.github ? (
    <button type="button" onClick={() => void signIn()} disabled={busy}>
      {busy ? "Opening GitHub…" : "Sign in"}
    </button>
  ) : (
    <a href="#connected">Accounts</a>
  );
  return (
    <div className="pub-page px-page">
      <a className="skip-link" href="#public-main">
        Skip to content
      </a>
      <header className="px-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark size={34} />
          Parallax
        </a>
        <nav className="px-desktop-nav" aria-label="Site">
          <a href="#workflow">Workflow</a>
          <a href="#install">Install</a>
          <a href={`${REPOSITORY}#readme`}>Docs</a>
        </nav>
        <div className="px-utilities">
          <button
            className="px-menu-button"
            type="button"
            ref={menuButton}
            aria-expanded={menu}
            aria-controls="public-menu"
            onClick={() => setMenu(!menu)}
          >
            Menu
          </button>
          {accountEntry}
          <ThemeToggle />
          <a className="px-studio-link" href="/studio">
            Open Studio
          </a>
        </div>
        <nav
          className="px-mobile-nav"
          id="public-menu"
          aria-label="Mobile site"
          hidden={!menu}
        >
          <a href="#workflow" onClick={() => setMenu(false)}>
            Workflow
          </a>
          <a href="#install" onClick={() => setMenu(false)}>
            Install
          </a>
          <a href={`${REPOSITORY}#readme`}>Docs</a>
          <a href="/studio">Open Studio</a>
          <div className="px-menu-theme">
            <span>Appearance</span>
            <ThemeToggle />
          </div>
        </nav>
      </header>
      <main id="public-main" tabIndex={-1}>
        {(failure || notice) && (
          <p className="pub-alert" role="alert">
            {failure || notice}
          </p>
        )}
        <section className="px-hero" aria-labelledby="hero-title">
          <h1 id="hero-title">
            <span>Delegate a change.</span>
            <span>Get back a reviewed patch.</span>
          </h1>
          <div className="px-hero-body">
            <div className="px-hero-intro">
              <p>
                Bring your coding agents together. Inspect one isolated change,
                a second perspective, and your project’s checks.
              </p>
              <div className="px-actions">
                <a className="px-primary" href="#install">
                  Install local tools
                </a>
                <a className="px-text-link" href="#workflow">
                  Explore the workflow
                </a>
              </div>
              <p className="px-availability">
                The saved-candidate workflow is a development preview. Public{" "}
                {PUBLIC_RELEASE.version} tools are available below.
              </p>
              <div className="px-providers" aria-label="Provider integrations">
                {(
                  [
                    ["codex", "Codex"],
                    ["claude", "Claude Code"],
                    ["grok", "Grok Build"],
                    ["antigravity", "Antigravity"],
                  ] as const
                ).map(([id, name]) => (
                  <span key={id}>
                    <ProviderMark provider={id} size={20} />
                    {name}
                  </span>
                ))}
              </div>
              <p className="px-provider-note">
                Supported transports vary by build.{" "}
                <a href="#install">Check requirements</a>.
              </p>
            </div>
            <CandidateIllustration />
          </div>
        </section>
        <section
          className="px-section px-workflow"
          id="workflow"
          aria-labelledby="workflow-title"
        >
          <div className="px-section-intro">
            <h2 id="workflow-title">
              The whole change,
              <br />
              within reach.
            </h2>
            <p>
              Follow one example from its request to a correction, fresh
              evidence and a human decision. Delivery is a separate action.
            </p>
          </div>
          <WorkflowPreview />
        </section>
        <section className="px-section px-fit" aria-labelledby="fit-title">
          <h2 id="fit-title">
            For changes you can
            <br />
            define and check.
          </h2>
          <div className="px-fit-list">
            <div>
              <h3>A bounded bug fix</h3>
              <p>Correct the behavior and keep its regression check.</p>
            </div>
            <div>
              <h3>A multi-file refactor</h3>
              <p>Change the implementation with stable interfaces.</p>
            </div>
            <div>
              <h3>One-component modernization</h3>
              <p>
                Replace a legacy parser while protecting its compatibility
                contract.
              </p>
              <a href={PREVIEW_GUIDES.modernization}>
                Inspect the runnable preview exercise
              </a>
            </div>
          </div>
        </section>
        <Install />
        <section
          className="px-section px-connected"
          id="connected"
          aria-labelledby="connected-title"
        >
          <div>
            <h2 id="connected-title">
              Your machine.
              <br />A shared review when you need it.
            </h2>
            <p>
              Local tools use your machine and providers. Connected workspaces
              add shared task evidence, reviewer handoff and explicitly paired
              workers.
            </p>
            <div className="px-connected-actions">
              <a className="px-secondary" href="/studio">
                Open Studio
              </a>
              {accounts ? (
                <a className="px-text-link" href="/login">
                  Sign in to your workspace
                </a>
              ) : config?.github ? (
                <button
                  className="px-text-link"
                  onClick={() => void signIn()}
                  disabled={busy}
                >
                  Sign in with GitHub
                </button>
              ) : (
                <a className="px-text-link" href="/support">
                  Ask about the invited pilot
                </a>
              )}
            </div>
            <p className="px-small">
              Pilot enrollment is closed while live validation is unfinished.
              Account sign-in and GitHub repository delivery use separate
              authorization.
            </p>
          </div>
          <dl className="px-boundaries">
            <div>
              <dt>On your machine</dt>
              <dd>
                Project snapshots, isolated work, agent processes, full
                provider-session files, sign-ins and provider credentials.
              </dd>
            </div>
            <div>
              <dt>At your chosen providers</dt>
              <dd>
                Prompts and relevant project content. Provider usage, quota and
                data policies apply.
              </dd>
            </div>
            <div>
              <dt>In a connected workspace</dt>
              <dd>
                Prompts, settings, diffs, check output, review findings, agent
                output and session metadata. This evidence can include source
                code.
              </dd>
            </div>
          </dl>
        </section>
        <section className="px-section px-faq" aria-labelledby="faq-title">
          <h2 id="faq-title">Before your first task.</h2>
          <div>
            <details>
              <summary>What does an approved change mean?</summary>
              <p>
                In the preview, approval records a human decision on an exact
                candidate and its evidence. Apply locally or publish a draft PR
                as separate operations. Passing checks support that scoped
                decision; they do not prove the software is bug-free. Public
                CLI/plugin tools retain their existing integration behavior.
              </p>
            </details>
            <details>
              <summary>Can I connect a GitHub repository?</summary>
              <p>
                The team preview supports owner-authorized GitHub App delivery
                for an approved project folder. Bind an installation, repository
                and remote base after separate GitHub authorization. Publication
                requires a matching clean remote baseline. This is not a
                repository cloning flow; dirty-tree tasks remain available for
                local delivery.
              </p>
            </details>
            <details>
              <summary>Do I need all four providers?</summary>
              <p>
                No. Use the providers available to you. Build and Compare need
                an independent reviewer from a provider outside the implementing
                team. Free software does not mean free model usage.
              </p>
            </details>
            <details>
              <summary>What stays under human control?</summary>
              <p>
                Team approval requires someone other than the revision’s
                requester, including Owners. Approval does not apply, publish,
                merge or deploy. GitHub delivery creates a draft PR; CI and
                review feedback can populate an explicit correction request.
              </p>
            </details>
            <details>
              <summary>Where can I inspect the technical limits?</summary>
              <p>
                Read the <a href="/privacy">privacy policy</a>,{" "}
                <a href={`${REPOSITORY}/blob/main/SECURITY.md`}>
                  security documentation
                </a>{" "}
                and <a href={`${REPOSITORY}#limits`}>execution limits</a>. The
                preview is still awaiting live provider, account and GitHub
                acceptance; the illustrated examples are not performance claims.
              </p>
            </details>
          </div>
        </section>
        <div className="px-last-call">
          <Mark size={40} />
          <h2>Bring the team to your next change.</h2>
          <a className="px-primary" href="#install">
            Install local tools
          </a>
        </div>
      </main>
      <PublicFooter preview />
    </div>
  );
}
