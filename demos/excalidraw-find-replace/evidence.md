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

Implementation, independent final review, browser acceptance and delivery are not yet complete. Provider cost is unknown.
