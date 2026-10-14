import { useEffect, useRef, useState } from "react";
import { CopyBlock } from "./Onboarding";
import { Mark, PublicFooter, ThemeToggle } from "./PublicChrome";
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
import "./site.css";
import proofReplaceAll from "./assets/excalidraw-replace-all.png";
import proofDarkFocus from "./assets/excalidraw-dark-focus.png";
import { parsePricing, type Pricing } from "./pricing";
export { SOURCE_DOWNLOAD } from "./public-release";

const LOCAL_STUDIO =
  "python3 scripts/parallax.py studio \\\n  --workspace /absolute/path/to/project";
const INSTALL_METHODS = ["Claude Code", "Codex", "From source"];

type Fact = {
  name: string;
  detail: string;
  state: "passed" | "failed" | "attention" | "waiting" | "pending";
};
type Line = {
  kind: "context" | "add" | "del";
  old?: number;
  new?: number;
  text: string;
};

const EXAMPLE: Record<1 | 2, { facts: Fact[]; lines: Line[]; note: string }> = {
  1: {
    note: "Candidate 1 is blocked. The reviewer found a gap and one final check failed.",
    facts: [
      {
        name: "Baseline checks",
        detail: "412 passed on main",
        state: "passed",
      },
      { name: "Prepared", detail: "Codex changed 4 files", state: "passed" },
      {
        name: "Independent review",
        detail: "Claude Code: 1 finding",
        state: "attention",
      },
      { name: "Final checks", detail: "1 failed, 416 passed", state: "failed" },
      {
        name: "Human approval",
        detail: "Blocked until checks pass",
        state: "pending",
      },
      { name: "Delivery", detail: "Nothing delivered", state: "pending" },
    ],
    lines: [
      {
        kind: "context",
        old: 39,
        new: 39,
        text: '  const signature = header(req, "x-ledger-signature");',
      },
      {
        kind: "del",
        old: 40,
        text: "  if (!hmacEquals(secret, req.rawBody, signature)) {",
      },
      {
        kind: "add",
        new: 40,
        text: '  const sent = Number(header(req, "x-ledger-timestamp"));',
      },
      {
        kind: "add",
        new: 41,
        text: "  if (clock.now() - sent > REPLAY_WINDOW_MS) {",
      },
      {
        kind: "add",
        new: 42,
        text: '    throw new WebhookRejected("stale_timestamp");',
      },
      { kind: "add", new: 43, text: "  }" },
      {
        kind: "add",
        new: 44,
        text: "  if (!verifySignature(secret, `${sent}.${req.rawBody}`, signature)) {",
      },
      {
        kind: "context",
        old: 41,
        new: 45,
        text: '    throw new WebhookRejected("bad_signature");',
      },
    ],
  },
  2: {
    note: "Candidate 2 is ready. Evidence is recorded against this exact candidate.",
    facts: [
      {
        name: "Baseline checks",
        detail: "412 passed on main",
        state: "passed",
      },
      {
        name: "Prepared",
        detail: "Codex revised candidate 1",
        state: "passed",
      },
      {
        name: "Independent review",
        detail: "Finding resolved",
        state: "passed",
      },
      {
        name: "Final checks",
        detail: "418 passed, 6 new tests",
        state: "passed",
      },
      { name: "Human approval", detail: "Needs a teammate", state: "waiting" },
      {
        name: "Delivery",
        detail: "Then a draft pull request",
        state: "pending",
      },
    ],
    lines: [
      {
        kind: "context",
        old: 39,
        new: 39,
        text: '  const signature = header(req, "x-ledger-signature");',
      },
      {
        kind: "del",
        old: 40,
        text: "  if (!hmacEquals(secret, req.rawBody, signature)) {",
      },
      {
        kind: "add",
        new: 40,
        text: '  const sent = Number(header(req, "x-ledger-timestamp"));',
      },
      {
        kind: "add",
        new: 41,
        text: "  if (!Number.isFinite(sent) || clock.now() - sent > REPLAY_WINDOW_MS) {",
      },
      {
        kind: "add",
        new: 42,
        text: '    throw new WebhookRejected("stale_timestamp");',
      },
      { kind: "add", new: 43, text: "  }" },
      {
        kind: "add",
        new: 44,
        text: "  if (!verifySignature(secret, `${sent}.${req.rawBody}`, signature)) {",
      },
      {
        kind: "context",
        old: 41,
        new: 45,
        text: '    throw new WebhookRejected("bad_signature");',
      },
    ],
  },
};

