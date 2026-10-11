# Parallax adversarial audit

October 9, 2026. Seven agents audited backend, frontend, UI/UX, data/recovery, DevOps, QA and product. Integration and delivery tests ran in the isolated `Parallax-pilot-20261009` checkout, branch `codex/delegation-pilot`, based on `a83e8569b6547099035ac93ddb81ed51d55188e7`. All changes remain local and uncommitted. The original dirty `Documents/parallax` checkout, production and real GitHub repositories were not modified.

**Result: the deterministic implementation is substantially better protected, but paid-pilot acceptance remains incomplete.** October 10 continuation completed local container/recovery and rendered-browser checks; successful live providers, staged authorization/delivery and compatible Linux execution still require evidence. See [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md) for the current result.

## October 10 continuation

The public website now leads with installation/downloads while Studio remains at `/studio`. Final Python 3.10 discovery passed 448 of 449 tests with one Linux-only skip, and 26 final private-path/App/API connection checks passed on 3.13. Studio passed 35 adversarial handler checks, graph/diff tests and both deployment builds. Fresh wheel/plugin setup, final packaged/container asset/source identity, real container replacement/cold restore, and redacted staging preflight checks passed. Four dependency-ordered local review patches have focused boundary checks and exact source-replay manifests; see [review boundaries](REVIEW-BOUNDARIES.md).

Browser revalidation confirmed one task panel/feedback field across polling, fresh saved-candidate correction, reviewer handoff, peer approval, explicit simulated PR publication, reload and CI/review feedback. Dark/light website layouts fit at 320/390px. Two further rendered defects were corrected: mobile approval sizing was overridden to 36px, and expanded desktop publication feedback overlapped follow-up controls. Final renders verify 44px approval/publication targets and separated desktop panels. Screenshots and exact scope are in [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md).

The sections below preserve the earlier audit's evidence and limitations. Earlier browser/Docker blockers were resolved locally; their descriptions are historical, not current launch blockers. Default container namespaces still cannot enforce project execution and Build correctly refuses before dispatch. No real provider/GitHub/staging success, deployment or paid enrollment is claimed.

The final security continuation also corrected command access to custom server state and configured App-key files outside the original user-directory masks. Both command backends now protect registered private paths; Linux exposes explicit runtime/project paths from an empty root. Real native Engine/API/App-key canaries pass. The website's installation names were checked against public main: its existing Claude plugin is `parallax` 1.3.0, while this 1.4.0 saved-candidate workflow is an unpublished preview. Download copy and pilot-worker prerequisites now reflect that difference.

## Demonstrated defects and corrections

