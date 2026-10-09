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

## 1.0 to 1.1 developer alpha

Back up the enabled personal source and replace it with the validated 1.1 bundle, then run `codex plugin add codex-claude-team@personal`. Confirm version 1.1.0. Do not edit Codex's versioned cache manually. Start a new chat to load the added assessment, project-profile, recovery and feedback MCP tools.

Pause or finish active work before restarting the local runtime. The runtime descriptor retains its port and authentication token; cookies and event replay reconnect after restart. SQLite adds project_profiles and feedback tables without dropping 1.0 runs, team profiles, sessions or events. Old final receipts are retained unchanged. A resumed legacy run with no configured checks must obtain a meaningful baseline from its original snapshot or remain Needs attention.

Project setup is now checked before Build and Compare. Add node_modules/ and generated compiler outputs to .gitignore. Commit an npm lockfile or supply supported Python requirements. Linux users need functioning bubblewrap with user namespaces; unprotected command execution no longer falls back silently. See [real-project delivery](docs/DELIVERY.md) and the [alpha protocol](docs/ALPHA.md).

## 1.1 to 1.2

**Claude Code.** Install the new plugin with `/plugin marketplace add ysham123/Parallax` and `/plugin install parallax@parallax`, then start a new session. It shares state, profiles and run history with the Codex plugin and the CLI.

**Codex.** Run `codex plugin marketplace upgrade codex-claude-team` and `codex plugin add codex-claude-team@codex-claude-team`, then start a new chat. The marketplace now points to `ysham123/Parallax`; GitHub redirects the old repository name, so existing installations keep updating. The install ID is unchanged.

**Local runtime.** Finish or pause active runs before upgrading. The launcher prepares a new private environment for 1.2.0 and starts a fresh local Studio server the next time it is needed; runs, profiles, connections and receipts are kept. Project memory starts empty and fills as runs finish. Set `PARALLAX_MEMORY=off` to disable it.

**Hosted deployments.** Back up the Railway volume, then follow [Migrating an existing deployment](docs/DEPLOYMENT.md#migrating-an-existing-deployment). Existing hosted sessions end, so sign in again. Update paired workers to 1.2 alongside the runtime so evidence declined while storage is low is resent instead of skipped.

## 1.3 to 1.4

**Claude Code.** The plugin is renamed `parallax-team`. Run `/plugin marketplace update parallax`, uninstall the old plugin with `/plugin uninstall parallax@parallax`, install `/plugin install parallax-team@parallax`, and start a new session. Commands move from `/parallax:` to `/parallax-team:`. State, profiles and run history are shared and unchanged.

**Codex and the local runtime.** Update as before; nothing else changes.

**Hosted deployments.** Update the runtime as usual. If you move Studio to a custom domain, follow [Custom domain](docs/DEPLOYMENT.md#custom-domain).

## 1.2 to 1.3

**Plugins and local runtime.** Update as for 1.2: `/plugin marketplace update parallax` in Claude Code, or `codex plugin marketplace upgrade codex-claude-team` and `codex plugin add codex-claude-team@codex-claude-team` in Codex, then start a new session. Nothing changes for local runs.

**Hosted deployments.** Back up the runtime volume, then follow [Enable sign-in with Supabase](docs/DEPLOYMENT.md#enable-sign-in-with-supabase-email-github-google) and the [public launch checklist](docs/DEPLOYMENT.md#public-launch-checklist). Without the Supabase variables the runtime keeps the built-in GitHub sign-in. Existing accounts and sessions carry over.