const EVIDENCE_URL =
  "https://github.com/ysham123/Parallax/blob/main/demos/excalidraw-find-replace/evidence.md";

const RECORD: [string, string][] = [
  ["Repository", "The Excalidraw monorepo, pinned to commit 2df993f"],
  [
    "Team",
    "Codex coordinating and implementing; Claude Sonnet reviewing independently",
  ],
  [
    "Required checks",
    "A frozen 16-case acceptance suite the agents could not edit, the monorepo typecheck, and Excalidraw's full upstream test suite",
  ],
  [
    "Result",
    "The first final checks failed and Claude rejected the first repair. The second repair passed all three checks after 78 minutes.",
  ],
  [
    "Caught by checks",
    "In a separate run, review approved a change the upstream suite rejected: undo stopped recording image paste and drag-in. The task stopped instead of handing it back.",
  ],
  [
    "In the browser",
    "The real editor passed 12 of 12 behaviors and showed two layout defects code review missed. A 15-minute follow-up fixed them: 14 of 14.",
  ],
  [
    "Not claimed",
    "Not merged upstream. Provider cost was not reported, so it is unknown.",
  ],
];

function RecordedRun() {
  return (
    <section
      className="site-section"
      id="proof"
      aria-labelledby="proof-title"
    >
      <div className="site-section-head">
        <h2 id="proof-title">A recorded run on a real repository.</h2>
        <p>
          Parallax was asked to add find and replace to Excalidraw&apos;s canvas
          search, in the actual open-source monorepo. Nothing below is a
          mockup.
        </p>
      </div>
      <div className="site-proof">
        <dl className="site-proof-record">
          {RECORD.map(([term, detail]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
        <div className="site-proof-shots">
          <figure>
            <img
              src={proofReplaceAll}
              width={1280}
              height={800}
              loading="lazy"
              alt="Excalidraw with Replace all applied: three matches replaced literally, the locked text left unchanged, and the result reported in the search panel"
            />
            <figcaption>Replace all, with locked text protected</figcaption>
          </figure>
          <figure>
            <img
              src={proofDarkFocus}
              width={1280}
              height={800}
              loading="lazy"
              alt="The same search panel in dark mode with keyboard focus on the Replace with field"
            />
            <figcaption>Dark mode and keyboard focus</figcaption>
          </figure>
        </div>
      </div>
      <p className="site-proof-source">
        Recorded October 12, 2026 in headless Chromium.{" "}
        <a href={EVIDENCE_URL}>Read the evidence record</a>
      </p>
    </section>
  );
}

const PRICING = parsePricing(
  typeof __PARALLAX_PRICING__ === "string" ? __PARALLAX_PRICING__ : "",
);

function PricingSection({ pricing = PRICING }: { pricing?: Pricing | null }) {
  if (!pricing) return null;
  return (
    <section
      className="site-section"
      id="pricing"
      aria-labelledby="pricing-title"
    >
      <div className="site-section-head">
        <h2 id="pricing-title">Pricing</h2>
        <p>
          Parallax runs on your machine with the agents you already pay for.
          Their usage is billed by your own Claude, Codex or Antigravity plan,
          not by Parallax.
        </p>
      </div>
      <div className="site-plans">
        <div className="site-plan">
          <h3>Free</h3>
          <p className="site-plan-price">$0</p>
          <ul>
            <li>{pricing.freeTasks} new tasks a month</li>
            <li>Every check, review and evidence feature</li>
            <li>Retries, recovery and delivery never count</li>
          </ul>
          <a className="btn btn-secondary" href="#install">
            Install Parallax
          </a>
        </div>
        <div className="site-plan">
          <h3>Pro</h3>
          <p className="site-plan-price">
            {pricing.monthly}
            <span> a month</span>
            {pricing.yearly && (
              <span className="site-plan-alt">
                {" "}
                or {pricing.yearly} a year
              </span>
            )}
          </p>
          <ul>
            <li>Unlimited tasks</li>
            <li>Everything in Free</li>
            <li>One license key, checked about once a day</li>
          </ul>
          {pricing.founding && (
            <p className="site-plan-note">{pricing.founding}</p>
          )}
          <a className="btn btn-primary" href={pricing.checkoutUrl}>
            Get Pro
          </a>
        </div>
      </div>
    </section>
  );
}

function ProductExample() {
  const [candidate, setCandidate] = useState<1 | 2>(2);
  const example = EXAMPLE[candidate];
  return (
    <figure className="site-example" aria-label="Illustrative Parallax task">
      <div className="site-example-stage">
        <div className="site-example-plane" aria-hidden="true" />
        <div className="site-window">
          <div className="site-window-main">
            <div className="site-window-head">
              <span className="site-repo">ledger-api</span>
              <strong>
                Reject replayed webhook events older than five minutes
              </strong>
            </div>
            <div className="site-window-tabs" aria-hidden="true">
              <span className="selected">
                Changes <em>4 files</em>
              </span>
              <span>Checks</span>
              <span>Review</span>
            </div>
            <div
              className="site-diff"
              aria-label={`Example diff, candidate ${candidate}`}
              role="img"
            >
              <div className="site-diff-file">src/webhooks/verify.ts</div>
              {example.lines.map((line, index) => (
                <div key={index} className={`site-diff-line ${line.kind}`}>
                  <span>{line.kind === "add" ? line.new : line.old}</span>
                  <span>
                    {line.kind === "add"
                      ? "+"
                      : line.kind === "del"
                        ? "-"
                        : " "}
                  </span>
                  <span>{line.text}</span>
                </div>
              ))}
              {candidate === 1 && (
                <div className="site-finding">
                  <strong>Claude Code review</strong>
                  <p>
                    A missing timestamp header parses as NaN, so the replay
                    check never rejects it. Reject non-numeric timestamps.
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="site-window-ledger">
            <span className="site-ledger-title">
              Evidence for candidate {candidate}
            </span>
            <ol className="site-ledger">
              {example.facts.map((fact) => (
                <li key={fact.name} className={fact.state}>
                  <i className={`fact-dot ${fact.state}`} aria-hidden="true" />
                  <span>{fact.name}</span>
                  <small>{fact.detail}</small>
                </li>
              ))}
            </ol>
            <div className="site-ledger-actions" aria-hidden="true">
              <span
                className={`site-fake-button ${candidate === 2 ? "primary" : "disabled"}`}
              >
                Approve
              </span>
              <span className="site-fake-button">Request changes</span>
            </div>
          </div>
        </div>
      </div>
      <div className="site-example-controls">
        <div className="site-segment" role="group" aria-label="Show candidate">
          {([1, 2] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={candidate === value}
              onClick={() => setCandidate(value)}
            >
              Candidate {value}
            </button>
          ))}
        </div>
        <p role="status">{example.note}</p>
      </div>
      <figcaption>
        Illustrative example. The repository, code and results are not from a
        recorded run.
      </figcaption>
    </figure>
  );
}

function Install() {
  const [selected, setSelected] = useState(2);
  return (
    <section
      className="site-section site-install"
      id="install"
      aria-labelledby="install-title"
    >
      <div className="site-section-head">
        <h2 id="install-title">Install</h2>
        <p>
          The {PUBLIC_RELEASE.version} development preview runs on your machine
          with the agent sign-ins you already have. Start from the pinned source
          below. No Parallax account is needed to work locally.
        </p>
      </div>
      <div className="site-preview-note">
        <p>
          <strong>Finish your first task in Studio.</strong> Follow the
          first-task guide through installation, review, approval and local
          application. New Studio tasks use saved candidates and separate
          approval. Plugin and CLI build requests retain their existing local
          integration behavior. Pilot enrollment is closed while live
          acceptance finishes.
        </p>
        <a href={PREVIEW_GUIDES.setup}>Install the preview and run your first task</a>
      </div>
      <div className="site-install-box">
        <div
          role="tablist"
          aria-label="Installation method"
          className="site-tabs"
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
          className="site-install-panel"
        >
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
          className="site-install-panel"
        >
          <CopyBlock label="Codex install commands" text={CODEX_INSTALL} />
          <p>
            Start a new chat and ask Codex to “use Parallax to review this
            change” or to “open Parallax Studio for this project.”
          </p>
        </div>
        <div
          id="install-panel-2"
          role="tabpanel"
          aria-labelledby="install-tab-2"
          tabIndex={0}
          hidden={selected !== 2}
          className="site-install-panel"
        >
          <CopyBlock label="Source install commands" text={SOURCE_INSTALL} />
          <p>
            Needs Python and your project's tools. This is a source checkout,
            not a native installer.
          </p>
          <details className="site-inline-details">
            <summary>Open Studio from the source folder</summary>
            <p>
              Run this inside the Parallax folder, then open the private link it
              prints. Keep that link to yourself.
            </p>
            <CopyBlock label="Open local Studio command" text={LOCAL_STUDIO} />
          </details>
        </div>
        <div className="site-install-foot">
          <span>Pinned preview source {PUBLIC_RELEASE.version}</span>
          <a href={SOURCE_DOWNLOAD}>Download source ZIP</a>
        </div>
      </div>
      <dl className="site-platforms">
        <div>
          <dt>macOS</dt>
          <dd>
            Plugin and source. A signed desktop app is in preparation and not
            yet downloadable.
          </dd>
        </div>
        <div>
          <dt>Linux</dt>
          <dd>Source, with bubblewrap and user namespaces for sandboxing.</dd>
        </div>
        <div>
          <dt>Windows</dt>
          <dd>No native worker yet. WSL2 is experimental and unverified.</dd>
        </div>
      </dl>
      <details className="site-inline-details">
        <summary>Requirements and provider limits</summary>
        <p>
          macOS, or Linux with bubblewrap and user namespaces. Python 3.10+, Git
          2.38+, and at least one signed-in agent CLI or API connection. Build
          and Compare need an independent reviewer from a provider outside the
          implementing team. Provider usage and quota remain yours.
        </p>
        <p>
          The preview checks adapter versions and isolation before running.
          Native Grok is currently unavailable in the preview. Claude Code and
          Antigravity run with restricted file tools and no shell. Detecting a
          provider does not prove remaining quota.{" "}
          <a href={`${REPOSITORY}#install`}>Installation details</a>
        </p>
      </details>
    </section>
  );
}

const STEPS = [
  [
    "Describe the outcome",
    "Choose a bounded change, project checks and an execution time limit.",
  ],
  [
    "Agents work in isolation",
    "On a separate copy of the repository. Your working files stay untouched.",
  ],
  [
    "A second agent reviews",
    "Fresh context, findings pinned to lines, fixes made as a new candidate.",
  ],
  [
    "Your checks run twice",
    "Compare the recorded baseline with the final results for this candidate.",
  ],
  [
    "Inspect and approve",
    "Read the diff, checks and review. Team approval needs another authorized person.",
  ],
  [
    "You choose delivery",
    "After approval, apply locally or publish a configured draft pull request.",
  ],
] as const;

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
    <a className="site-nav-link" href="/login">
      Sign in
    </a>
  ) : config?.github ? (
    <button
      type="button"
      className="site-nav-link"
      onClick={() => void signIn()}
      disabled={busy}
    >
      {busy ? "Opening GitHub…" : "Sign in"}
    </button>
  ) : (
    <a className="site-nav-link" href="#teams">
      Accounts
    </a>
  );
  const navigation = [
    ["#how", "How it works"],
    ["#teams", "Teams"],
    ["#install", "Install"],
    [`${REPOSITORY}#readme`, "Docs"],
  ] as const;
  return (
    <div className="site">
      <a className="skip-link" href="#public-main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header-inner">
          <a className="site-brand" href="/" aria-label="Parallax home">
            <Mark size={22} />
            Parallax
          </a>
          <nav className="site-nav" aria-label="Site">
            {navigation.map(([href, name]) => (
              <a key={name} href={href}>
                {name}
              </a>
            ))}
          </nav>
          <div className="site-utilities">
            {accountEntry}
            <ThemeToggle />
            <a className="btn btn-primary small site-studio" href="/studio">
              Open Studio
            </a>
            <button
              className="site-menu-button"
              type="button"
              ref={menuButton}
              aria-expanded={menu}
              aria-controls="public-menu"
              onClick={() => setMenu(!menu)}
            >
              Menu
            </button>
          </div>
        </div>
        <nav
          className="site-mobile-nav"
          id="public-menu"
          aria-label="Mobile site"
          hidden={!menu}
        >
          {navigation.map(([href, name]) => (
            <a key={name} href={href} onClick={() => setMenu(false)}>
              {name}
            </a>
          ))}
          <a href="/studio">Open Studio</a>
          <div className="site-menu-theme">
            <span>Appearance</span>
            <ThemeToggle />
          </div>
        </nav>
      </header>
      <main id="public-main" tabIndex={-1}>
        {(failure || notice) && (
          <p className="site-alert" role="alert">
            {failure || notice}
          </p>
        )}
        <section className="site-hero" aria-labelledby="hero-title">
          <h1 id="hero-title">
            Delegate a change.
            <br />
            Get back a reviewed patch.
          </h1>
          <p className="site-lede">
            Parallax runs your coding agents on a separate copy of your
            repository. Inspect the patch, independent review and recorded
            checks, then approve the candidate when you are ready.
          </p>
          <div className="site-actions">
            <a className="btn btn-primary site-cta" href="#install">
              Install Parallax
            </a>
            <a className="btn btn-secondary site-cta" href="/local">
              Open local Studio
            </a>
          </div>
          <p className="site-fineprint">
            Works with Codex, Claude Code, Antigravity and Grok Build where each
            is supported. macOS and Linux.
          </p>
          <p className="site-fineprint">
            The 1.4 development preview is awaiting live acceptance.{" "}
            <a href={PREVIEW_GUIDES.setup}>Start with the first-task guide</a>.
          </p>
        </section>
        <ProductExample />
        <section className="site-section" id="how" aria-labelledby="how-title">
          <div className="site-section-head">
            <h2 id="how-title">
              Review the result before it reaches your project.
            </h2>
            <p>
              In the 1.4 preview, each saved candidate has its own diff,
              independent review and recorded checks. A revision needs fresh
              evidence and approval. Applying the approved patch is a separate
              action.
            </p>
          </div>
          <ol className="site-steps">
            {STEPS.map(([title, body], index) => (
              <li key={title}>
                <span className="site-step-number">{index + 1}</span>
                <h3>{title}</h3>
                <p>{body}</p>
              </li>
            ))}
          </ol>
        </section>
        <RecordedRun />
        <section className="site-section" aria-labelledby="fit-title">
          <div className="site-section-head">
            <h2 id="fit-title">Best for changes you can define and check.</h2>
          </div>
          <div className="site-columns">
            <div>
              <h3>A bounded bug fix</h3>
              <p>Correct the behavior and keep its regression test.</p>
            </div>
            <div>
              <h3>A multi-file refactor</h3>
              <p>Change the implementation behind stable interfaces.</p>
            </div>
            <div>
              <h3>A one-component migration</h3>
              <p>
                Replace a legacy parser while protecting its compatibility
                contract.{" "}
                <a href={PREVIEW_GUIDES.modernization}>See the exercise</a>
              </p>
            </div>
          </div>
        </section>
        <section
          className="site-section"
          id="teams"
          aria-labelledby="teams-title"
        >
          <div className="site-section-head">
            <h2 id="teams-title">Alone on your laptop, or with a team.</h2>
          </div>
          <div className="site-split">
            <div>
              <h3>On your own</h3>
              <p>
                Install the plugin or run from source. Agents use your sign-ins
                on your machine. You can approve your own work. No account
                needed.
              </p>
            </div>
            <div>
              <h3>With a team</h3>
              <p>
                Create a workspace, pair a machine you control, and grant
                projects. Developers start work, reviewers approve it without
                installing anything, and GitHub delivery is opt-in per
                repository. An account never supplies compute and never signs
                you up for email.
              </p>
              <div className="site-inline-actions">
                {accounts ? (
                  <a href="/login">Sign in to your workspace</a>
                ) : config?.github ? (
                  <button
                    type="button"
                    className="btn-text"
                    onClick={() => void signIn()}
                    disabled={busy}
                  >
                    Sign in with GitHub
                  </button>
                ) : (
                  <a href="/support">Ask about the invited pilot</a>
                )}
              </div>
              <p className="site-fineprint">
                Pilot enrollment is closed while live validation finishes.
              </p>
            </div>
          </div>
        </section>
        <PricingSection />
        <Install />
        <section className="site-section" aria-labelledby="data-title">
          <div className="site-section-head">
            <h2 id="data-title">Where your code goes.</h2>
          </div>
          <dl className="site-columns site-data">
            <div>
              <dt>On your machine</dt>
              <dd>
                Project copies, agent processes, provider sessions, sign-ins and
                credentials.
              </dd>
            </div>
            <div>
              <dt>At the providers you choose</dt>
              <dd>
                Prompts and the project content an agent reads. Their usage,
                quota and data policies apply.
              </dd>
            </div>
            <div>
              <dt>In a connected workspace</dt>
              <dd>
                Prompts, settings, diffs, check output, review findings and
                agent output. This evidence can include source code.
              </dd>
            </div>
          </dl>
        </section>
        <section className="site-section site-faq" aria-labelledby="faq-title">
          <div className="site-section-head">
            <h2 id="faq-title">Questions</h2>
          </div>
          <div className="site-faq-list">
            <details>
              <summary>What does approving a change mean?</summary>
              <p>
                Approval records a person's decision on one exact candidate and
                its evidence. Applying it locally or opening a draft pull
                request are separate steps. Passing checks support that
                decision; they do not prove the software is bug-free.
              </p>
            </details>
            <details>
              <summary>Can I connect a GitHub repository?</summary>
              <p>
                In the team preview, an owner can authorize the GitHub App and
                connect a repository and base branch to a project folder that is
                already on a paired machine. Publishing needs a clean baseline
                that matches the remote base. Parallax does not clone
                repositories for you yet.
              </p>
            </details>
            <details>
              <summary>Do I need all four providers?</summary>
              <p>
                No. Use the ones you have. Build and Compare need a reviewer
                from a different provider than the one that wrote the change.
                Free software does not mean free model usage.
              </p>
            </details>
            <details>
              <summary>What stays under human control?</summary>
              <p>
                Starting work, revising, approving, applying and publishing are
                each explicit. Team approval needs someone other than the
                requester. Nothing is merged, force-pushed or deployed.
              </p>
            </details>
            <details>
              <summary>Where are the technical limits written down?</summary>
              <p>
                In the <a href="/privacy">privacy policy</a>, the{" "}
                <a href={`${REPOSITORY}/blob/main/SECURITY.md`}>
                  security notes
                </a>{" "}
                and the <a href={`${REPOSITORY}#limits`}>execution limits</a>.
                The preview is still awaiting live provider, account and GitHub
                acceptance.
              </p>
            </details>
          </div>
        </section>
        <section className="site-closing" aria-labelledby="closing-title">
          <h2 id="closing-title">Hand off the next change.</h2>
          <div className="site-actions">
            <a className="btn btn-primary site-cta" href="#install">
              Install Parallax
            </a>
            <a className="btn btn-secondary site-cta" href="/local">
              Open local Studio
            </a>
          </div>
        </section>
      </main>
      <PublicFooter preview />
    </div>
  );
}
