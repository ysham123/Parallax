# Release validation evidence

## 1.2 live validation

[Live validation](live-1.2.md) records real Codex, Claude Code, Grok Build and Antigravity runs on a disposable fixture: a blind Review, a Build that passed all five integration gates with the user's staged and untracked work preserved, `/parallax:review` through the Claude Code plugin, and a live exploration round trip. It also lists the five issues those runs exposed, each fixed with a regression test and confirmed by a live rerun, and what remains uncovered.

## Hosted local execution

[Paired worker validation](paired-local-worker-2026-10-06.md) records a real hosted Codex/Claude build, independent reviews, all five integration gates, and staged/untracked preservation. It also records the current runtime and relay regression coverage. Earlier evidence below retains its historical validation status.

## 1.1 developer alpha

[Real mixed-project delivery](delivery-native-1.1.json) records a completed four-native-provider build with two failed baseline test suites, four passing final checks, independent per-task and combined review, two scoped source edits and all five integration gates. The real Git index matched byte for byte after application. This is a disposable build demonstration, not a human alpha outcome.

The final 1.1 suite completed **142 cases on Python 3.13** in 97.8 seconds, with one Linux-only live sandbox case skipped on macOS. The full 139-case suite passed on Python 3.10 in 89.7 seconds before the final additions; the final 20 delivery cases completed on Python 3.10 in 26.2 seconds with the same Linux skip, and the final 33 engine regressions passed after lock cleanup. The Linux mount-order and secret masking regression is exercised structurally on macOS; actual Linux execution remains pending. CI targets Ubuntu/macOS and Python 3.10/3.13 with bubblewrap provisioning. The local Docker daemon was unavailable. Remote CI, live API inference and the five-developer alpha are unperformed.

[Studio delivery QA](delivery-studio-qa-1.1.md) records readiness, project profiles, keyboard task inspection, responsive check comparisons and contextual conflict recovery. [Installed 1.1 runtime](installation-1.1.json) records all 24 MCP operations, current and legacy receipts, a held-SSE shutdown in 3.2 seconds, same-port restart, existing-cookie reconnection and preserved requested workspace. Source and installed cache matched byte for byte.

[Graph-first Studio QA](studio-workspace-qa-1.1.md) records the Workspace redesign, real run inspection, responsive keyboard behavior and 59 portable graph/activity assertions. This UI update does not rerun or increase the earlier 142 runtime-case count.

## Retained 1.0 evidence

Validated locally on macOS, 2026-10-06. The configured GitHub CI matrix targets Ubuntu and macOS with Python 3.10/3.13; it has not run remotely for this unpublished branch.

| Evidence | Coverage |
| --- | --- |
| [Native smoke](native-smoke.json) | 16 real CLI cases: consultation, scoped edit, resume, and permission boundary for each of Codex, Claude Code, Grok Build and Antigravity. Exact installed versions and effective settings recorded. |
| [Four-provider build](four-provider-build.json) | Actual task/repair history, independent reviews, source diff, combined check output and completed application. Eight unchanged acceptance tests pass. |
| [Final verification record](four-provider-verification.json) | All five gates passed. Preservation was rechecked against the committed integration journal and destination bytes before finalizing this record. |
| [Earlier blocked attempt](four-provider-build-attempt1.json) | Preserved failure evidence, including the initial permission/verification issue and runtime stop. |
| [Installed runtime](installation.json) | Enabled personal installation is 1.0.0; packaged launcher, 15 MCP tools, receipt retrieval, authenticated Studio, SSE-connected shutdown (3.2 seconds), same-port restart and cookie reconnection passed. |
| [Studio QA](studio-qa.md) | Desktop/mobile flows, keyboard navigation, modal focus, task graph, real receipt, downloads and visual captures. |

The final complete suite passed all **122 tests on Python 3.13** in 59.5 seconds. The full suite passed 121 tests on Python 3.10 in 51.6 seconds before the last finalization regression; the final 33-case engine suite then passed on Python 3.10 in 25.0 seconds. The final six-case receipt suite passed. These cover the current 122-case inventory; unchanged suites were not repeated solely to increase test counts.

Tests include model/effort rejection, malformed streams, authentication and permission failures, failed review and repair, dirty-tree and concurrent-edit preservation, check failures, cancellation, restart reconciliation, duplicate actions, bounded subprocess handling, API journals, secret canaries, offline private Python/npm setup, HTTP auth/origin controls, legacy bridge compatibility and release input exclusions.

API inference is exercised with deterministic protocol fixtures, not paid live account calls. Native smoke establishes the tested cases and versions, not every possible model/effort combination. The small build fixture is evidence of the full delivery path, not a productivity benchmark. Record hashes identify artifacts; they are not signatures or proof that code is correct.
