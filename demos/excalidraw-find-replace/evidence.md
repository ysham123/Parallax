# Live demonstration evidence

Upstream: `excalidraw/excalidraw`, commit `2df993fb397dd6d64625908c9c10337727617f6f`.

## Before implementation

- Frozen Yarn install completed locally using Yarn 1.22.22.
- TypeScript: `node node_modules/typescript/bin/tsc --noEmit` passed.
- Upstream regression suite: `node node_modules/vitest/vitest.mjs run --maxWorkers=2 --minWorkers=1` passed 2,482 tests across 142 files, with 47 skipped and one todo. The initial attempt with only maxWorkers failed before collection because Vitest's default minWorkers conflicted; corrected bounds were used for the actual baseline.
- Independent harness relocation: the original five search tests passed when executed from private temporary storage against the actual application. The acceptance bootstrap's minimum-ten-tests safeguard deliberately rejects that smaller calibration suite.
- 214 existing upstream test/configuration/manifest inputs are recorded in `acceptance/protected-upstream.json`. Real acceptance checks verify these hashes before testing the candidate.

- Acceptance calibration (October 12, 2026): the first baseline run failed all 16 tests, including ordinary search, for harness reasons rather than missing features. jsdom measures the editor as 0x0, so upstream search (which focuses only visible matches) focused nothing for elements away from the origin; and upstream keeps its search debounce and focused-match index at module level, so a search from a previous test's editor could leave that index set. The harness now gives the editor a stable 1280x800 bounding box and clears the query through the real input before each measured query. Three consecutive baseline runs against the unmodified clone (acceptance sha256 `f814ee5c2b470e9259f01a440c762193c9235e9b5dcef2b0676e702bf969fd21`, 214 protected inputs verified) each passed ordinary search preservation and failed the other 15 tests at the missing "Replace with" control, which is the expected pre-implementation state.

These host setup checks precede the run. They do not substitute for Parallax's own isolated baseline and final checks.

## Live provider attempts

1. Read-only architecture preflight `f1b86820-c312-4ddc-9947-41ca6b5e422e`: Antigravity (`gemini-3.8-flash-high`) used repository read tools but exceeded its 240-second attempt limit. The runtime recorded `needs_attention`, no successful verdict, no candidate and no application. Raw local evidence remains under `output/showcase/`.

2. Build run `36b311ef-ff88-4fca-804a-533ff93bebd6` (October 12, 2026, 74 minutes, runtime from branch `claude/yarn-classic` with Yarn Classic provisioning, integration disabled). Coordinator and implementer: Codex `gpt-6.1-sol` (high). Independent reviewer: Antigravity `gemini-3.8-flash-high`. Limits: 1 worker, 1 repair, 12 coordinator turns, 1800 s per attempt, 150 minutes.
   - Baseline inside Parallax isolation, after a fresh private frozen-lock Yarn install: acceptance 1 passed and 15 failed at the missing "Replace with" control (as calibrated), typecheck passed, upstream regression passed.
   - Codex completed `safe-find-replace` (SearchMenu, its styles, English locale, a new `searchReplacement.ts` and a new focused test) and one repair task, `repair-replacement-history`. Antigravity approved both task-level reviews.
   - Final checks: independent acceptance 15 of 16 passed; "commits Replace all as exactly one undoable edit including geometry and frame names" still fails because undo does not restore the exact previous scene. Typecheck failed on the agent's own new test (`searchReplacement.test.tsx(117,32): Type 'true' is not assignable to type 'false'`). Upstream regression passed: 143 files, 2,496 tests, 47 skipped, 1 todo.
   - The combined integration review could not run: Antigravity returned "Individual quota reached", resetting in about 150 hours. The coordinator then reached its decision limit and the run stopped as `needs_attention` with work and evidence preserved. No candidate was approved or applied, and the clone is unchanged.
   - The run cannot resume: it spent all 12 coordinator turns, so recovery offers only a new run with adjusted settings. It was started as a direct run, not a workflow, so the saved-candidate revision path does not apply either. `output/demo/launch_next.py` starts the same request, checks and frozen acceptance suite with 16 coordinator turns and a named reviewer.
   - The next run needs an independent reviewer with capacity. Claude Code requires a native sign-in on this Mac; Antigravity's quota returns around 18:02 UTC on October 18; native Grok is refused by Parallax's isolation policy.
   - Product fixes from this run (same branch): a reviewer reporting exhausted quota is now skipped in favor of the next independent provider, and when none is left the run stops at once with a `provider_quota` recovery category instead of spending coordinator turns. Recovery also no longer reports a post-run memory failure as the stop cause, which this run's record did.

