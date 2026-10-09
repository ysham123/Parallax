# Changelog

## 1.4.0 · Directory ready

- Optional remote MCP for personal accounts: eight tools use the existing paired-machine relay, with Supabase JWT verification, explicit OAuth consent and revocable client grants. Hosted execution remains unavailable to remote clients. Enable only after completing the audience-hook and live OAuth setup in `docs/REMOTE-MCP.md`.
- `scripts/build_openai_plugin.py` builds a separate `parallax-team` directory ZIP with remote HTTPS MCP, a pairing skill, listing metadata and five positive/three negative proposed review cases. Draft builds do not claim live readiness; submission builds require a demo-recording URL.

- The Claude Code plugin is now named `parallax-team`, because another publisher already lists a plugin called `parallax` in Anthropic's directory. Install with `/plugin install parallax-team@parallax`; commands are `/parallax-team:review`, `/parallax-team:build` and `/parallax-team:studio`. The Codex install ID stays `codex-claude-team`.
- Hosted Studio publishes a privacy policy, terms of service and a support page at `/privacy`, `/terms` and `/support`, linked from every public page. They load without the runtime or a session.
- The public page describes hosted accounts by email, name and sign-in method instead of GitHub only.
- A Claude Code plugin tree for Anthropic's directory: `scripts/build_claude_plugin.py` assembles the runtime, the four Claude Code skills and the Studio source without the Codex plugin, checks it against the directory's rules, and CI publishes it to the `claude-code-plugin` branch after every green push to `main`. The plugin README describes everything the plugin runs, sends and stores.
- The Claude Code MCP server starts as `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/parallax.py mcp`, and the manifest carries the directory's icon, documentation, support, privacy and terms links. Its display name is Parallax Team.

## 1.3.0 · Accounts

- Sign up and log in with email and password, GitHub or Google, through Supabase Auth. Email sign-ups are confirmed by a link that works on any device, and forgotten passwords are reset by email.
- The runtime makes every call to Supabase itself. Keys never reach the browser, Studio keeps `connect-src 'self'`, and the Supabase token is used once to read the user and then revoked. Parallax keeps its own revocable server-side sessions, so the workspace boundary and limits are unchanged.
- GitHub and Google sign-in use PKCE with a sealed, browser-bound flow cookie and keep no server state while pending. A sign-in started in another browser fails the code exchange.
- Abuse limits: generic answers that never reveal whether an email has an account, 5 sign-ups and 3 reset emails per address per hour, a 15-minute pause after 10 failed passwords, and the existing open, allowlist or closed policy with an account cap applied before Supabase is called.
- Owners and allowlists by email (`PARALLAX_OWNER_EMAILS`, `PARALLAX_ALLOWED_EMAILS`); GitHub IDs still work, matched through the Supabase GitHub identity. Deleting an account also deletes the Supabase user when `PARALLAX_SUPABASE_SECRET_KEY` is set.
- Studio has sign-up, log-in, forgot-password and set-new-password pages, and the account menu and deletion dialog name accounts by email. The public entry offers Get started and Log in once sign-in is configured.
- Accounts from the GitHub-only release move to a provider-neutral table at startup and keep their workspaces and sessions. The built-in GitHub OAuth App remains available for deployments without Supabase.

## 1.2.0 · Public release