| Surface | Defects reproduced or established in the actual implementation | Correction and evidence |
| --- | --- | --- |
| Backend authorization | A removed member could replay a consumed invitation and rejoin. A disabled Owner's invitation still admitted members. Team pairing codes survived issuer demotion/logout. Shared-recipe PUT could create a chosen or foreign identifier. Reviewer choices ignored per-project grants. | Active membership/issuer and durable pairing-session authority are checked; recipe creation uses server IDs; project-specific authorized reviewers are returned. Six adversarial backend tests plus the existing account/team/worker suites. |
| QA dispatch | Personal queued work survived logout, session expiry and account disablement with modern and legacy workers. Repeated polling could replace an already-dispatched command's authority/fingerprint or its eventual receipt after role/project/base changes. Invalid recipe validation echoed submitted secret-shaped values. | Recheck trusted originating browser sessions before first dispatch; atomically persist one authorized dispatch and frozen context; keep eventual receipts and legacy payloads stable; refuse worker downgrade/revocation; sanitize validation errors. Thirteen QA methods include six session scenarios, restart, 16 concurrent polls and GitHub refresh races. |
| Data and recovery | Approval could be saved before graph launch and remain stuck on retry. Apply retries after pre-write interruption or verified rollback were refused. No-op application lacked a durable applied record. Publication reservation and exact bundle were separate writes. Concurrent duplicate starts/revisions were inconsistent. A revision racing approval could revive a superseded parent. Recipe versions and actor-bound retries needed stronger protection. | Same-operation checkpoint/recovery, atomic publication bundle reservation, durable no-op receipt, transactional rereads and actor/version checks. Seventeen tests inject interruptions at real durable boundaries and preserve unrelated developer edits/indexes. |
| GitHub recovery | After an interrupted publication had saved its commit, a remote branch rewind to the original base or removal could reach PR mutation before refusal. | Compare the current remote ref with the saved durable commit; refuse missing/changed heads before remote mutation. Three failing-before/passing-after adversarial tests; 11 GitHub tests total cover retry, scoping, head drift, exact files and signed/deduplicated webhooks. All HTTP responses are simulated. |
| Revision lineage | A second-generation correction counted its selected awaiting/approved parent as another active revision and refused the child. Superseded parents lost the correction action in Studio after failed children. | Exclude only the parent being atomically superseded while preserving sibling refusal; restore the parent action. Two Python regressions cover second-generation correction, restart, original baseline, immutable parent tree, fresh digest and staged index. Frontend regression covers superseded recovery. |
| Frontend state | Late account/machine/task responses restored old scope or overwritten current state. Recovery inputs and request IDs could change after interrupted operations. Apply failure offered execution resume. Role controls were briefly permissive before authority loaded. | Scope generations and remounts, response guards, stable durable retry identities, application retry controls, gated publication recovery, fail-closed controls and project-specific reviewer/binding choices. The real-handler harness has 33 passing adversarial checks. |
| Frontend rendering | Browser polling accumulated actual task sections, duplicated IDs and compressed unusable panels. A new measurement component and the task had the same sibling React key. | Prefix task/measurement keys and add a sibling-key regression. Rebuilt packaged/cloud assets and passed TypeScript/tests. The browser defect screenshot was saved; final rendered recheck became blocked by Chrome transport timeouts and a blank native capture, so browser success is not claimed. |
| UI/UX | Light-mode panels referenced nonexistent color tokens, inherited full-width checkboxes distorted controls, mobile consequential targets were too small, and hosted privacy wording understated what was mirrored. | Existing theme tokens, checkbox/native-select sizing, keyboard diff focus, 44px mobile targets, 16px mobile inputs, responsive header and explicit hosted-data copy. Earlier mobile inspection confirmed the decision footer is reachable through internal scrolling. Final repaired light/mobile renders remain to be rechecked. |
| DevOps | Deploy contexts allowed private-key/authentication/runtime files; container smoke checked little persistence. | Expanded Docker/Vercel exclusions, CI public credential canaries and disposable-volume smoke across three replacements. Assertions passed across three real native hosted processes. Docker daemon startup timed out; image/container/Linux behavior is unverified. |
| Product and measurement | Documentation conflated approval/application and current-project tasks/saved-candidate corrections. Privacy/provider prerequisites were inaccurate. Declines counted as approval latency; unknown runtime became zero; event pagination undercounted interventions. | Updated workflow/onboarding/privacy/recovery/manual pilot guidance; correct approval/unknown-time/count semantics. Three metric regressions plus data tests; 25 product documentation links checked. No measured productivity or cost claim. |

## Verification actually completed

| Check | Result |
| --- | --- |
| Complete Python test discovery | **430 discovered: 429 passed, one skipped, zero failures/errors; 275.513 seconds.** The skip is the live Linux bubblewrap canary on macOS. |
| Focused authorization/server suite | 73 passed, including the final dispatch/privacy changes. |
| Studio tests | Existing graph inspection (69 assertions), diff parser and **33 new adversarial frontend behavior checks** passed. This harness exercises actual handlers with controlled async responses; it does not replace a real browser. |
| Studio build and hosted helpers | TypeScript, packaged Vite build, hosted URL/session/routing checks passed. |
| Vercel output builds | Both default and Railway-backed cloud builds passed after the rendering fix. Their existing bundle-size warning remains, approximately 644 kB JS / 200 kB gzip. Earlier default/cloud builds also verified unchanged packaged static SHA-256 hashes. No deployment was performed. |
| Release/configuration | Release consistency validator, offline dependency-lock consistency, CI YAML parsing and `git diff --check` passed. |
| Hosted process recovery | 27 focused tests and all enhanced smoke assertions passed across three real OS processes sharing disposable persistent state. This is native process recovery, not a Docker result. |
| Loopback end-to-end HTTP | **18 assertions passed** across two real authenticated fixture sessions, worker/relay HTTP, two corrections, reviewer assignment, requester self-approval refusal, Reviewer apply/publish refusal, peer approval, preview, publication/retry, delivery receipt, CI/review feedback and unknown cost. Providers and GitHub were simulated. The fixture's developer Git tree remained clean. |
| Fresh live provider attempt | Codex/Claude discovery reported authenticated. The bounded task reached Claude's weekly quota before a candidate. It was stopped and its developer Git tree remained clean. This is a failed live outcome. |
| Final browser recheck | Incomplete. The pre-fix defect was visibly reproduced and captured. Chrome CDP/navigation timed out; native capture became blank. A wake/reconnect request is pending. |

