# Frontend redesign validation

Updated October 12, 2026. Research and compared prototypes preceded implementation. This is a locally verified development preview; it has not been pushed, merged or deployed as the redesigned production website.

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

## Task canvas and contextual records

The next slice compares a compact chooser with an on-demand version of the existing task browser. The latter preserves project/status filters, search, archive and unavailable-count states without adding another modal. Task list or Review queue opens alongside the candidate at wide widths and occupies the work surface below 1180px. Explicit selection closes it; background inbox reconciliation does not. The selected task remains mounted. Closing the browser returns keyboard focus, and delayed navigation cannot replace a newer task or steal deliberately moved focus.

Pilot measurements and human assessments now open from the task's Details tab. They make no measurement-only reads before first disclosure, retain unfinished values across collapse/tab navigation, and bind permissions to the selected project's current access. Comparison recording requires delivery permission; human labels use review permission. The task browser retains an explicit worker report disclosure when no task is selected. Unknown cost, observation identity and idempotent retries retain their existing meaning.

The new suites pass **45 task-browser handler checks and 17 contextual measurement checks**. Full frontend and hosted suites passed before the final deferred-export guard; measurement, task-browser, product and adversarial suites passed again after that guard. TypeScript, local/cloud/hosted production builds, release consistency and whitespace checks passed. Independent review reproduced a late report download after the originating view was removed; the final guard suppresses Blob creation, download and stale notices after unmount/task change, while an explicit current download still succeeds. No backend implementation changed.

Guarded browser checks used a frozen simulated fixture at port 8828, with both themes at 1440, 1024, 390 and 320 CSS pixels. Search/Escape/selection, New task/back, archive and actual mounted measurement/form retention passed. The initial 1024px pass found a workspace/role label compressed into individual letters beyond the header. The final build reflows header controls and allocates the desktop task canvas from the header's actual height. Root checks on a separate frozen fixture at port 8830 passed at 1440×1000, 1024×768 and 768×390: the scope stayed inside its header, the task toolbar started below it, and the document had no horizontal overflow.

The final build also passed an independent 390/320px check in both themes, with no horizontal document overflow or header overlap. The settled Reviewer view exposed the human-label form and permitted approval, with no New task, setup inspection, comparison recording or delivery controls. Those consequential actions were not selected. The two independent request logs contain 296 and 176 GET/HEAD requests, with zero writes or blocked attempts. Read-only inspection of both disposable worker/relay databases confirmed awaiting-approval candidates, no human decisions/publications, zero workflow operations and zero setup observations. Browser 200% zoom, a populated archive and real external inbox updates were not exercised in this pass.

At 1440×1000, the default task canvas grew from 964 to 1222 CSS pixels, while the code region measured 916.5 pixels in the final fixture. The removed rail was 258 pixels wide; this is not a claim that code gained all 258 pixels because the file chooser also takes proportional width. The permanent measurement/status footer is gone. These are layout measurements, not productivity or usability outcome evidence. Mobile first-hunk depth remains a separate refinement.

The fixtures use simulated providers, identities and GitHub. Browser inspection forbids non-GET/HEAD requests and does not select Start, approval, application, publication, pairing, measurement submission or report download. Artifacts are retained under `output/playwright/round5` and the independent report under `output/redesign/round5`. These checks do not establish live acceptance, scale or complete accessibility conformance.

## Mobile evidence and read recovery

This slice compared a compact decision/evidence summary with moving the decision below the patch. The compact summary was selected to keep blockers and permitted actions visible before inspection. Final checks, independent review and human decision remain above the evidence tabs. Candidate narrative, full digest, file count and supporting run records move into **Candidate details**. Current failures, uncertainty and material delivery facts remain outside it. Code font size and exact patch rows are preserved.

Against the same settled Owner fixture, the first hunk moved from 810.97 to 660.77 CSS pixels at 390px width and from 821.97 to 680.27 at 320px. This is 150.20 and 141.70 pixels earlier, respectively. The 390px view fits all four sample patch rows; the 320px view exposes the hunk and two rows, with the rest reachable by scrolling. These are measurements of this fixture, not proof that all patches fit above the fold or that users work faster.

The bounded independent browser pass covered both themes at 1440, 1024, 390 and 320px without document overflow or header overlap. Candidate details works by keyboard and retains its state through evidence-tab navigation. Task and measurement components remain mounted, preserving entered values. Reviewer evidence and permitted approval remain accessible without creation or delivery controls. No approval or other consequential action was selected.

