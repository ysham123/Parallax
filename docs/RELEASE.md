# Parallax 1.2 · Public release

Parallax runs a team of coding agents from different providers on your project and integrates only what survives independent review and your project's real checks. This release brings Parallax to Claude Code, adds individual accounts to the hosted Studio, and rebuilds how agents receive context.

## Highlights

**Claude Code plugin.** Install with `/plugin marketplace add ysham123/Parallax` and `/plugin install parallax@parallax`. Use `/parallax:review`, `/parallax:build <task>` and `/parallax:studio`, or ask Claude to bring in the team. The plugin uses the same local runtime, history and profiles as the Codex plugin and the CLI.

**Accounts and private workspaces.** A hosted Studio now has a public entry and GitHub sign-in. Each account gets a private workspace whose agents run only on machines its owner pairs, scoped to approved project folders. Sessions are server-side and revocable, accounts can be deleted with their evidence, and the operator keeps a separate workspace. Durable limits cover sign-in, pairing, machines, relayed requests and retained evidence.

**Context and memory engineering.** Every model call receives a compact, role-scoped packet compiled from saved state, never a growing transcript. Coordinator turns, repairs and reviews start fresh sessions. Reviewers never see who wrote a change, and review-mode synthesis is blind. The coordinator can explore substantially different variants of a task in isolated checkouts. A local, per-project idea graph and post-run distillation of evidence-grounded lessons give later runs a memory without hard-coded loops.

## Upgrading

See [UPGRADE.md](../UPGRADE.md#11-to-12). The Codex install ID stays `codex-claude-team`. Hosted operators should back up the runtime volume and follow the [public launch checklist](DEPLOYMENT.md#public-launch-checklist). Existing hosted sessions end, and paired workers should be updated alongside the runtime.

## Validation

- The full suite passes on Python 3.10 and 3.13 on macOS and Linux in CI, with Studio graph checks, hosted routing checks, container smoke tests and release consistency checks. Tests use deterministic fake agents; no provider inference is involved.
- The accounts work passed three adversarial review rounds covering tenant isolation, session handling, schema rollback, request races, storage limits and the OAuth flow. The engine work passed two, covering context isolation, exploration, repair budgets and memory hygiene.
- The Claude Code plugin passes `claude plugin validate --strict`, installs into a clean configuration with exactly its four skills and its MCP server, and starts the runtime from an empty state.

## Known limits

- Live API inference and the five-developer study remain separate validation gates.
- Shared team workspaces and hosted execution for personal workspaces are not available.
- API command execution requires the macOS sandbox. SSH workers and remote filesystem mounts are not supported.
- Yarn, pnpm and npm workspaces need a prepared environment. Git submodules and symlinks that leave the project need manual handling.

Release archives and `SHA256SUMS` are produced by `python3 scripts/build_release.py`.
