# Release validation evidence

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
