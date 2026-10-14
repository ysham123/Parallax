# Parallax for Claude Code

Parallax runs Codex, Claude Code, Grok Build and Antigravity as one coding team on your project. Each agent works in its own isolated copy, a different provider reviews every change, and your project's own checks must pass before anything reaches your working tree. Every run ends with a verification record of what was checked.

## Install

```text
/plugin install parallax-team --marketplace ysham123/Parallax
```

On Claude Code older than 2.1.275, run `/plugin marketplace add ysham123/Parallax` and then `/plugin install parallax-team@parallax`. Start a new session after installing.

## Commands

```text
/parallax-team:review                      independent review of this project or a focus area
/parallax-team:build <task>                implement a task with review and checks before integration
/parallax-team:studio                      open Parallax Studio for this project
```

You can also ask Claude directly, for example "have Parallax review this change with Codex and Grok."

## Requirements

macOS or Linux, Python 3.10 or newer, Git 2.38 or newer, and at least one signed-in agent CLI (`codex`, `claude`, `grok` or `agy`) or a provider API key. On Linux, project commands need bubblewrap with user namespaces.

## What this plugin runs, sends and stores

- **Local MCP server.** Claude Code starts `python3 scripts/parallax.py mcp` from this plugin. Nothing listens on the network for it.
- **First-run install.** On first start, the launcher creates a private Python environment in your Parallax state directory and installs the exact packages listed in `requirements.lock` from PyPI, as binary wheels verified against their SHA-256 hashes. It does not change global packages or provider settings. The state directory is `~/Library/Application Support/Parallax` on macOS and `$XDG_STATE_HOME/parallax` (or `~/.local/state/parallax`) on Linux.
- **Agent processes.** For a run, Parallax launches the agent CLIs you selected as child processes, using their existing sign-ins, each in an isolated working copy of your project. Project commands run inside the operating system sandbox (macOS Seatbelt or Linux bubblewrap); native CLIs also apply their own permission controls.
- **What leaves your machine.** Prompts and the relevant parts of your project go only to the providers you select: through their CLIs, or, if you set up an API connection, directly to that provider's API with a key you keep in macOS Keychain or name as an environment variable. Parallax has no server of its own in this path and sends no telemetry.
- **Local Studio.** Studio runs as a local web server bound to `127.0.0.1` with a random access token, when you open it.
- **What it stores.** Run history, events, verification records, versioned workflow recipes, workflow checkpoints and approval decisions, team and project profiles, and a per-project memory of lessons from earlier runs, all in the state directory. Workflow orchestration uses LangGraph locally, with LangSmith tracing disabled. Set `PARALLAX_MEMORY=off` to turn memory off.
- **Changes to your project.** A Build writes to your working tree only after independent review and your project's checks pass, and keeps your staged and unstaged changes.
- **Hosted Studio (optional).** Nothing goes to the hosted Studio unless you pair a machine yourself with the `worker` command. A paired worker connects outward over HTTPS and mirrors run evidence to your hosted workspace, as described in the [privacy policy](https://parallax.yosefshammout.com/privacy).
- **Feedback (opt-in).** Feedback metrics are recorded locally and leave your machine only if you export and send them.
- **Packaged interface.** `src/parallax/static` is the production build of the Studio source in `studio/`. The project's CI rebuilds it from source and fails if the output differs.

## Links

- Documentation and source: https://github.com/ysham123/Parallax
- Support: https://parallax.yosefshammout.com/support
- Privacy policy: https://parallax.yosefshammout.com/privacy
- Terms of service: https://parallax.yosefshammout.com/terms

## License

MIT. See `LICENSE`.