Run read state is now separate from recorded outcomes. Initial loading does not invent missing checks, review verdicts or a zero-file patch. Initial failure and mismatched run identity report unavailable evidence. A failed refresh retains qualified last-loaded evidence and blocks approval, including while Retry is pending. Ordinary background polling preserves stable labels and layout. Snapshots bind synchronously to workflow, run, candidate digest and viewer, and delayed responses cannot cross those identities. Successful retry restores a disappearing Retry button's focus to the active evidence tab, while preserving deliberate focus moves. Existing legacy saved-gate approval semantics remain unchanged.

The new evidence suite passes **27 focused checks**, including actual handlers with controlled deferred responses, identity replacement before effects, current verification attempts, offline state, retry focus cancellation and legacy compatibility. Full frontend and hosted suites, TypeScript, local/cloud/hosted builds, release consistency and whitespace checks passed. Navigation tests now locate the Changes fact without relying on its former text adjacency; fake product run responses use the real `run_id` contract. No backend implementation changed.

Root browser checks deliberately held or replaced only run GET responses. They verified initial loading/failure/retry/success, stable ordinary polling, failed refresh and pending retry, focus return/no focus theft, wrong-run rejection and loaded-but-unrecorded presentation. The empty successful body is an intentionally inconsistent modern presentation fixture, not an acceptance test. It cannot establish server approval behavior. After visual review found the premature zero-file badge, the final build received a bounded loading/count/recovery smoke check on a new frozen fixture; the independent full layout matrix used the preceding build, whose healthy layout is unchanged.

All browser contexts used GET/HEAD guards. Read-only inspection of both disposable worker/relay databases confirmed awaiting-approval candidates, no human decision or publication, zero workflow operations and zero setup observations. Plans, sanitized request logs, screenshots and reports remain under `output/redesign/round6` and `output/playwright/round6`. Providers, accounts and GitHub are simulated; this pass does not establish live acceptance, browser zoom behavior, complete accessibility conformance or customer outcomes.

## Contextual GitHub connection

The next first-use audit found that the repository's GitHub action opened a long workspace panel without retaining its machine/folder, lookup failures were swallowed, and an interrupted binding save could insert a duplicate. An inline connection form was selected over another full-screen wizard. It keeps the selected project visible, loads connection information only when opened, exposes read errors and retry, and separates authorization, repository selection and explicit connection. Workspace settings uses the same repository entry. The project-management action is now named **Manage project access** to describe its actual behavior.

Current account/workspace/project permission is rechecked before authorization or binding. Scope generations invalidate older pending actions even after going offline and back online or changing away from and back to the same project. Installation reads are sequenced; old selections cannot replace current repository choices. Optional authorization-return context expires and never authorizes an action. Saving a connection refreshes the mounted task composer's delivery choices, with older reads unable to overwrite the new list.

The relay accepts an optional binding request UUID. An additive operation journal binds it to actor, workspace and exact payload; the binding and journal commit atomically. Every retry rechecks current session, Owner permission, worker/project access and selected GitHub repository. Legacy requests remain compatible. New UI requires the advertised retry capability. Personal account deletion removes its journal without deleting team records.

**49 new frontend handler/helper checks and 21 new backend tests passed**, along with the full frontend/hosted suites and 60 existing GitHub, team and account tests. The new tests cover concurrent/restarted saves, rollback, changed IDs/actors/destinations, revocation during remote reads, stale selection and preflight responses, reconnect cycles, returned-body mismatch, authorization redirect handling, and expired/malformed/unavailable tab storage. Independent source review found no remaining blocker in this slice. TypeScript, local/cloud/hosted builds and release consistency passed.

Guarded browser inspection covers 1440/390/320px in both themes, exact project context, current connection visibility, Owner/Reviewer controls, settings handoff, error/empty states and focus on Close/Escape. The initial pass found 11px inherited input text; the final connection controls and labels use an explicit 14px minimum, verified on a fresh fixture. A synthetic authorization-return marker with scoped tab context restored the same project and made no automatic write. It did not perform a real GitHub authorization exchange.

One root browser pass deliberately permitted a single binding POST to a disposable fixture with simulated GitHub. The new `qa/connection` base appeared in the task composer's Delivery options; no task was started. Database inspection distinguishes that intended binding/journal from unchanged workflow, approval, setup and publication records. Other visual contexts remained GET/HEAD-only. Reports and sanitized artifacts are under `output/redesign/round7` and `output/playwright/round7`.

This completes the locally implemented connection slice, not repository import or live acceptance. Real App authorization, provider execution, account onboarding/revocation and signed installers remain release gates. Next concrete product gaps are scoped reviewer handoff and contextual task recovery; worker-side cloning still needs an approved destination contract.

## Public bundle loading

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
