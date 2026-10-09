# Contributing

Parallax separates connections, runtime actions, and Studio. Keep their versioned contracts synchronized. Native CLI behavior is documented in `src/parallax/providers.py`; API transports use `connections.py` and `api_agent.py`. Provider-native teams are disabled so the runtime remains responsible for assignment and integration.

Use Python 3.10+ and Git 2.38+. Install the locked environment with `uv sync --extra test`, then run `PYTHONPATH=src uv run python -m unittest discover -s tests -v`. Tests use deterministic fake CLIs and HTTP transports and do not spend inference credits. Run `python scripts/validate_release.py` to check manifests, skills, and packaged assets. For the Claude Code plugin, run `claude plugin validate . --strict`. To try a working copy the way users get it, run `claude plugin marketplace add . --scope local` and `claude plugin install parallax-team@parallax --scope local` inside a scratch project. Marketplace installs load only the skills under `claude-code/skills/`; `claude --plugin-dir .` loads the MCP server and the Codex skill but not the Claude Code commands.

For Studio development, run `npm ci` and `npm run build` in `studio/`. Commit `src/parallax/static/` and the npm lockfile. End users do not need Node. Verify keyboard navigation, reduced motion, light mode, empty states, invalid settings, connection failures, and run reconnection in a real browser.

Before a release, exercise native providers in disposable projects, including schema output, file edits, resume, permission denial, cancellation, and a four-provider build. Keep sanitized evidence under `docs/validation/`. Never include credentials, private prompts, project contents, or live session identifiers. API-key tests require an explicitly configured connection; fixture coverage alone does not establish live API compatibility.

Use GitHub private vulnerability reporting for security issues. Changes affecting snapshots or application must verify staged, unstaged, untracked, and concurrently edited files. Changes affecting recovery must demonstrate that dispatch, commands and integration are not blindly repeated after interruption.
