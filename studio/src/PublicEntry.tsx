import { useEffect, useState } from "react";
import { ProviderMark } from "./Brand";
import { CopyBlock } from "./Onboarding";
import { Mark, PublicFooter, ThemeToggle } from "./PublicChrome";
import WorkflowPreview from "./WorkflowPreview";
import { REPOSITORY, signInErrorMessage, signInMethods, type AuthConfig } from "./session";
import { PUBLIC_RELEASE, CLAUDE_INSTALL, CODEX_INSTALL, SOURCE_INSTALL, SOURCE_DOWNLOAD } from "./public-release";
import "./public.css";

const PROVIDERS = [
  ["codex", "Codex"], ["claude", "Claude Code"],
  ["grok", "Grok Build"], ["antigravity", "Antigravity"],
] as const;
const LOCAL_STUDIO = "python3 scripts/parallax.py studio \\\n  --workspace /absolute/path/to/project";
export { SOURCE_DOWNLOAD } from "./public-release";

function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    {diagonal ? <path d="M5 15 15 5M5 5h10v10" /> : <path d="M3 10h13m-5-5 5 5-5 5" />}
  </svg>;
}

function CandidateIllustration() {
  return <figure className="landing-artifact" aria-label="Illustration of a saved candidate, independent review and project checks">
    <div className="landing-artifact-top"><span><i aria-hidden="true" /> SAVED CANDIDATE</span><span className="landing-example-label">Illustration</span></div>
    <div className="landing-orbit" aria-hidden="true">
      <svg viewBox="0 0 480 230" fill="none">
        <path className="landing-orbit-line" d="M28 115H452M240 14V216" />
        <ellipse cx="240" cy="115" rx="174" ry="54" transform="rotate(-22 240 115)" />
        <ellipse cx="240" cy="115" rx="174" ry="54" transform="rotate(22 240 115)" />
        <ellipse className="landing-orbit-inner" cx="240" cy="115" rx="94" ry="94" />
        <circle className="landing-orbit-center" cx="240" cy="115" r="22" />
        <circle className="landing-orbit-dot" cx="93" cy="176" r="5" />
        <circle className="landing-orbit-dot second" cx="387" cy="54" r="5" />
      </svg>
      <span className="landing-orbit-tag left">isolated work</span><span className="landing-orbit-tag right">independent review</span>
      <span className="landing-orbit-title">One patch.<br /><strong>A visible path to approval.</strong></span>
    </div>
    <div className="landing-mini-diff"><div><span className="landing-file-icon" aria-hidden="true">⌘</span><span>maths.py</span><span className="landing-diff-count">+2</span></div>
      <code><span className="landing-code-muted"> def average(values):</span><span className="landing-code-add">+    if not values:</span><span className="landing-code-add">+        raise ValueError("empty input")</span><span className="landing-code-muted">     return sum(values) / len(values)</span></code>
    </div>
    <div className="landing-evidence-strip"><span><i aria-hidden="true">✓</i> Project checks</span><span><i aria-hidden="true">✓</i> Independent review</span><span className="landing-evidence-human">Your approval</span></div>
    <figcaption>Changes, findings and check results beside the candidate you approve.</figcaption>
  </figure>;
}

