# Pilot implementation and verification

Implementation checkout: `Parallax-pilot-20261009`, branch `codex/delegation-pilot`, based on `codex/verified-workflows` at `a83e8569b6547099035ac93ddb81ed51d55188e7` (PR #15). Changes are local and uncommitted. The existing dirty developer checkout was preserved. No production deployment, commit, push, real GitHub publication, email, enrollment or billing occurred.

## Review in dependency order

| Change | Review focus | Main files |
| --- | --- | --- |
| Candidate revision | Immutable child, original baseline checks, binary preservation, source drift, lineage, fresh approval | `workspaces.py`, `engine.py`, `candidates.py`, revision portions of `workflows.py`; `test_workflows.py` |
| Team authorization | Membership, invitations, roles, shared recipes, project grants, queued revocation, separate approval/application | `authority.py`, `teams.py`, `accounts.py`, `executors.py`, `worker.py`, authorization portions of `server.py` and `workflows.py`; `test_teams.py` |
| GitHub delivery | Independent App authorization, scoped tokens, baseline/tree checks, durable publication reservation, expected-head commit, restart/retry reconciliation, draft revisions, signed webhooks | `github_delivery.py`, publication portions of `server.py`, `workflows.py`, `candidates.py`; `PublicationPanel.tsx`; `test_github_delivery.py` |
| Product and pilot | Workspace switching, reviewer queue, findings/corrections, separate delivery, mobile layout, privacy, raw measurements | `WorkspaceControls.tsx`, `TaskWorkspace.tsx`, `Workflows.tsx`, `CloudApp.tsx`, `PublicEntry.tsx`, `Legal.tsx`, `PilotMetrics.tsx`, `pilot.py`, `docs/PILOT.md` |

Shared contract and route files span these boundaries. Four sequential local review patches now separate the implementation, with focused checks at the backend boundaries and complete interface integration last. These are not landed commits. See [review boundaries](REVIEW-BOUNDARIES.md) for their scope, base, replay evidence and local artifact location before staging.

## Verification evidence

Current continuation: [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md) records final Python 3.10 discovery (448 of 449 passed, one Linux-only skip), targeted final 3.13 private-path checks, 35 frontend handler checks, fresh installed packages, real container recovery and final desktop/mobile fixture walkthrough. Four sequential local review patches are documented in [review boundaries](REVIEW-BOUNDARIES.md). The evidence below records the original implementation pass. Live provider, App and staging gates remain open.

- Full Python suite: 379 tests passed, one skipped. Later focused suites (44 workflow/team/GitHub tests, 53 account/recovery checks, and nine App authorization/comment checks) covered all subsequent workflow, team and GitHub changes, including binary candidate seeding/publication, reserved publication recovery, same-PR updates, closed/ready PR refusal before mutation, comment persistence, remote base drift and ended sessions. A final 24-test worker/relay compatibility suite passed. Worker downgrade tests also verify that missing capability fields clear prior feature flags and queued team requests are refused before dispatch.
- Studio graph/diff checks: 69 graph inspection assertions plus diff parsing checks passed.
- Hosted session and Vercel routing checks passed.
- Packaged and cloud TypeScript/Vite builds passed. The existing large-chunk warning remains.
- Scoped pilot report checks passed for outcomes, approval time, unknown cost, idempotent same-criteria comparison and cross-workspace denial.
- Release validation passed for 1.4.0. This change does not bump or publish the release.
- A real local relay and worker with deterministic providers and a mocked GitHub App completed: Owner delegation, saved-candidate revision, assigned second-human Reviewer queue, approval without filesystem application, explicit draft PR publication, CI/review refresh and publication reload. No real GitHub repository was contacted by this browser fixture.
- Browser screenshots are under `output/playwright/`. Desktop: 1440 by 1000. Mobile: 390 by 844, measured document width 390 after correcting header overflow. Workspace settings fit and scroll; task activity, correction controls and evidence remain scrollable.

Temporary detailed test logs reside under `/private/tmp/parallax-*`; they are not release assets. Disposable acceptance repositories and state are in `Parallax-pilot-acceptance-20261009` beside the implementation checkout and `Parallax-pilot-browser-fixture` beside the implementation checkout.

## Live acceptance remains incomplete

Actual authenticated native-provider executions were attempted with Codex coordination in a disposable Git repository:

| Implementer | Outcome |
| --- | --- |
| Claude Code | Weekly quota reached; no patch produced |
| Grok Build | Usage balance exhausted (402); no patch produced |
| Antigravity | Individual quota reached; no patch produced; acceptance run stopped after confirming the limit |

Failed evidence and consumed budgets remain preserved. The developer project stayed unchanged. These attempts establish provider authentication and failure handling, not a successful live delegation/revision/review cycle. A working independent provider budget is needed to finish that check.

No staging GitHub App credentials or designated test repository were supplied. App authorization, real draft publication, CI/reviews, installation revocation and live webhooks remain unverified. No invited pilot has been opened. See `PILOT.md` for server configuration and the remaining launch checklist.

## Recovery details

Each revision, approval, application and publication binds a request ID to recorded inputs and actor. Explicit publication first reserves the workflow and saves its approved file bundle on the worker. This blocks a simultaneous revision. The relay journal saves the remote operation; retries reconcile its commit marker, exact tree and PR. Studio restores a pending request from the relay after reload. A completed remote publication can reconcile its worker receipt without recapturing mutable developer files. The original actor retries the saved operation; other members can inspect it.

If publication is pending, reconcile it before revising. A removed installation, changed base or external branch head is refused; do not force push or clear journals. If recovery cannot proceed, the pilot operator must inspect the saved records and remote state. Existing execution budgets are not reset. Team and GitHub features require `PARALLAX_PILOT_ENABLED=on` on staging.