3. Build run `66921c92-1fb9-4f91-9539-b6b8526c5498` (October 12, 2026, 24 minutes, runtime with the reviewer-quota fix). Same request, checks and frozen acceptance suite, 16 coordinator turns, Antigravity as reviewer. A one-line Antigravity request succeeded beforehand, so a small probe does not establish capacity for a full review.
   - Codex completed `safe-search-replacement` (SearchMenu, its styles, English locale, `searchReplacement.ts` and a focused test). The task review then returned "Individual quota reached", resetting in about 144 hours.
   - The run stopped after 2 coordinator turns with `provider_quota` and "Resume after restoring capacity", instead of spending its remaining turns. The implementation is saved and resumable; no final checks ran, nothing was reviewed or applied, and the clone is unchanged.
   - Next step: resume this run once an independent reviewer has capacity (Claude Code sign-in, or Antigravity around 18:02 UTC on October 18).

4. Build run `aaffee71-7a19-4ed8-b6a8-03cbf122f385` (October 12, 2026, 78 minutes, runtime that also passes the login name so Claude Code's sign-in is found). Coordinator and implementer: Codex `gpt-6.1-sol` (high). Independent reviewer: Claude `sonnet` (high). 16 coordinator turns allowed, 15 used.
   - The first final validation failed because the disk was full during the private Yarn install. Removing the dependency caches of the two settled runs freed space, and the coordinator validated again.
   - Final checks then failed (acceptance, typecheck on the agent's own test, upstream regression). Claude rejected the first repair and approved a second repair that restores replacement geometry through the editor's history.
   - Final result `completed`, verified and not applied: independent acceptance passed, monorepo typecheck passed, upstream regression suite passed. Claude approved the combined review. Patch `verified.patch`, SHA-256 `a28b902c…79da5`, 10 files.

## Browser acceptance

`browser/accept.mjs` drives the real editor (Vite dev server on a disposable copy of the baseline plus the verified patch, dependencies installed offline from the run's private cache) in headless Chromium 1217 at 1280x800. The scene is built through the UI and the feature is used through its visible controls; the development test hook is read only to verify scene state.

Run `aaffee71`: 12 of 12 behavior checks passed (`browser/aaffee71/results.json`). Case-insensitive search found all 4 occurrences and announced the locked one; Replace all was literal for `$&` and `$1`, kept element IDs, skipped the locked text, regrew text geometry and reported the result; one undo restored the exact previous text and widths, one redo restored the replacement; Replace changed only the focused occurrence; view mode kept search and disabled replacement; no page errors.

Screenshots show two presentation defects the code-only review did not catch: the Replace and Replace all controls use icon-button styling, so they lack button chrome, "Replace all" wraps and "Replace" overruns the panel padding; and status copy does not pluralize ("1 protected results"). These were not fixed by hand. They were handed to a focused follow-up Parallax run on the committed candidate, with every configured check still required.

5. Follow-up run `38bdd816-d27d-4a8f-83f1-41d5f48d6fdd` (October 12, 2026, 15 minutes). Workspace: a disposable repository at the baseline commit plus the verified `aaffee71` patch as one commit. Codex implementer, Claude `sonnet` reviewer, 10 coordinator turns allowed, 5 used. The request named only the two browser findings and forbade changes to replacement, history, delta or store logic.
   - Codex changed `SearchMenu.tsx`, `SearchMenu.scss` and `en.json` only (text buttons with Excalidraw's filled-button styling, singular and plural strings). Claude approved the task and the combined review.
   - Final result `completed`, verified and not applied: independent acceptance, monorepo typecheck and upstream regression suite all passed. Patch SHA-256 `1167d9f1…84fa0`.

Final browser acceptance on the baseline plus both verified patches: 14 of 14 checks passed (`browser/final/results.json`), adding single-line, in-panel button layout and singular and plural wording to the earlier checks. Screenshots in `browser/final/` cover the scene, search and replacement, Replace all, undo, dark mode with keyboard focus, and view mode. A paced 28-second recording of the same run is kept locally at `output/demo/browser/final/walkthrough.mp4` (not committed). The combined candidate is `output/demo/combined-candidate.patch`, 10 files, SHA-256 `46da2c52…71f76`.

The candidate is verified and browser-accepted but not applied: delivery into a real checkout needs explicit human approval. Provider cost is unknown. Provider cost is unknown.