function Install() {
  return <section className="pub-section landing-install-section" id="install" aria-labelledby="install-title">
    <div className="landing-section-heading"><div><p className="pub-eyebrow">Start where you already work</p><h2 id="install-title">Bring your agents.<br />Keep your workflow.</h2></div><p>Install the public local tools: Review, Build, Compare and the existing Studio. The source download is pinned to {PUBLIC_RELEASE.version}. The saved-candidate workflow shown above needs the separate development preview.</p></div>
    <div className="landing-install-grid">
      <article className="landing-install-card"><ProviderMark provider="claude" size={26} /><h3>Claude Code</h3><p>Current public plugin: <code>parallax</code>.</p><CopyBlock label="Claude Code install commands" text={CLAUDE_INSTALL} /><p className="landing-install-note">Start a new chat, then use <code>{PUBLIC_RELEASE.claudeStudio}</code>, <code>{PUBLIC_RELEASE.claudeReview}</code> or <code>{PUBLIC_RELEASE.claudeBuild}</code>.</p></article>
      <article className="landing-install-card"><ProviderMark provider="codex" size={26} /><h3>Codex</h3><p>Ask Codex to bring in the team.</p><CopyBlock label="Codex install commands" text={CODEX_INSTALL} /><p className="landing-install-note">Start a new chat and ask: “Use Parallax to review this change” or “Open Parallax Studio for this project.”</p></article>
      <article className="landing-install-card landing-source-card"><span className="landing-terminal-symbol" aria-hidden="true">&gt;_</span><h3>Source &amp; terminal</h3><p>Run the public local tools yourself.</p><CopyBlock label="Source install commands" text={SOURCE_INSTALL} /><a className="landing-text-link" href={SOURCE_DOWNLOAD}>Download source ZIP <Arrow diagonal /></a><p className="landing-install-note">Pinned public source {PUBLIC_RELEASE.version}. Requires Python; this is a source archive, not a native desktop installer. The new saved-candidate Studio workflow and team/GitHub pilot build are not included.</p></article>
    </div>
    <div className="landing-open-studio"><div><span className="landing-small-label">LOCAL STUDIO</span><h3>Your project. A browser tab.</h3><p>Run this from your Parallax source folder, then open the authenticated URL printed in the result. It launches the existing local Studio. Keep that access link private.</p></div><CopyBlock label="Open local Studio command" text={LOCAL_STUDIO} /></div>
    <p className="landing-requirements"><strong>Before your first task</strong> macOS, or Linux with bubblewrap and user namespaces; Python 3.10+, Git 2.38+, and a signed-in agent CLI or API key. Build and Compare require an available independent provider that did not implement the candidate. Provider charges and quota are yours. <a href={`${REPOSITORY}#install`}>Installation details <Arrow diagonal /></a></p>
  </section>;
}

