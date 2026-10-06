# Studio UI validation

Validated 2026-10-06 against the local service and a read-only SQLite backup of the recorded four-provider acceptance run. The QA service never starts the engine and rejects every non-GET/HEAD request before routing. Public preview workspace labels use `/demo/parallax-acceptance`.

## Completed checks

- Native metadata: all four installed CLI providers reported ready; model and effort choices came from their actual catalogs.
- Keyboard: Alt+1/2/3 navigation; task selection with Enter; replacement-task navigation; graph zoom and fit controls; review tabs with Left/Right arrows.
- Connections drawer: initial close-button focus, Tab/Shift+Tab focus loop, Escape restoring prior focus, inert background and scroll-lock cleanup.
- API connection validation: malformed model JSON rejected; disposable custom local endpoint with a missing environment reference saved as credentials missing; testing disabled; explicit model loaded; unknown effort control disabled/default; launch blocked; disposable connection removed and native coordinator restored. No key or API inference was used.
- Run validation: invalid command argument JSON and out-of-range worker count prevented launch.
- Actual run evidence: three recorded task nodes, dependency and dashed repair edge; original failed outcome and resolution review retained; recorded diff contains `maths.py` and `stats.py`; supplied acceptance check reports exit 0 and eight passing tests; effective model, effort, limits and provider-session records visible.
- Responsive layout: dark/light Team, dark Connections, light Run empty state, and recorded graph with stacked inspector checked at 390×844. Document width remained 390px with no horizontal overflow. Temporary viewport and appearance overrides were restored during completed checks.
- Desktop verification panel: receipt state/outcome, five gate rows, JSON/patch links and coverage text rendered from the backend receipt; fingerprint disclosure is available. The initial historical snapshot correctly showed preservation as unknown. The preview now serves the genuine final verification JSON for the matching completed run, with all five recorded gates passed after the application-journal recheck.
- Evidence integrity: downloaded patch SHA-256 matches the receipt patch hash.
- Production build, TypeScript, Prettier and npm audit passed; npm reported zero vulnerabilities.

## Final root visual check

Root Playwright confirmed the final Verification panel at 390×844. Document width is exactly 390px; both download controls stay inside the viewport. All five gates are readable in the single-column layout. Desktop dark and light screenshots were visually inspected. The preview serves the exact final native-demo record and blocks mutations; it does not simulate provider activity.

## Captured release evidence

- [Team](studio-team.png)
- [Task graph](studio-run.png)
- [Verification record](studio-review.png)
- [Light mode](studio-review-light.png)
- [Mobile verification gates](studio-verification-mobile.png)
- [Full mobile Review](studio-review-mobile.png)

The native acceptance record was finalized after reconciliation against the committed integration journal and actual destination bytes. Its patch hash matches the downloaded patch. Older runs without that evidence retain unknown preservation status.
