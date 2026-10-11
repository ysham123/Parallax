# Invited pilot: implementation and acceptance

Product promise: **Delegate a change. Get back a reviewed patch.**

The pilot targets five individual developers and three small engineering teams using paired user-owned machines or team servers. Enrollment, support and pricing are agreed manually before any paid enrollment. There is no self-service billing and no measured productivity claim.

The pilot remains closed. The implemented local browser example uses deterministic providers and a mocked GitHub App. Earlier native-provider acceptance attempts stopped at quota or balance errors; the latest attempt stopped at a prohibited tool, then timed out without a candidate. A successful live correction, review and delivery cycle is still required. See [current evidence and evaluation changes](EVIDENCE-PILOT-IMPROVEMENTS.md), [earlier implementation evidence](PILOT-IMPLEMENTATION.md) and the [product audit](PRODUCT-AUDIT.md) before describing this as a launched service.

## Rollout gate

Set `PARALLAX_PILOT_ENABLED=on` only on staging first. The default hosted configuration rejects team creation and GitHub connection/publication. Team session kinds are deliberately `team`, so prior account servers refuse them. Existing personal sessions, CLI/plugin runs and legacy approve-and-apply workflows remain supported. New Studio tasks use contract 2.0 and distinct approval and delivery actions. Workers advertise `workflow-v2`; older workers receive an update requirement.

