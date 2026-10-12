# Frontend redesign validation

October 11, 2026. Research and compared prototypes preceded implementation. This is a locally verified development preview; it has not been pushed, merged or deployed as the redesigned production website.

## Result

The public site now uses the selected Perspective identity: locally bundled Archivo and Plex Mono, original offset-plane mark, light default with saved dark preferences, a readable patch and second review perspective, and an installation selector. Account access is visible when configured; local installation does not need an account. Public 1.3 tools, the supplied 1.4 preview, unsupported transports and unavailable native downloads stay distinct.

Studio has one labeled navigation: Tasks, Repositories, Review inbox and Settings. Repositories use the current worker's authorized folders and separately scoped GitHub delivery bindings. Approval and pending delivery have distinct queues. Current evidence and permitted next action precede activity; run identity and supporting records remain inspectable. Single-file mobile diffs omit a redundant chooser. Ordinary text patch headers are optional; binary, rename, mode and unrecognized metadata remain visible. Finding navigation and raw patch downloads retain exact rows and bytes.

Team advanced views now match server permissions. Legacy direct runs, run controls, recovery, profiles and feedback cannot be initiated through a team interface. Teams use recorded workflow operations. The legacy graph remains inspectable; personal legacy controls retain their previous behavior. Handler guards also use current scope when an older callback is retained.

The researched first-use slice now presents **Prepare your machine → Connect it** instead of four simultaneous instruction blocks. Platform choice is manual; Windows and experimental WSL2 expose guides without a worker command or pairing control. macOS/Linux guidance distinguishes the supplied preview from public local tools. Pairing retains its existing expiry and errors. Connected/offline machines bypass installation guidance, and non-managers retain the Owner handoff. Stage transitions and the real connection handoff preserve focus without claiming provider/check readiness. Team onboarding names the selected team rather than substituting the account name.

## Checks run

- Full `npm --prefix studio test`: graph inspection, diff parsing, adversarial frontend, product behavior, review/location navigation, desktop connections/navigation, new repository/decision and legacy authorization suites passed. The focused suites contain 24 repository/decision/diff checks and 38 legacy authorization checks.
- The added worker setup suite passed 33 checks covering platform/stage handlers, no automatic requests, role handoffs, connection focus, original-state recovery, actual pairing expiry/failure and unchanged command/copy behavior. The full frontend and hosted suites passed again after integration; local, cloud and hosted builds passed.
- `npm --prefix studio run test:hosted` passed.
- Five new backend boundary tests passed with the standard-library unittest runner. They cover all team roles, authorization refresh and queued role downgrade. No backend implementation changed.
- TypeScript, local production build, hosted build and cloud build passed. Vercel build output was prepared locally without deployment.
- `scripts/validate_release.py` passed. Graph libraries are split so every non-exempt artifact remains under the plugin directory's 256 KiB file limit. Original font licenses ship with the assets.
- Independent browser checks at 1440, 390 and 320px covered installation keyboard navigation, copy failure/retry, public offline fallback, mobile menu focus, synchronized theme controls, reduced motion, repository setup focus, task composition, role permissions and bounded code scrolling.
- Delayed and failed Studio chunks produced a readable loading/error state; Refresh performed a full reload and recovered. Ordinary public page inspection had no console errors. Injected failure tests produced expected diagnostics.
- A real loopback server fixture exercised Owner self-approval refusal, peer approval, separate draft publication, a published-candidate revision with a selected finding, fresh checks/review and a new required approval. Persisted records confirmed original source identity, recipe/settings, goal and publication lineage; the developer's disposable project stayed unchanged. Provider and GitHub behavior in this fixture is simulated.
- Local authenticated Studio and its authorized repository view loaded from the prebuilt production assets. The public hosted launcher and preserved graph/evidence views were inspected separately.

The original UI issues found during review were corrected: vertical public navigation, overlapping patch annotation, ambiguous diff context, invisible copy failure, missing mobile theme control, stale theme labels, excessive mobile summary height, lost focus on dialog/composer close, and team controls for unsupported legacy operations.

An additional browser audit intended to perform only reads and navigation, but a real peer-approval operation was associated with that audit tab. Durable records show the permitted Reviewer actor and one approval; no local application or publication followed. Source inspection found no implicit approval path, but the original interaction had no action trace, so its initiating event remains unknown. The earlier assertion that the fixture was untouched is withdrawn. This does not invalidate the separate role visibility and deterministic authorization checks; it does limit that browser pass. Future inspection uses isolated contexts, semantic targets and a guard against consequential writes. Details are retained in `output/redesign/qa/APPROVAL-TRACE-INCIDENT.md`.

The affected navigation sequence was repeated on a fresh fixture in an isolated headless context with a write guard and action/network trace. Reviewer and Owner legacy handoffs reached the correct task views; team graph controls remained unavailable and no Machines dialog appeared. The trace contained 67 API GETs and no consequential requests. Read-only database inspection confirmed the candidate still awaited approval, with no decision or workflow operation. This repeat did not reproduce the earlier interaction and does not explain its cause.