- Claude Code plugin: install with `/plugin marketplace add ysham123/Parallax` and `/plugin install parallax@parallax`. It provides `/parallax:review`, `/parallax:build` and `/parallax:studio`, a team skill Claude uses when you ask for Parallax, and the same MCP runtime as the Codex plugin.
- Hosted accounts: GitHub sign-in (OAuth with PKCE and a browser-bound state), a private personal workspace per account, revocable server-side sessions, account deletion, and a public entry page with first-machine onboarding.
- Server-enforced workspace boundary: personal workspaces reach only their own machines, pairing codes, relayed requests, mirrored evidence, and event replay; the hosted engine, its CLI sign-ins, and project clones stay with the operator workspace.
- Durable limits for accounts, sign-in, pairing, machines, queued requests, and retained evidence; bounded request bodies including chunked uploads; additive migration of existing machines into the operator workspace.
- Rollback-safe storage: the previous release sees personal machines as revoked and cannot redeem personal pairing codes. Pending GitHub sign-ins keep no server state. Workers resend evidence a relay low on storage declined.
- Context engineering: every provider call receives a role-scoped packet compiled from durable state, with budgets, hash fences, path scrubbing and a recorded content-free manifest. Coordinator turns, repairs, reviews and synthesis start fresh sessions; only a crashed attempt is continued.
- Evaluator isolation: reviewers judge the request, the original requirements, the candidate's own patch and its own evidence, never the implementer; review-mode synthesis is blind.
- Exploration: the coordinator can try substantially different variants of a task in isolated checkouts, reviewed and checked independently, and merge one.
- Project memory: a local per-project idea graph, coordinator-only retrieval with `search_ideas`, and post-run distillation of grounded, evidence-weighted lessons with local inspect, disable and forget controls.
- Planner packets carry a complete task index with actionable detail first; plans are capped at 40 tasks; synthesis and worker packets are budgeted by encoded size; memory text is stored with runtime paths scrubbed and project paths relative.
- Fixes: the integration reviewer sees the checks it just ran, merge conflicts consume the repair budget instead of looping, a failed attempt is never re-run for free after a crash, a process's started event, with its recovery identity, always precedes its output, integration reviews judge the completed tasks' acceptance criteria, reviews without a verdict are retried once, process steps never block isolated reviews, failed variants can be repaired within their round, and the distiller is told its lesson limits.
- Studio shows exploration: variants by round beside the task they explore, the selected variant, and why others were set aside. Inspectors show each call's context packet by section and size, and New run has a Project memory panel to review, disable or forget lessons.
- One version constant drives the runtime, CLI, MCP server, launcher and release archives. Plugin metadata and the Codex marketplace point to `ysham123/Parallax`, and the Codex install ID stays `codex-claude-team`.

Live API inference and the five-developer study remain separate validation gates.

## 1.1.0 · Developer alpha

- Read-only project assessment, package roots, reusable project profiles and selected-provider readiness.
- Private baseline checks, required final check preservation, per-package dependency setup and environment provenance.
- Contextual recovery and repair briefs carrying actual failed checks and independent findings.
- Studio readiness, check comparison, recovery and opt-in aggregate feedback export.
- Graph-first Workspace with project run history, separate agent and task views, recorded assignment inspection, scoped activity and responsive keyboard drawers.
- Refreshable native model catalogs in Team settings, configured Codex defaults and profile support, with explicit errors for unavailable defaults and preserved saved selections.
- Vercel entry and optional dedicated Railway-backed Studio builds, secure hosted sessions, persistent container deployment, and deployment validation.
- Versioned additive contracts and SQLite tables, retained 1.0 receipts and legacy Claude compatibility.
- Python service, typed React and mixed-project fake-agent acceptance fixtures; prepared matched single-Codex alpha protocol.

## 1.0.0 · Constellation

- Added Codex, Claude Code, Grok Build, and Antigravity adapters with native sign-ins, model and effort selection, streaming results, and resumable sessions.
- Added a selectable autonomous coordinator and runtime-owned task scheduling, independent review, combined verification, and guarded integration.
- Added Parallax Studio with Team, Run, and Review, saved presets, live events, checkpoint steering, history, and recovery controls.
- Added private effective-worktree snapshots and isolated workers preserving staged, unstaged, and untracked user changes.
- Added durable SQLite state, CLI and stdio MCP interfaces, pinned runtime dependencies, and packaged frontend assets.
- Added CLI/API connection choice, Keychain or environment references, custom compatible endpoints, official provider marks and an accessible task graph with repair history.
- Added downloadable verification records and patches with explicit gates, preservation evidence and SHA-256 fingerprints.
- Preserved the original Claude bridge interface and plugin installation identity.

## 0.1.0 · First Contact

- Introduced independent Claude consultation, resumable follow-ups, and explicitly delegated file edits.
- Published the Parallax identity and repository marketplace installation.