The original workflow foundation was based on `codex/verified-workflows` at `a83e8569b6547099035ac93ddb81ed51d55188e7` (PR #15), including earlier directory/MCP work. Review the complete dependency chain before integration into main. These isolated changes do not modify existing production workers or the dirty developer checkout.

## The workflow

1. Sign in and retain a personal workspace, or explicitly create and switch into a team workspace.
2. Pair a machine into that workspace. Existing personal workers are never transferred automatically. The worker owner approves exact project paths locally.
3. Owners bind those paths to team project policies. Empty member selection grants the project to all current members; a selected list restricts it. Owners retain policy management access.
4. Select a versioned recipe, configure providers and real checks, and delegate an outcome. Choose local delivery, or a previously authorized repository binding.
5. Inspect candidate changes, check output and independent review. Add comments and assign a reviewer. Review findings retain their recorded locations when selected for revision.
6. **Revise candidate** seeds a fresh isolated run from the saved candidate, with the original snapshot, goal, acceptance criteria, recipe and settings. **New task from current project** snapshots current developer files instead. Source drift blocks revision. Each revision consumes a new explicit run budget and has fresh evidence, digest and approval.
7. Team approval requires a human other than the current revision requester. Owners have the same rule. Personal users can approve their own candidates.
8. Approval grants delivery permission. **Apply locally** and **Publish draft PR** each have durable operation IDs and recorded actors. Local application preserves the developer's index and unrelated edits.
9. Refresh CI and review feedback. A comment can populate a revision request; it never automatically launches agents. Published unapplied candidates can be revised and their existing draft PR updated after fresh checks, review and approval.

A revision supersedes its parent when accepted for execution; parent code and evidence remain inspectable. Only one active revision may exist in a lineage. Cancel or decline an unsuccessful child before requesting another revision. A failed or interrupted run retains its consumed execution budget on recovery.

Provider discovery checks connections and supported settings, not available credit or future quota. Build and Compare need an available independent provider that did not contribute code. Complete readiness checks before choosing a representative task, then verify the chosen providers with a small disposable live task. A passing local mock example does not establish provider or GitHub readiness.

## Roles and revocation

| Role | Authority |
| --- | --- |
| Owner | Membership, invitations, role changes, workers, project policies and GitHub bindings; also Developer actions |
| Developer | Start/revise tasks, assign reviewers, comment, approve others' candidates, apply or publish approved work |
| Reviewer | Inspect authorized projects, comment and approve others' candidates |

Membership and project grants are resolved on the relay. Clients cannot supply their own role. Queued commands are reauthorized before dispatch. Removed users and changed project policies invalidate pending commands. Already dispatched work retains its recorded requester and evidence. Team data and personal templates are scoped independently; team requests cannot read machine-level personal profiles or feedback exports. Team mirrors require an online worker for filtered task requests; unfiltered offline cache responses are refused.

Promote another Owner before demoting the last Owner. Owners must transfer ownership before account deletion. Deleting a member's account removes their personal workspace and membership, preserving the team workspace and other members.

## GitHub App setup

This App is separate from Parallax sign-in. Register it with:

- Contents and Pull requests: write.
- Checks, Commit statuses and Actions: read.
- Workflow-file modification: excluded from the pilot.
- User authorization callback: `<STAGING_ORIGIN>/api/github/connect/callback`.
- Webhook: `<STAGING_RUNTIME_ORIGIN>/api/github/webhook` with a strong secret.
- Selected repository installation access; start with a designated disposable test repository.

Set server-side environment variables:

```
PARALLAX_GITHUB_APP_ID
PARALLAX_GITHUB_APP_PRIVATE_KEY_PATH
PARALLAX_GITHUB_APP_CLIENT_ID
PARALLAX_GITHUB_APP_CLIENT_SECRET
PARALLAX_GITHUB_APP_WEBHOOK_SECRET
PARALLAX_GITHUB_APP_SLUG
PARALLAX_PILOT_ENABLED=on
```

The private key file must stay outside approved projects and must not enter Git, a browser build, logs, a worker queue or a support bundle. Configuration is held server-side and removed from the subprocess environment. App JWTs and installation tokens stay on the relay; workers receive no Git credentials. Publication uses GitHub's API and an expected head mutation, preserving all local branches and indexes. Repository-scoped installation tokens are freshly minted for operations, never persisted.

After installing the App, use **Authorize GitHub delivery** in Workspace settings. The relay exchanges the App OAuth code, verifies the user's accessible installations belong to this App, then discards the user token. An Owner selects an installation and repository and binds it to a worker-approved project. GitHub sign-in alone does not grant delivery access.

A GitHub task requires its captured tree to match the selected remote base tree before provider execution. Publication rechecks the base commit/tree and candidate digest. Dirty tasks remain usable for local delivery. Publication only writes the approved tree to `parallax/<workflow-id>`; revisions retain the original published branch and compare its expected head. Parallax never force-pushes, rebases, merges or deploys automatically.

Current API delivery bounds: up to 4 MiB of changed blob content; binary contents are base64 encoded. Symlink changes and executable-mode changes require local delivery because the expected-head API does not represent those changes. Such changes are refused before creating a remote commit. Unchanged executable modes remain supported. Workflow files are refused before any remote mutation.

Publication journals capture request identity, actor, base, tree, commit, branch and PR number. An interrupted publication checks existing remote state before retrying. The commit includes its operation ID and candidate digest. Webhooks validate SHA-256 HMAC signatures in constant time and deduplicate delivery IDs. Events act as refresh hints; Studio reads current GitHub state so missed or reordered events cannot regress saved CI/review state.

Official references: [installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [webhook verification](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

## Data, support and recovery

Execution, repository snapshots, private working copies, complete local provider-session files, provider sign-ins and credentials remain on the worker. The relay retains account/workspace membership, project permissions, GitHub bindings, operation journals and mirrored task evidence, including task prompts and settings, diffs, check output, review findings, agent output and session metadata. Evidence can contain source code and other project content. Relevant prompts and project contents reach the chosen model providers. GitHub receives approved file content when the developer explicitly publishes. App credentials remain on the relay. See existing privacy, terms, security and support pages for the operator's policies.

Invitation links are copyable, single use and expire after seven days. Parallax does not automatically email invitations. Do not include App tokens, sign-in tokens, provider keys, private prompts or source files in a support request. Recovery starts with the durable task and operation record, then the local candidate metadata and current remote state. Never delete recovery journals to reset a budget or blindly repeat a mutation.

| User sees | Next action |
| --- | --- |
| Worker offline | Wake the machine and reconnect the worker using its existing state. New work, decisions and delivery need an online worker. Team task inspection also needs it to enforce project filtering; personal cached evidence cannot authorize mutations. |
| Quota, balance or authentication failure | Inspect the provider error in task evidence and resolve that connection or budget. Resume deliberately with the remaining execution budget; use a new task when choosing a different setup. Provider failures are failed attempts, not successful outcomes. |
| Another human must approve | Assign an authorized project reviewer, share the task link and ask that person to sign in to their own account. In a team of one, invite a second human; there is no Owner override. The approver does not apply files or publish. |
| Original project changed | Preserve the old candidate and evidence. Start **New task from current project** with the relevant correction; revision cannot silently replace its original baseline. |
| A revision failed before producing a candidate | Stop the unsuccessful child and return to the saved parent under **Related tasks** to request another revision. Preserve the failure and its consumed budget. |
| Publication may already have happened | Reload the task, inspect the saved publication and remote branch/PR, and have its original actor retry the saved operation. Ask the operator for help if the actor is unavailable or access was revoked; do not clear the reservation. |
| GitHub reports changed base/head or removed installation | Inspect the remote state and authorization with the Owner/operator. Keep the saved operation for reconciliation. A fresh task captures a new baseline; Parallax does not automatically rebase or force push. |

Before enrollment, the operator must confirm support contact, response expectations, evidence retention and deletion procedures, volume backups and restoration. The pilot does not promise unattended operation when machines sleep, recovery by another actor for a reserved publication, or preservation of every mirrored event after relay storage limits prune old evidence. Preserve worker state and local evidence while recovering.

Worker reports are available from `GET /api/pilot/report` through the selected machine. They record setup readiness, outcomes, revisions, recorded interventions, execution duration, approval latency and delivery results. Usage appears only when reported by a provider; cost remains explicitly unknown if it is not measured. Reports cover the selected worker's latest 100 authorized workflows, with full retained authorized ancestor effort for their revision lineages. Missing or inaccessible ancestors leave totals incomplete; this is not all workspace history. Reports also include participant-reported comparisons and scoped, readable journal observations, including failed attempts absent from the current result. Observation lists are capped and flag unavailable or invalid evidence. Missing execution duration is `null`, distinct from a recorded zero. Approval latency is populated only for an approval and measures candidate capture to its recorded decision; a decline is not an approval.

For a representative comparison, use Studio's **Pilot measurements** and [evaluation protocol](PILOT-EVALUATION.md). `POST /api/pilot/benchmark` retains legacy requests and supports a versioned `evaluation` object for comparison identity, attempt order, outcomes, nullable elapsed/human/setup/review time, baseline scheme, safe provider settings and budgets. The saved baseline, contract, configuration and lineage are attached server-side. `POST /api/pilot/observations` records immutable human labels against an observation digest and optional review finding; labels never change approval or delivery gates. Use the same repository baseline and acceptance criteria for both approaches. Report raw outcomes before making pricing or productivity claims.

The following limits apply to measurement:

- Setup readiness records a successful assessment, not completion of a live task, provider credit validation or GitHub delivery.
- Automatically recorded interventions combine revision starts, task comments and recorded steering/pause/recovery events. They are recorded activity counts, not human effort or all work outside Studio. Agree on a comparable manual intervention definition for both approaches.
- Keep copies of the same baseline and acceptance criteria, use the same checks, and report unsuccessful, cancelled and quota-blocked attempts alongside successes. The server attaches the saved goal/checks but does not prove that the manually reported single-agent run used them.
- Define the timing boundary before each comparison. Automatic engine execution time and manually entered end-to-end duration measure different things. For a wall-clock comparison, manually record both approaches using the same start and accepted-result boundary, with setup and human review time identified separately.
- Include all revisions in a task's total effort and provider consumption. Separate approval waiting time from active review effort. Vary task order to limit learning effects, record provider/model/settings and show individual outcomes before aggregating.
- Provider usage may be incomplete. Missing cost is unknown, and per-provider observed costs must not be presented as an authoritative all-provider bill.

Commercial enrollment remains manual: record each participant's agreed scope, price, evaluation period, provider charges, support expectations and cancellation/refund arrangement before enrollment. Do not accept payment or advertise measured savings until the live launch checklist and that participant's terms are complete.

## Launch checklist

- [ ] Staging deployment identifies the exact reviewed source head and enables the pilot gate.
- [ ] Anonymous entry, sign-up/sign-in, account recovery, session expiry and sign-out verified live.
- [ ] Two genuine accounts complete personal and team onboarding with separate worker ownership.
- [ ] Cross-account/workspace/project denial verified for tasks, events, downloads, profiles and publication.
- [ ] Owner/Developer/Reviewer permissions, self-approval refusal, reviewer assignment and invitation expiry verified live.
- [ ] Member removal, worker revocation and project policy changes invalidate queued mutations.
- [ ] Real providers prepare a candidate, revise it and return fresh checks/review; approval and delivery remain separate.
- [ ] Designated test repository receives a real App-authenticated draft PR with the exact approved tree.
- [ ] Publication interruption, removal of the installation, token expiry, base drift and external head changes verified.
- [ ] CI/reviews, signed duplicate/reordered webhook deliveries, and explicit PR revision verified live.
- [ ] Desktop/mobile setup, reviewer handoff, approval, publication and recovery visually verified.
- [ ] Privacy/support contacts, retention/deletion expectations, backups and recovery are confirmed by the deployment operator.
- [ ] Manual commercial terms agreed with each pilot participant before enrollment.

Missing staging/App credentials or a designated repository is an unverified integration, not a completed launch. Leave the pilot closed until all live acceptance gates pass.