Relevant local logs are under `/private/tmp`: `parallax-qa-final-full.log`, `parallax-adversarial-lineage-before.log`, `parallax-adversarial-lineage-after.log`, `parallax-adversarial-studio-tests-final2.log`, `parallax-adversarial-studio-hosted-final2.log`, `parallax-adversarial-studio-build-final2.log`, `parallax-vercel-default-final.log`, `parallax-vercel-cloud-final.log`, `parallax-pilot-http-acceptance.log` and `parallax-adversarial-live.log`.

The defect screenshot is `output/adversarial/duplicate-task-before.jpg`. It is explicitly a pre-fix screenshot, not proof that the repaired browser UI passed.

## Reproduce the local checks

Use the installed project virtual environment and Studio dependencies. On macOS the disposable check subprocesses need permission to invoke the native sandbox; denied outer-shell runs are not product failures.

```sh
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -v
npm --prefix studio test
npm --prefix studio run test:hosted
npm --prefix studio run build
node scripts/build_vercel.mjs
PARALLAX_RUNTIME_URL=https://runtime.example.com node scripts/build_vercel.mjs
.venv/bin/python scripts/validate_release.py
git diff --check
```

For the disposable full-flow fixture, start `PYTHONPATH=src:tests .venv/bin/python tests/pilot_browser_fixture.py`, open `http://127.0.0.1:8766/demo-session/owner` or `/demo-session/reviewer`, then run `PYTHONPATH=src:tests .venv/bin/python tests/pilot_http_acceptance.py`. The fixture uses a named disposable project under `Parallax-adversarial-browser-fixture`; it contacts no real GitHub repository. The HTTP walkthrough consumes the initial awaiting candidate; restart the fixture to seed a new one before repeating it.

## Remaining gates and limits

Use the proposed [staging acceptance setup](STAGING-ACCEPTANCE.md), the [pilot checklist](PILOT.md#launch-checklist), [DevOps audit](DEVOPS-AUDIT.md) and [product audit](PRODUCT-AUDIT.md) before enrollment.

- Actual staging URLs, a selected disposable repository and owner-authorized GitHub App configuration are still needed. Mock tokens/webhooks/PRs do not validate real integration.
- A successful live task needs available independent-provider quota. Authentication discovery is insufficient. Claude reported a weekly limit resetting October 11 at 8 a.m. America/Detroit; recheck availability then instead of assuming success.
- Run Docker image/private-file exclusion and Linux isolation checks with a working daemon. The native fallback cannot clear those gates.
- Reload the rebuilt browser, verify exactly one task section/feedback ID remains across at least two polling cycles, then finish desktop/light/mobile reviewer/publication/recovery screenshots.
- Reviewer choices may need reload after a project policy changes; the server rejects stale choices. Revoking a worker removes its relay mirror, so prior evidence must be recovered from preserved worker state. Operator bearer-key rotation retains its existing sessionless queued-command behavior; the new browser-session dispatch binding covers pilot account users.
- Actual support, retention/deletion, backup restoration, agreed participant terms and representative single-agent comparisons remain launch work. No self-serve billing or productivity claim was added.

No remaining reproduced authorization, crash-recovery or revision-lineage defect is known to fail the completed local suites. This statement is limited to the tested implementation and fixtures; it does not certify production or clear the live acceptance gates.
