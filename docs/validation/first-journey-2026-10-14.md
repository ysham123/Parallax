# First task journey review

Checked on October 14, 2026, on macOS, in the isolated `codex/first-journey-20261014` checkout. The initial baseline was `63c919e5893b260d61cd0589e8988ed4fd7ea6bb`. The owner subsequently authorized commits, pushes to `main` and continued work. Launch posts remain drafts.

## What changed

Website copy, the README and [post drafts](../LAUNCH-POSTS.md) use `/yosef-voice` and `/ai-to-human`. The [first-task guide](../FIRST-TASK.md) follows one local exercise through installation, task setup, evidence inspection, approval and application. It names the current Studio controls and gives commands that share the same disposable project path.

The homepage defaults to the pinned source route. Its preview note appears before the install commands. The current [Claude marketplace](https://github.com/ysham123/Parallax/blob/63c919e5893b260d61cd0589e8988ed4fd7ea6bb/.claude-plugin/marketplace.json) names `parallax-team`, and the [Codex manifest](https://github.com/ysham123/Parallax/blob/63c919e5893b260d61cd0589e8988ed4fd7ea6bb/.codex-plugin/plugin.json) carries 1.4.0. Install copy now matches those manifests. Public source availability is described as a development preview, with live pilot acceptance still required.

The setup guide link follows `main`. The source download, example and platform guides stay pinned to a checked preview revision. Bundled Studio assets were rebuilt to include the changes. The homepage's **Open local Studio** link now opens `/local` even on a deployment with a hosted runtime; the existing `/studio` and authorization routes retain their hosted behavior. The Claude manifest's support and legal links use the working Vercel site.

The source download and installation commands are pinned to `c2127aec7f4acc571247fafe8a7b4b5e47647e97`, which includes this journey polish and the quota fixes. The subsequent website commit refreshes that pin and its generated assets, and ignores local Vercel metadata.

## Checks completed

- A fresh private state directory installed the hash-locked Python dependencies and `python3 scripts/parallax.py --version` reported `Parallax 1.4.0`.
- The hosted and local Studio builds passed TypeScript checking and Vite compilation.
- The existing worker setup harness passed all 33 checks. Its preview copy assertion was updated to retain the operator-approved-build requirement.
- Hosted URL, session and Vercel routing checks passed; all three pricing parser checks passed.
- The complete Studio test suite passed. The 48 engine, provider diagnostics and release tests passed, as did 19 quota tests and 29 quota/memory tests (these groups overlap).
- Native Claude session-limit wording is classified as provider quota. A whole-engine fixture stops after one implementation attempt, preserves the project and staged work, offers explicit recovery, and makes no post-run memory request. A reported local clock reset is tied to the failure timestamp and expires correctly. Transient rate-limit codes retain their existing retry behavior.
- `scripts/validate_release.py` passed manifest, marketplace, launcher, lock, skill and bundled-asset consistency checks.
- `git diff --check` passed.

The homepage was inspected visually in headless Chromium and audited with axe-core 4.13.0 using its default rules. Pricing was unset for these checks.

| Viewport | Theme | Axe violations | Horizontal page overflow |
| --- | --- | --- | --- |
| 1280 × 900 | Light | 0 | None |
| 1280 × 900 | Dark | 0 | None |
| 320 × 900 | Light | 0 | None |
| 320 × 900 | Dark | 0 | None |

The mobile menu's theme control was used to switch themes. Audits ran after the color transitions settled. The install link, default source panel and preview instructions were checked in both widths. The `/local` launcher also had zero axe violations and no page overflow in all four viewport/theme combinations. A remote Studio URL was rejected without an outgoing request or storage of its token. Screenshots and the disposable fixtures are retained in the checkout's ignored `output/playwright/` folder. Automated rules do not establish complete WCAG conformance.

## First task result

The browser walkthrough used the real local runtime and bundled `examples/first-change` exercise with **simulated providers**. It did not call a live model, use a production workspace or contact GitHub for delivery.

1. The baseline ran two unchanged tests: one passed and the empty-input case errored with `ZeroDivisionError`.
2. Studio's **New task** captured the requested fix, two simulated independent providers, and the explicit test command. **Check readiness** reported no setup issues.
3. **Start task** produced a saved candidate with a one-file diff, recorded baseline and final command output, and simulated independent reviews. Both tests passed on the candidate.
4. Before and after **Approve candidate**, the original `average.py` and supplied tests were byte-identical to the baseline, and the project had no tracked diff.
5. **Apply locally** applied the approved patch. A separate local test run passed both tests. The Git diff contained only two added lines in `average.py`; the supplied tests were unchanged.

Fixture workflow: `010021ff-9972-493e-8169-4aaf5a838b4f`. This verifies interaction and local check execution. Live provider quality, fresh-Mac installation, account isolation, real team approval and GitHub App delivery remain outside this result. Follow [PILOT.md](../PILOT.md) and [STAGING-ACCEPTANCE.md](../STAGING-ACCEPTANCE.md) before enrollment.

## Live provider attempts

The same disposable exercise was attempted with the signed-in native CLIs and their own default model settings. Neither attempt produced an approvable candidate. Sign-in readiness did not establish available quota.

- **Codex and Claude:** Claude reported `You've hit your session limit` with an 8:30 p.m. America/Detroit reset. The old classifier treated it as configuration and allowed three failed implementation attempts before the coordinator turn limit stopped work. That observed message is now covered by the quota regression described above.
- **Codex and Antigravity:** Antigravity reported exhausted individual quota with a reset about 92 hours away. The existing guard stopped after one implementation attempt and retained the baseline and error. This run exposed a redundant post-run memory request; quota stops now skip that request while keeping the local execution evidence.

Both source projects and the supplied test files stayed unchanged. No approval or application was recorded for these failed live attempts. Account capacity still blocks a live successful first-task run; the simulated walkthrough must not be reported as live model acceptance.

## When the owner supplies prices and Polar details

1. Set `PARALLAX_PRICING` as a Vercel **build** variable using the JSON fields in [PLANS.md](../PLANS.md). Use approved prices and an HTTPS checkout URL. Its free task allowance must match the runtime's configured allowance.
2. Set `ORGANIZATION_ID` and `UPGRADE_URL` in `src/parallax/license.py` to the supplied Polar organization and upgrade destination.
3. Rebuild with that configuration and repeat desktop and 320px checks in both themes, including the rendered pricing section, with axe reporting zero violations. The current no-pricing audit does not cover that future build.
4. Deploy only after the configured build passes those checks. The owner's continuing authorization permits pushes to `main`; publishing launch posts still needs specific approval.