export default function PublicEntry({ config, error, notice }: { config: AuthConfig | null; error: string | null; notice?: string }) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(error ? signInErrorMessage(error) : "");
  useEffect(() => { if (error) setFailure(signInErrorMessage(error)); }, [error]);
  useEffect(() => { const restore = (event: PageTransitionEvent) => { if (event.persisted) setBusy(false); }; window.addEventListener("pageshow", restore); return () => window.removeEventListener("pageshow", restore); }, []);
  const methods = signInMethods(config);
  const accounts = config?.identity === "supabase" && methods.length > 0;
  async function signIn() {
    setBusy(true); setFailure("");
    try {
      const response = await fetch("/api/auth/github/start", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" } });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.url !== "string") throw new Error(signInErrorMessage(typeof body.detail === "string" ? body.detail : "failed"));
      const destination = new URL(body.url);
      if (destination.origin !== "https://github.com") throw new Error(signInErrorMessage("failed"));
      window.location.assign(destination.href);
    } catch (problem) { setFailure(problem instanceof Error ? problem.message : signInErrorMessage("failed")); setBusy(false); }
  }
  return <div className="pub-page landing-page">
    <a className="skip-link" href="#public-main">Skip to content</a>
    <header className="pub-header landing-header"><a className="pub-brand" href="/" aria-label="Parallax home"><Mark size={30} />Parallax</a><nav aria-label="Site"><a href="#workflow" className="landing-nav-workflow">Workflow</a><a href={`${REPOSITORY}#readme`}>Docs</a><a href="/studio">Studio <Arrow diagonal /></a><ThemeToggle /><a className="pub-signin-link" href="#install">Install</a></nav></header>
    <main id="public-main" tabIndex={-1}>
      <section className="pub-hero landing-hero" aria-labelledby="hero-title"><div className="pub-hero-copy">
        <p className="pub-eyebrow landing-hero-eyebrow"><span aria-hidden="true" /> Coding workflows on your machine</p>
        <h1 id="hero-title">Delegate a change.<br /><span>Get back a<br className="landing-hero-break" /> reviewed patch.</span></h1>
        <p className="pub-lead">Your coding agents, working as a team. Isolated changes, independent review, and real project checks. The upcoming Studio workflow brings corrections and human approval into the same view.</p>
        <div className="pub-actions"><a className="pub-primary" href="#install">Install local tools <Arrow /></a><a className="pub-secondary" href="#workflow">Preview the workflow <span aria-hidden="true">↓</span></a></div>
        <p className="pub-fineprint landing-local-note">Open source · Runs locally · No account needed locally</p><p className="pub-fineprint">Unreleased Studio workflow preview. Install the current public local tools below.</p>
        <ul className="pub-providers" aria-label="Supported agents">{PROVIDERS.map(([id, name]) => <li key={id}><ProviderMark provider={id} size={20} />{name}</li>)}</ul>
        {(failure || notice) && <p className="pub-alert" role="alert">{failure || notice}</p>}
      </div><CandidateIllustration /></section>
      <div className="landing-principles" aria-label="Product principles"><span><i aria-hidden="true">01</i> Your providers</span><span><i aria-hidden="true">02</i> Isolated work</span><span><i aria-hidden="true">03</i> Inspectable evidence</span><span><i aria-hidden="true">04</i> Explicit approval</span></div>
      <section className="pub-section landing-workflow-section" id="workflow" aria-labelledby="workflow-title"><div className="landing-section-heading"><div><p className="pub-eyebrow">The whole change, in view</p><h2 id="workflow-title">A patch is a starting point.<br />Make it a decision.</h2></div><p>Explore the unreleased Studio workflow: changes, checks, a review finding, a correction and human approval. The illustrated evidence is simulated; the public source download has the existing local tools.</p></div><WorkflowPreview /></section>
      <section className="pub-section landing-reasons" aria-labelledby="reasons-title"><div className="landing-section-heading"><div><p className="pub-eyebrow">A clear path from work to evidence</p><h2 id="reasons-title">Let agents do the work.<br />Keep the decision yours.</h2></div><p>Parallax connects implementation, verification and review into a workflow you can inspect and return to.</p></div><div className="landing-reason-grid">
        <article><span className="landing-reason-number">01 / ISOLATION</span><h3>Keep your working tree yours.</h3><p>Agents work in private checkouts seeded from your project. The upcoming Studio workflow keeps saved candidates separate from your files. Local application preserves staging and checks for conflicting edits.</p><span className="landing-reason-foot">Private worktrees · Captured baseline</span></article>
        <article><span className="landing-reason-number">02 / VERIFICATION</span><h3>Read what actually passed.</h3><p>Run your project’s real check commands and inspect their output. A provider outside the implementing team reviews the candidate independently. Failures remain visible.</p><span className="landing-reason-foot">Check output · Independent findings</span></article>
        <article><span className="landing-reason-number">03 / CONTROL</span><h3>Correct it before you deliver it.</h3><p>The upcoming Studio workflow revises a saved candidate against its original baseline, or starts afresh from your current project. It separates candidate approval from local application or pilot PR publication.</p><span className="landing-reason-foot">Fresh evidence · Recorded decisions</span></article>
      </div></section>
      <section className="pub-section landing-reasons" aria-labelledby="modernization-title"><div className="landing-section-heading"><div><p className="pub-eyebrow">A focused modernization exercise</p><h2 id="modernization-title">Upgrade the component.<br />Protect the behavior.</h2></div><p>Older services carry rules that their users depend on. The development preview includes a bounded exercise: replace one batch job’s legacy parser while preserving its CLI and settlement report. Start with a working baseline and an agreed compatibility contract.</p></div><div className="landing-reason-grid">
        <article><span className="landing-reason-number">01 / RECORD</span><h3>Make the contract explicit.</h3><p>Freeze representative inputs, expected outputs, allowed files and the target change. In the bundled CSV exercise, that includes refunds, rounding, dates and rejected input.</p><span className="landing-reason-foot">One component · Defined acceptance</span></article>
        <article><span className="landing-reason-number">02 / VERIFY</span><h3>Test what consumers observe.</h3><p>The exercise has 34 characterization tests. A naive local parser conversion fails two compatibility cases; a compatible local conversion passes. Independent review still has to inspect the exact patch.</p><span className="landing-reason-foot">Synthetic exercise · Local test evidence</span></article>
        <article><span className="landing-reason-number">03 / DECIDE</span><h3>Review each upgrade.</h3><p>Choose “Modernize one component” in the supplied preview, inspect checks and findings, request a correction, then approve the saved candidate. Your team controls application and delivery.</p><span className="landing-reason-foot">Preview recipe · Explicit delivery</span></article>
      </div><p className="landing-data-note">This exercise is included in the development preview, separately from the public download. Live agent migration and customer comparisons remain to be validated. Whole-system conversion, production data migration and automatic deployment are outside this pilot.</p></section>
      <Install />
      <section className="pub-section landing-studio-section" id="studio" aria-labelledby="studio-title"><div className="landing-studio-copy"><p className="pub-eyebrow">An interface for the work</p><h2 id="studio-title">Studio in your browser.<br />Local by default.</h2><p>The public local Studio lets you follow runs, inspect changes and review evidence in your browser. The upcoming task workspace adds saved-candidate corrections and human approval. Plugins, CLI and Studio share the same runtime.</p><a className="landing-text-link" href={`${REPOSITORY}#studio`}>Explore Studio <Arrow diagonal /></a></div><div className="landing-hosted-card"><span className="landing-small-label">OPTIONAL · INVITED PILOT</span><h3>Share the review with your team.</h3><p>Hosted Studio adds invited workspaces, project access and reviewer handoff on explicitly paired machines. Team approval requires another human. GitHub App delivery publishes an approved candidate to a draft PR.</p><p>These features are being validated for an invited pilot. Enrollment and commercial terms are arranged manually. Paired workers must remain online for task controls and team evidence.</p><div className="landing-hosted-actions"><a className="pub-secondary" href="/studio">Open Studio <Arrow /></a>{accounts ? <a href="/login" className="landing-text-link">Log in</a> : config?.github ? <button className="landing-text-link" type="button" onClick={() => void signIn()} disabled={busy}>{busy ? "Opening GitHub…" : "Sign in with GitHub"}</button> : null}</div><p className="landing-install-note">Account sign-in and repository delivery use separate authorization. Legacy CLI/plugin runs retain their existing integration behavior.</p></div></section>
      <section className="pub-section landing-data-section" aria-labelledby="data-title"><div className="landing-section-heading"><div><p className="pub-eyebrow">Know where the work goes</p><h2 id="data-title">Local execution.<br />Clear data boundaries.</h2></div><p>Bring your own machine and providers. Connecting a hosted workspace adds a relay; publishing adds GitHub.</p></div><div className="landing-data-grid">
        <article><span className="landing-small-label">01 / YOUR MACHINE</span><h3>Execution &amp; private copies</h3><p>Project snapshots, private worktrees, agent processes, full local provider-session files, sign-ins and provider credentials stay on the worker.</p></article>
        <article><span className="landing-small-label">02 / MODEL PROVIDERS</span><h3>Prompts &amp; relevant code</h3><p>Your selected providers receive task prompts and the project content needed for their role. Their own usage, quota and data policies apply.</p></article>
        <article><span className="landing-small-label">03 / OPTIONAL RELAY</span><h3>Workspace &amp; task evidence</h3><p>Connected workspaces mirror prompts, settings, diffs, check output, review findings, agent output and session metadata. This evidence can contain source code.</p></article>
        <article><span className="landing-small-label">04 / EXPLICIT DELIVERY</span><h3>The approved candidate</h3><p>Current local builds integrate verified patches under their existing behavior. The upcoming workflow adds explicit application or configured GitHub delivery of an approved candidate. Merging and deployment stay with you.</p></article>
      </div><p className="landing-data-note">Free software does not mean free model usage. Read the <a href="/privacy">privacy policy</a>, <a href={`${REPOSITORY}/blob/main/SECURITY.md`}>security documentation</a> and <a href={`${REPOSITORY}#limits`}>execution limits</a> before connecting a project.</p></section>
      <section className="pub-section landing-faq" aria-labelledby="faq-title"><div><p className="pub-eyebrow">Before you install</p><h2 id="faq-title">A few practical details.</h2></div><div>
        <details><summary>Do I need a Parallax account?</summary><p>Local Studio, plugins and the CLI run without a hosted account. An account is needed when you choose a connected hosted workspace.</p></details>
        <details><summary>Do I need all four providers?</summary><p>No. Choose the providers you have available. Build and Compare need an independent reviewer from a provider that did not implement the candidate. Sign-in detection does not establish remaining quota.</p></details>
        <details><summary>Which agents can run the development preview?</summary><p>The supplied preview checks adapter versions and execution boundaries before running. Native Grok execution is currently unavailable under its required isolation policy. Claude Code and Antigravity use restricted file tools; their shell and content-search tools are disabled. Supported API connections provide another entry point. These preview restrictions are separate from the pinned public download.</p></details>
        <details><summary>What can I download today?</summary><p>The source ZIP is pinned to public version {PUBLIC_RELEASE.version}; the source commands check out that same revision. It requires Python and the listed prerequisites. The plugins install from the repository. Native desktop installers are not available. The saved-candidate development preview requires a separate build supplied by the operator. Pilot enrollment remains closed while live validation is unfinished.</p></details>
        <details><summary>Does approval merge or deploy my change?</summary><p>The unreleased Studio workflow records approval separately from delivery. Current public CLI/plugin builds retain their existing integration behavior. In the upcoming workflow, apply locally or publish a draft PR explicitly after approval. Pilot GitHub delivery requires App setup and a matching clean remote baseline. Parallax does not automatically merge or deploy.</p></details>
      </div></section>
      <section className="landing-last-call" aria-label="Get Parallax"><Mark size={44} /><h2>Bring the team to your next change.</h2><a className="pub-primary" href="#install">Install local tools <Arrow /></a><p>Start locally. Open Studio when you want the whole picture.</p></section>
    </main>
    <PublicFooter preview />
  </div>;
}
