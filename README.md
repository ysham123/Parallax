<p align="center">
  <img src="assets/parallax-hero.svg" alt="Parallax — Two minds. One codebase. Sharper judgment." width="100%">
</p>

<p align="center">
  <a href="https://github.com/ysham123/codex-claude-team/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/ysham123/codex-claude-team/actions/workflows/tests.yml/badge.svg"></a>
  <a href="https://github.com/ysham123/codex-claude-team/releases/tag/v0.1.0"><img alt="First Contact release" src="https://img.shields.io/badge/release-First_Contact-A989FF?style=flat-square"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-62D8D1?style=flat-square"></a>
</p>

<p align="center">
  <a href="#launch-in-30-seconds">Install</a> ·
  <a href="#the-experience">See how it works</a> ·
  <a href="https://github.com/ysham123/codex-claude-team/releases/tag/v0.1.0">Download First Contact</a>
</p>

---

## A second perspective, built into the flow

**Parallax** brings Claude Code into a local Codex task. Codex considers your problem, asks Claude for an independent read of the same project, then brings the two views together. When you explicitly hand Claude an edit, Codex reviews the changed files and runs the relevant checks.

No extra dashboard. No copy-pasting context between chats. Just a deliberate handoff between two coding agents in your workspace.

> **First Contact** is the inaugural release. The plugin's install ID remains `codex-claude-team`, so the commands below are stable and easy to share.

## Launch in 30 seconds

You need a local Codex task, [Claude Code CLI](https://code.claude.com/docs/en/overview) signed in on the same machine, Python 3.10+, and Git. Verify your Claude login with `claude auth status`; run `claude auth login` if needed.

```sh
codex plugin marketplace add ysham123/codex-claude-team
codex plugin add codex-claude-team@codex-claude-team
```

Start a new Codex task for your project and say:

> Consult Claude on this bug. Form your own diagnosis first, ask Claude for an independent view, and show me where your conclusions differ.

You can also install from the **Parallax** marketplace source in the Codex desktop Plugins Directory. The CLI steps follow [OpenAI's repository marketplace flow](https://developers.openai.com/plugins/build/plugins).

## The experience

| 01 / Ask for perspective | 02 / Continue the conversation | 03 / Hand off an edit |
| :--- | :--- | :--- |
| Codex gets Claude's independent, read-only assessment of your current workspace. | Codex can ask a focused follow-up in the same Claude session when the first answer raises a question. | You explicitly delegate a specific change. Claude edits files; Codex inspects the diff and verifies the result. |

### Try a review

> Review the retry logic with Claude. I want two independent diagnoses of any failure modes, then a single recommendation that explains the tradeoffs.

### Try an implementation handoff

> Delegate the empty-field fix in the CSV parser to Claude. When it finishes, inspect every changed file and run the parser tests before summarizing the result.

### What Codex receives

```json
{
  "ok": true,
  "answer": "Claude's response…",
  "session_id": "…",
  "changed_files": [],
  "error": null
}
```

That structured result lets Codex continue the conversation and check what actually changed. The example shows the shape of a response, not a real session.

## A clear line between review and edits

```text
YOUR TASK
   │
   ▼
CODEX forms an independent view
   │
   ├──── consultation ────► CLAUDE CODE reads the workspace
   │                            │
   │◄──── answer + file report ─┘
   │
   └──── explicit delegation ► CLAUDE CODE edits the project
                                │
        CODEX reviews + tests ◄─┘
```

The bridge gives consultations `Read`, `Glob`, and `Grep`. An explicitly delegated edit also gets `Edit` and `Write`. It snapshots the workspace before and after the Claude run and reports detected file changes. If a consultation changes files, the bridge returns an error for Codex to inspect.

The plugin is a Codex skill plus a small Python bridge. It uses your existing Claude Code CLI login and does not require a separate API key or hosted relay. The workflow runs in **local Codex tasks**; it does not sync cloud sessions or Claude Desktop chats.

## Download the launch edition

Get the source from the [First Contact release](https://github.com/ysham123/codex-claude-team/releases/tag/v0.1.0), [download the ZIP](https://github.com/ysham123/codex-claude-team/archive/refs/tags/v0.1.0.zip), or clone it:

```sh
git clone https://github.com/ysham123/codex-claude-team.git
```

The marketplace commands above install the plugin into Codex. A ZIP or clone gives you the source for inspection and development.

## For builders

Call the bridge directly when you want its JSON result in a local script:

```sh
printf '%s\n' 'Review the retry logic for correctness.' | \
  python3 scripts/claude_bridge.py --workspace /path/to/project --mode consult
```

Use `--resume SESSION_ID` for a follow-up. Use `--mode edit` only when you intend to give Claude a defined file-editing task. Direct calls also accept `--prompt-file` and `--timeout SECONDS`. The default timeout is 180 seconds for consultation and 600 seconds for edits.

Run the test suite without third-party Python packages:

```sh
python3 -m unittest discover -s tests -v
```

Explore the [skill](skills/codex-claude-team/SKILL.md), [bridge](scripts/claude_bridge.py), [plugin manifest](plugin.json), and [marketplace catalog](.agents/plugins/marketplace.json). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

<details>
<summary><strong>Troubleshooting</strong></summary>

| Symptom | Check |
| --- | --- |
| `Claude Code CLI was not found` | Install Claude Code and make sure `claude` is on the `PATH` used by Codex. |
| `Claude Code is not signed in` | Run `claude auth login`, then `claude auth status`. |
| Plugin is missing in an existing task | Start a new Codex task after installation. |
| Claude times out | Narrow the question or use `--timeout SECONDS` for a direct bridge call. |
| A consultation reports changed files | Inspect the named files before continuing. The bridge treats this as an error. |

</details>

<details>
<summary><strong>Data and permissions</strong></summary>

Claude Code may transmit your prompt and project content to Anthropic under your Claude account settings. Use Parallax with projects you are permitted to share with Claude. Consultations use read-only file tools; file edits require an explicit delegation in your request.

</details>

---

<p align="center"><strong>FIRST CONTACT</strong><br>Made by <a href="https://github.com/ysham123">Yosef Shammout</a> · <a href="LICENSE">MIT licensed</a></p>
