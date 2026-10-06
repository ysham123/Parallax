---
name: codex-claude-team
description: Use Parallax when the user asks for a coding team, invokes Parallax, or asks to involve Claude Code, Grok Build, or Antigravity in a local Codex task. Supports independent reviews, autonomous implementation, alternative solutions, model and effort selection, and Studio.
---

# Parallax Constellation

Activate when requested. Keep the user's chosen providers, models, effort, scope, and existing authorization. A request for consultation is a Review; a request to implement with the team is a Build. Use Compare when the user wants alternative implementations evaluated against common checks.

Use the Parallax MCP tools when available. Otherwise locate `scripts/parallax.py` at the plugin root, two directories above this skill, and call it with Python. Prompts and structured run specifications go through UTF-8 files or stdin, never interpolated shell commands.

- Run diagnostics, inspect connections, and read model catalogs before choosing settings. Catalogs identify their source. Honor explicit settings; report unsupported choices instead of silently substituting them. Defaults are Codex coordinator, Quality first, and the available team requested by the user.
- Open Studio with `parallax_studio` or `scripts/parallax.py studio --workspace PATH`, then open its returned local URL in the Codex browser panel. Studio shares the same profiles and run state as chat controls.
- Assess Build and Compare projects with `parallax_assess_project` before starting. Inspect package roots, setup blockers and all required checks. Save reusable project configuration with the project-profile operations. One implementer and an independent reviewing provider are sufficient; retain explicit model and effort selections.
- Start a run with `parallax_start_run` or `scripts/parallax.py run --spec FILE`. Supply the current repository root, task, mode, coordinator, team, limits, and meaningful check argv commands when known. The runtime handles private workspaces, scheduling, review, and integration. Do not independently edit the same project during an implementation run.
- Inspect status and evidence through `parallax_get_run`. Steering applies at the next checkpoint. Pause, Stop, and Resume have distinct lifecycle operations. Keep user progress updates tied to actual events and wait between unchanged status checks.
- Use `parallax_get_recovery` for recorded failure categories. Repair and retry reconcile existing attempts; setup changes start a new run. Keep every configured final check even if it failed at baseline. Feedback is opt-in and exported locally; never share it without a separate request.
- Evaluate the result's diffs, independent findings, and check evidence. Report failures and preserved artifacts honestly. Completion requires the runtime's verification gates; model claims and consensus do not replace checks. Build and Compare need Git. Review can operate in non-Git workspaces.

Every selected coordinator is a dedicated CLI or API session. Model and effort controls do not change the initiating Codex chat. CLI connections use existing native sign-ins. API connections use macOS Keychain or environment references. Inspect parallax_connections and the selected transport catalog. API secrets belong in Studio; do not embed them in run specs, prompts, or profiles. Custom models need an explicit compatible endpoint and capability catalog. Remote inference is supported. Hosted Studio can pair an outbound local worker with exact approved project roots using the worker CLI; see docs/LOCAL-WORKERS.md. Execution and provider credentials stay on that worker. SSH execution and remote workspace mounts are not enabled. Publishing, deploying, or pushing requires a separate user request.

For a simple legacy Claude consultation or delegated edit, `scripts/claude_bridge.py` remains compatible. Use `--mode consult` for independent read-only assessment, `--resume` for follow-ups, and `--mode edit` for the specifically delegated implementation. Inspect its changed-files result and actual diff.
