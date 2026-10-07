---
name: parallax
description: Run a verified multi-model coding team with Parallax. Use when the user asks for Parallax, a coding team, an independent review or second opinion from Codex, Grok or Antigravity, alternative implementations to compare, or a change that must pass independent review and real project checks before it lands.
---

# Parallax

Parallax runs a team of coding agents (Codex, Claude Code, Grok Build, Antigravity, or API models) on the user's project. The runtime gives each agent an isolated checkout, has a different provider review every change, runs the project's real checks on the combined result, and only then applies the verified patch. You start runs, follow them, and report the evidence. You do not do the team's work yourself.

## Choose the mode

- **Review**: independent read-only assessments, synthesized blind. Use for "review", "second opinion", "audit".
- **Build**: the coordinator plans scoped tasks, workers implement, reviewers check each change, combined checks gate integration. Use for "build", "implement", "fix" with the team.
- **Compare**: isolated alternative implementations, each checked against the same commands; the best verified candidate integrates.

Keep the user's chosen providers, models, effort, scope and limits. Defaults are a Codex coordinator, Claude and Antigravity implementing, Grok reviewing, and the Quality first profile. If a provider is not signed in, say so and offer the available team; never substitute silently.

## Run it

Use the Parallax MCP tools (`parallax_*`). If they are unavailable, call the CLI instead: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parallax.py" <command>`, passing specifications through a UTF-8 file, never through interpolated shell strings. The first start prepares a private Python runtime, which can take a minute.

1. `parallax_doctor` and `parallax_connections` show which providers are signed in. Read `parallax_models` before choosing a model or effort.
2. For Build and Compare, call `parallax_assess_project` on the repository root and resolve setup blockers first. Supply meaningful check commands as argv arrays, such as `["npm", "test"]`. Without real checks the runtime will not integrate.
3. `parallax_start_run` with `workspace` set to the absolute repository root, `prompt`, `mode`, `coordinator`, `team`, `limits` and `checks`.
4. Follow with `parallax_get_run`. Report progress only from recorded events, and wait between unchanged checks. `parallax_steer`, `parallax_pause`, `parallax_cancel` and `parallax_resume` control the run. On failure, use `parallax_get_recovery`.
5. When it settles, summarize what the evidence shows: changed files, review findings, check results, and anything that needs attention. `parallax_get_receipt` exports the verification record.

## Boundaries

- Do not edit the project yourself while a Build or Compare run is active; the runtime owns integration.
- Model claims and agreement are not verification. Only the runtime's review and check gates are.
- Build and Compare need a Git repository. Review works anywhere.
- API keys belong in Studio's Connections, never in prompts, run specs or profiles.
- Parallax applies changes to the working tree only. Committing, pushing, publishing and deploying need a separate request from the user.
- Studio (`parallax_studio`) returns a local link that carries an access token. Give it to the user to open; do not fetch it or paste it elsewhere.