Independent setup QA found and corrected two keyboard failures: pairing's pending/error state lost focus, and reconnection removed the focused offline control. The final frozen build retained pairing focus while pending, refused duplicate activation, preserved deliberate focus moves and moved disappearing reconnect-control focus to the modal Close button. Desktop/mobile role and platform states passed. Its guarded trace contains two intentional synthetic pairing refusals and no task operations; read-only worker/relay inspection confirmed no approval or delivery. Positive pairing behavior is covered by controlled handler tests, not claimed as live onboarding.

## Continuous project setup

The next researched slice keeps project setup in the existing task composer. Paired project choices use current worker grants; historical folders remain only in history filtering. The setup action is explicit, with actual issues above the task and the detailed check plan below it. Inspection language states its scope: checks have not run, and inference/quota remain unverified. Reviewer entry bypasses creation/setup controls.

Both inspection and Start refresh permission before sending their POST. The current rendered account/workspace and first accepted context bind the UI identity; an account/workspace change requires a reload, even if both actors have identical project grants. Delayed permission and assessment responses cannot cross worker, project, settings, offline/reconnect or activity changes. Server authorization remains authoritative.

Reconnect and provider-settings navigation preserve the draft rather than restoring recipe defaults. When the catalog advances, the captured draft version remains explicit; adopting the newer version is a deliberate choice. Generic New task clears a prior linked-follow-up relationship. Start request IDs still survive unchanged uncertain retries.

The full frontend suite now also includes **17 preflight presentation/adoption checks** and **50 setup/authorization and focus-return handler checks**. These exercise actual component handlers with controlled promises, including revoked roles/projects, changed session identity with equal grants, initial rendered-identity mismatch, stale callbacks, same-key reconnect, duplicate inspection, draft/version preservation, independent-task reset, legacy local compatibility, delayed dialog return, revoked-access focus fallbacks and deliberate focus preservation. Full frontend/hosted tests, TypeScript, local/cloud/hosted builds and release consistency passed. No backend implementation changed.

Independent guarded browser checks exercised blocked and successful setup inspection at 1440, 390 and 320 CSS pixels, with no horizontal document overflow. They verified permitted repository continuity, version labels, preserved drafts, visible setup blockers, and Reviewer entry without creation/setup controls. Pending inspection retained keyboard focus. Two focus regressions were reproduced and corrected: repository entry now focuses the task field after refreshed permission, and closing provider settings returns to its original control after that refresh. The latter passed on a final frozen build with a read-only browser guard.

Each of the two inspection fixtures recorded one deliberate setup-assessment POST; the final dialog fixture recorded no writes. Read-only database inspection confirmed zero workflow operations, unchanged awaiting-approval candidates and no decision or publication in all three fixtures. The successful inspection recorded one setup observation. Providers, identities and GitHub in these fixtures are simulated; these checks do not establish live onboarding or task acceptance. Scoped screenshots, sanitized request logs and the independent report are retained under `output/redesign/round4/qa`.

## Loading evidence

The initial redesign build placed about 711 kB of JavaScript in one bundle. The final setup build's public page requests two JavaScript assets totaling about 246 kB before compression, while Studio and graph chunks load for the working interface. Browser resource inspection confirmed that the public page did not request those chunks or `/api/session`. These are build/network observations, not a production speed, conversion or productivity claim.

The implementation follows [React's lazy-loading contract](https://react.dev/reference/react/lazy) and [Rollup's explicit chunk configuration](https://rollupjs.org/configuration-options/#output-onlyexplicitmanualchunks). The homepage stays eager; only working interfaces are deferred. Existing callback/invitation route detection is reused.

## Reproduce

From the repository root:

```sh
npm ci --prefix studio
npm --prefix studio test
npm --prefix studio run test:hosted
npm --prefix studio run build
python3 scripts/validate_release.py
PYTHONPATH=src:tests python3 -m unittest test_legacy_team_authorization
```

Use the locked runtime environment for Python. To inspect the simulated browser fixture, first build cloud assets from `studio` with `npx vite build --mode cloud`, then run:

```sh
PYTHONPATH=src:tests python3 tests/pilot_browser_fixture.py \
  --port 8810 --root /private/tmp/parallax-redesign-inspection \
  --state-name inspection
```

Use a new disposable root, and open `/demo-session/public`, `/demo-session/owner` or `/demo-session/reviewer` on that loopback origin. These are test accounts, not deployment sign-in. Review artifacts are retained under the ignored `output/redesign/qa` directory. Use separate noninteractive browser contexts and record deliberate consequential actions; visual inspection should refuse such requests.

## Remaining product acceptance

These results do not establish live model-provider execution, genuine account isolation/onboarding, real GitHub App publication/webhook recovery, installer signing/notarization, fresh-device setup, complete accessibility conformance or customer outcomes. The invited pilot remains closed until its live acceptance checklist passes. Existing operator setup requirements remain the route to those checks; secrets belong in the configured services or local keychain, not documentation or chat.

Online accounts remain part of the product direction. Newsletter enrollment, billing and automatic deployment were not introduced in this redesign.
