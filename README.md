# Codex Claude Team

[![Tests](https://github.com/ysham123/codex-claude-team/actions/workflows/tests.yml/badge.svg)](https://github.com/ysham123/codex-claude-team/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/ysham123/codex-claude-team)](https://github.com/ysham123/codex-claude-team/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**An independent second opinion, right inside a local Codex task.**

Codex Claude Team lets Codex ask the Claude Code CLI to inspect the same project. Codex forms its own view first, then brings Claude's findings back into the task and explains where the two agree or differ. When you explicitly delegate an edit to Claude, Codex checks the resulting diff and runs the relevant verification.

The plugin is a small Codex skill and a Python bridge. It uses your existing Claude Code login. There is no hosted relay, API key to paste into the plugin, or background agent to manage.

## What you can do

| Ask Codex to… | What happens |
| --- | --- |
| “Consult Claude on this bug and compare your findings.” | Claude reads relevant project files and returns an independent assessment. Codex synthesizes both views. |
| “Ask Claude to review this design; follow up on any disagreement.” | Codex can continue the same Claude CLI session for a focused follow-up. |
| “Have Claude implement the parser change, then review and test its diff.” | Claude gets file read and edit tools for that delegated task. Codex inspects the changed files and verifies the result. |

Consultations have read-only file tools. Edits require an explicit delegation in your request. The bridge reports changed files in either mode.

## Install

### Requirements

- A local Codex task in the Codex desktop app or Codex CLI, with plugin marketplaces available.
- [Claude Code CLI](https://code.claude.com/docs/en/overview) installed and signed in. Check with `claude auth status`; if needed, run `claude auth login`.
- Python 3.10 or newer and Git on your `PATH`.

Add this GitHub repository as a Codex marketplace, then install the plugin:

```sh
codex plugin marketplace add ysham123/codex-claude-team
codex plugin add codex-claude-team@codex-claude-team
```

This follows [OpenAI's repository marketplace installation flow](https://developers.openai.com/plugins/build/plugins).

Start a new Codex task after installing. In the desktop app, you can also open the Plugins Directory, select **Codex Claude Team** as the marketplace source, and install the plugin there.

To download the source instead, use the [v0.1.0 release](https://github.com/ysham123/codex-claude-team/releases/tag/v0.1.0) or clone the repository:

```sh
git clone https://github.com/ysham123/codex-claude-team.git
```

The marketplace method handles the Codex installation. A clone or ZIP gives you the source code.

## Use it

Open a **local** Codex task for the project you want reviewed, then ask:

> Consult Claude on the race condition in the job queue. Give me your own diagnosis first, ask Claude for an independent view, and explain any disagreement.

For an implementation handoff, be specific about the edit:

> Work with Claude on the CSV parser. Delegate the empty-field fix to Claude, then inspect its diff and run the parser tests.

Codex invokes the bridge from the installed skill. You can also call the bridge directly from a terminal:

```sh
printf '%s\n' 'Review the retry logic for correctness.' | \
  python3 scripts/claude_bridge.py --workspace /path/to/project --mode consult
```

The command prints one JSON object with `ok`, `answer`, `session_id`, `changed_files`, and `error`. Pass `--resume SESSION_ID` for a follow-up. Direct `--mode edit` calls give Claude file edit tools; use them only for a task you intend to delegate.

## How it works

```text
Your request → Codex forms its view → Claude Code CLI examines the local workspace
             → bridge returns an answer and changed-file report
             → Codex compares, verifies, and explains the result
```

The bridge checks Claude Code authentication, sends the request through standard input, and invokes Claude with a restricted tool list. Consultation allows `Read`, `Glob`, and `Grep`; delegated edits also allow `Edit` and `Write`. It records the workspace state before and after Claude runs and returns any detected file changes. A consultation that changes files is reported as a failure for Codex to inspect.

The plugin runs locally, but Claude Code may transmit your prompt and project content to Anthropic under your Claude account's settings. Use it only with work you are permitted to share with Claude. Claude Code CLI conversations do not need to appear in Claude Desktop.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Claude Code CLI was not found` | Install Claude Code and make sure `claude` is on the `PATH` used by Codex. |
| `Claude Code is not signed in` | Run `claude auth login`, then `claude auth status`. |
| Plugin is missing in an existing task | Start a new Codex task after installation. |
| Claude times out | Retry with a narrower question or use `--timeout SECONDS` for a direct bridge call. The defaults are 180 seconds for consultation and 600 seconds for edits. |
| A consultation reports changed files | Inspect the named files before continuing; the bridge treats this as an error. |

This workflow requires a local task because it calls the Claude Code executable on the same machine as Codex. It does not connect two cloud sessions or sync Claude Desktop chats.

## Development

Run the bridge tests without third-party Python packages:

```sh
python3 -m unittest discover -s tests -v
```

The [plugin manifest](plugin.json), [marketplace catalog](.agents/plugins/marketplace.json), [skill instructions](skills/codex-claude-team/SKILL.md), and [bridge](scripts/claude_bridge.py) are all included in this repository. Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Yosef Shammout.
