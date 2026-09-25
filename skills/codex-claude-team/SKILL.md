---
name: codex-claude-team
description: Consult the signed-in Claude Code CLI from a local Codex task when the user explicitly asks Codex to consult or work with Claude. Supports independent review, follow-up exchanges, and expressly delegated file edits.
---

# Parallax — Codex–Claude team

Use this skill only when the user asks to involve Claude in the current task. A request to “consult Claude” or “work with Claude” starts with an independent, read-only review. Claude may edit files only when the user explicitly delegates an implementation task to Claude.

1. Form your own view of the user's request before reading Claude's answer. Give Claude the original task and any essential constraints, without your conclusion, so the first views are independent. The bridge runs in the active workspace; Claude can inspect relevant files there.
2. Find `scripts/claude_bridge.py` at the plugin root, two directories above this `SKILL.md`. Run it with `--workspace` set to the active workspace and `--mode consult`. Supply the prompt through stdin or a temporary UTF-8 file with `--prompt-file`; do not interpolate untrusted prompt text into a shell command. The script prints one JSON object containing `ok`, `answer`, `session_id`, `changed_files`, and `error`.
3. For further exchanges, pass the returned `session_id` as `--resume`. Share the precise question or disagreement to resolve. Keep the exchange bounded by what the task needs.
4. For an explicitly delegated edit, call the bridge with `--mode edit` and a specific implementation task. Wait for Claude to finish before editing the same workspace. Inspect `changed_files` and the actual diff, preserve pre-existing changes, run relevant checks, and fix or report problems. The bridge gives Claude file read and edit tools, without command execution; Codex runs tests and other commands.
5. Present Codex's view, Claude's view, meaningful disagreements, and the final synthesis. Attribute Claude's claims and changes. If the bridge fails, report the error and proceed with the work you can complete; do not invent Claude's opinion.

The plugin uses the existing Claude Code CLI login. It operates in local tasks; CLI conversations need not appear in Claude Desktop. Read-only consultations have a default three-minute timeout; edits have ten minutes. Override `--timeout` when a known task needs longer.
