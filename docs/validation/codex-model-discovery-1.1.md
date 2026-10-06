# Codex catalog and default validation

Validated locally on October 6, 2026. These checks do not establish model inference entitlement or replace the earlier native build demonstration.

## User-visible issue

The native Codex picker offered seven visible models while an already-open Studio page retained an older three-model catalog. A fresh installed-runtime query returned the current catalog. Studio previously fetched provider models only during its initial load or the broad connections refresh, and the runtime derived the CLI default from the first catalog row rather than configured selection.

## Corrected behavior

- Team includes a dedicated **Refresh models** control that bypasses the runtime metadata cache. Opening Team or returning the page to view also rereads catalogs.
- The native catalog remains discovered through `codex debug models`, with clearly identified cached and bundled fallbacks. No model IDs or efforts are invented for native discovery.
- The Codex default follows the model in `CODEX_HOME/config.toml`, normally `~/.codex/config.toml`, including the configured profile. Invalid configuration or a missing configured model produces an explicit error. Explicit available selections remain usable.
- Saved model and effort selections remain intact during refresh. A selection that disappears remains visible and blocks starting or saving until corrected.
- Studio, CLI `doctor --refresh` / `models codex --refresh`, and MCP diagnostics/model operations share the force-refresh behavior.

## Installed validation

The personal `codex-claude-team@personal` 1.1.0 installation was updated from the curated repository files. The idle local runtime was restarted on its existing loopback port, and completed run history and statuses were preserved.

Installed Codex CLI 0.160.1 returned these seven visible model IDs:

1. `gpt-6.1-sol`
2. `gpt-6-astra`
3. `gpt-6-sol`
4. `gpt-6-luna`
5. `gpt-5.6-sol`
6. `gpt-5.6-terra`
7. `gpt-5.6-luna`

Browser validation on the installed Studio confirmed all seven coordinator menu choices and **CLI default · GPT-6.1-Sol**, with **Codex configuration** as its default source. An explicit `gpt-5.6-luna` / `max` draft survived forced refresh. Luna omitted `ultra` from its effort menu; Sol exposed it as reported by the CLI. No run was started, saved profiles were not modified, and no inference was requested during this validation.

## Automated checks

- 34 provider tests passed, including 12 new deterministic catalog regressions for configured defaults, profiles, CODEX_HOME, hidden model filtering, model-specific efforts, native default markers, cache expiration and forced refresh without substitution.
- 9 server/CLI/MCP tests passed, including forced-refresh routing.
- 17 connection/permission/session tests passed.
- 59 portable Studio assertions and the production TypeScript/Vite build passed.
- The 12 catalog regressions also passed on the supported Python 3.10 runtime.

Release archives are prepared locally with fresh checksums. No release was published and no Git changes were pushed.
