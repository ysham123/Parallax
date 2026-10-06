# Upgrade to Constellation

The install ID and repository remain `codex-claude-team`. Version 1.0 adds a private Python runtime, four native providers, API connections, autonomous runs, and Studio. Your existing native provider logins remain in their original CLIs. API connections are optional and do not convert CLI subscriptions into API access. Configure them in Studio with separate provider API credentials. API keys use macOS Keychain; Linux uses environment references.

For local development, install the plugin from your existing personal marketplace source after replacing that source directory with the validated 1.0 bundle. Keep a backup of the original plugin. Do not edit versioned Codex cache folders by hand. Reinstall through `codex plugin add codex-claude-team@personal`, then start a new chat so the updated skill and MCP tools load.

For the repository marketplace after publication:

```sh
codex plugin marketplace upgrade codex-claude-team
codex plugin add codex-claude-team@codex-claude-team
```

Check `codex plugin list` for version 1.0.0 and the enabled source. Avoid enabling duplicate personal/repository installations. Run `python3 scripts/parallax.py doctor` from the source or installed plugin and open Studio.

Runtime data defaults to `~/Library/Application Support/Parallax` on macOS and `$XDG_STATE_HOME/parallax` (or `~/.local/state/parallax`) on Linux. It includes local prompts, responses, private workspaces, sessions, and check output; protect it as project data. The local server descriptor contains a local access token and is permission-restricted.

An existing Codex chat may still have the earlier skill loaded. Start a new chat after reinstalling. Existing calls to `scripts/claude_bridge.py` retain their arguments and result shape.

Environment references must be visible to the process that starts Parallax. The bundled MCP configuration forwards the standard `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `GROK_API_KEY`, `GEMINI_API_KEY`, and `GOOGLE_API_KEY` names when supplied by the host. For a custom variable name, add that name to the host's MCP environment allowlist or start Parallax from a terminal where it is exported. Restart the local Parallax runtime after changing its environment. Keep secret values out of plugin manifests.

Select a Git repository root for autonomous editing. Existing branches, the index, and unrelated changes are preserved. Provider compatibility failures are reported; do not work around them by disabling all permission checks.
