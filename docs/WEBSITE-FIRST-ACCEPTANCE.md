# Website first, Studio retained

October 10, 2026. The selected direction is a public website focused on explaining Parallax and installing/downloading it, with Studio available for tasks and review. All implementation remains local in `Parallax-pilot-20261009`. No release, push, production deployment or enrollment occurred.

## Implemented experience

- `/` renders the public website in both standalone and connected builds. Installation does not wait for a session, machine or relay. Optional authentication configuration can fail or time out without hiding the website.
- `/studio` opens the local authenticated-link launcher in the standalone build, or the workspace in the connected build. Successful sign-in, email confirmation and OAuth callbacks return to `/studio`. Existing invitation, workspace and GitHub callback links remain supported.
- The site includes an original technical hero, candidate/evidence illustration, six manual workflow steps, Claude/Codex installation, source setup and download, local Studio launch, prerequisites, data boundaries and FAQ. Team/GitHub availability is clearly marked as pilot validation.
- The source ZIP points to GitHub's public main branch. Its redirect/attachment response was verified. Public main was inspected at `a5b0ccf84cee50ff0b9c0d69df522aaf1ed4e2ee` on October 10 at 22:34 EDT: it contains runtime 1.3.0 and the Claude plugin `parallax`, while this local 1.4.0 build is a development preview. The website now uses public `parallax@parallax` and `/parallax:*` commands and explicitly labels the entire saved-candidate workflow as unreleased. The source archive is not a pilot package or native desktop installer. A browser download-event interception failed, so completed browser download is not claimed.
- The source Studio command prints an authenticated URL to open; the page says to keep it private. Genuine pilot onboarding needs an operator-supplied reviewed compatible worker because public main does not yet advertise the new workflow capability. The onboarding page makes that dependency explicit.
- Local Studio remains usable without a hosted account. Provider usage and quotas remain the developer's responsibility. No productivity claim, public paid plan or automatic enrollment was added.

## Verification

| Check | Actual result |
| --- | --- |
| Final Python discovery | Python 3.10.18 with a fresh hash-locked environment: 449 tests in 249.624 seconds, 448 passed, one Linux-only bubblewrap skip, no failures/errors. The earlier Python 3.13 full run passed 439 of 440 before the final nine isolation tests; the final private-path/App/API connection suite passed all 26 on 3.13. Project commands used native macOS isolation. An outer-sandbox-denied run and a mistyped focused module selection are not acceptance evidence. |
| Studio checks | 69 existing graph assertions, diff parser and 35 adversarial handler checks passed. New checks cover immediate public entry and failed/timed-out optional auth configuration. |
| Routing/authentication | 52 account/Supabase tests passed with `/studio` success destinations. Hosted URL/session/entry-routing and Vercel configuration checks passed. |
| Builds | TypeScript, packaged Studio and both standalone/connected Vercel outputs passed. Existing Vite bundle-size warnings remain. |
| Fresh install | Offline wheel/source distribution builds, private-file canaries, fresh hash-locked installation, CLI, 24 MCP tools, recipes, actual loopback server and final served assets passed. Real plugin bootstrap and cached offline reuse also passed. See [QA continuation](QA-CONTINUATION.md). |
| Container/recovery | Actual Linux image build, seven credential exclusions, three runtime replacements, cold restore and final HTTP asset/source identity passed. The final image includes the private-path sandbox policy and latest public installation copy. Default Docker namespaces cannot enforce project execution; actual Build refused before dispatch or edits. See [DevOps audit](DEVOPS-AUDIT.md). |
| Website browser | Dark desktop and 390px mobile, light 320px layout, no document overflow, six workflow steps and install-command copying passed. The standalone website and `/studio` launcher were also inspected; a nonlocal launch URL was refused without navigation. |
| Studio browser | Real local relay/worker with two fixture accounts and simulated providers/GitHub completed correction, fresh evidence, parent preservation, reviewer assignment/queue, peer approval, separate draft publication, reload and CI/review feedback. An explicit correction of the published candidate received new evidence and peer approval, then updated the same PR #1 and branch with a new commit; reload preserved that receipt. Exactly one task panel and feedback field remained across multiple polling cycles. Developer Git state remained clean. These are local fixture results. |

Logs include `/private/tmp/parallax-website-*`, `/private/tmp/parallax-python310-final-full.log` and `/private/tmp/parallax-sandbox-final-python313-corrected.log`. Screenshots are in `output/website-first/`; they are local acceptance evidence, not public release assets. The corrected public Claude command copied successfully; final hero/install content was rechecked at 320px with document width 320px.

## Browser defects corrected

Mobile approval measured 36px because the later workflow stylesheet overrode the pilot sizing rule. The workflow media rule now sets 44px; actual approval and publication controls measured 44px at a 390px viewport, and the decision footer was reached with keyboard navigation.

Expanded desktop CI/review feedback compressed the task panels until the delivery panel overlapped follow-up controls. Publication-bearing desktop tasks now scroll with a 380px task-panel floor. The repaired browser measured follow-up bottom 582px and delivery top 594px, with no overlap. Mobile behavior remains unchanged. Final package/container asset checks were refreshed after both corrections.

The narrow desktop layout was also inspected at 756px. Task content scrolls within a clipped panel, so off-screen descendant bounds can extend beyond the panel without painting over delivery controls. The final same-PR update screenshot is `output/website-first/publication-updated-same-pr.jpg`; the earlier `publication-reloaded-desktop.jpg` records the defect before correction.

The last security audit found that custom server-state/key locations outside the original user-directory deny list could be read by project commands, and Linux's blanket read-only host binding exposed arbitrary mounts. Live Store/agent state and configured App-key aliases/targets are now registered independently of inherited environment variables. Native macOS denies those private paths while preserving exact candidate/environment grants. Linux starts from an empty root with public runtime and explicit project/toolchain bindings, then masks private state/files. Synthetic Engine/API/App-key canaries pass, including a key whose environment setting was removed during server setup. Successful Linux execution remains unverified locally; CI is prepared on a supported unprivileged runner with a mandatory capability check and no security-setting override.

## Remaining release gates

Successful live independent-provider execution and correction, actual staging sign-in/isolation/revocation, GitHub App authorization and real PR/CI/webhook recovery, compatible Linux worker execution/CI, and actual staging worker/volume restoration remain unverified. Provider quota and missing staging/App configuration prevent live acceptance; fixtures do not clear these gates.

Four sequential local patches with focused backend boundary checks and source-reconstruction manifests are documented in [review boundaries](REVIEW-BOUNDARIES.md). They remain uncommitted and unpublished; the complete shared interface arrives in the fourth patch. Manual participant terms, support operations and representative single-agent comparisons also remain enrollment work. A reviewed compatible worker must be distributed before genuine pilot onboarding. The pilot stays closed.

For local inspection, the website preview runs at `http://127.0.0.1:8767/`; the simulated connected Studio runs at `http://127.0.0.1:8766/`. Neither is staging or a public deployment.
