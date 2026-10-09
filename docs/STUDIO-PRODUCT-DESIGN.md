# Studio as a developer workspace

Research and source review: October 9, 2026. This is a product direction for the current development branch, not a claim about the deployed release. Competitor observations below come from their public documentation; they are not hands-on evaluations of paid products.

## Product decision

Parallax should open on the developer's work: projects, active tasks, decisions that need attention, and the selected task's evidence. Starting a task is one action within that workspace. Recipes belong in task configuration; three recipe cards do not provide a useful home for someone managing ongoing work.

The intended repeat-use loop is: select a project, describe an outcome, follow the team's progress, inspect the exact changes and verification, request another pass when needed, and explicitly apply the accepted candidate. Parallax's strongest existing foundation is its mixed-provider execution, independent review, retained failure evidence, durable approval, and preservation of the developer's working tree. The interface should make that foundation usable every day.

LangGraph stays inside the runtime. Developers should experience reliable continuation and understandable task history, without needing to learn or edit orchestration graphs. The agent graph remains a useful diagnostic view of actual recorded execution.

## What established applications organize around

| Product and primary source | Observed application pattern | Implication for Parallax |
| --- | --- | --- |
| [Conductor workflow](https://www.conductor.build/docs/concepts/workflow) and [diff viewer](https://www.conductor.build/docs/reference/diff-viewer) | Each shippable task has a workspace. Changed files, inline feedback, verification, PR actions, and eventual archive form a continuous lifecycle. | Keep tasks persistent and reviewable. A developer must be able to ask for a correction from the result being inspected. Finished work needs a clear delivery path. |
| [Cursor Agents Window](https://cursor.com/docs/agent/agents-window) | Agents across repositories and environments share one workspace interface. File search, diffs, worktrees, and local/cloud handoff stay accessible from the work. | Make project/task switching cheap. Keep evidence beside task activity. Retain links into deeper execution tools rather than requiring users to rediscover the same run in another tab. |
| [Devin Review](https://docs.devin.ai/work-with-devin/devin-review) | Review is a product workflow: organized diffs, findings, contextual discussion, code corrections, and Git-provider actions. | A green badge is not enough. Findings should lead to the relevant changes; review feedback should retain the candidate context. |
| [Google Antigravity introduction](https://antigravity.google/blog/introducing-google-antigravity) | Its documented design separates asynchronous agent management from direct editing and emphasizes task-level artifacts, verification, and feedback. This source describes the original November 2025 design. | Summarize progress around tasks and inspectable outputs. Keep raw events available without making them the main explanation of what happened. |

These are shared interaction patterns, not evidence that any one layout improves outcomes. Parallax still needs observation with real developers on their own repositories.

## Present in the current branch

The task workspace replaces the recipe-card home with a persistent queue, project and status filters, task search, and a selected-task surface. New-task configuration includes the saved workflow, participants, models, checks, and time limit.

The selected task combines its original request, assigned team, recorded plan, result, execution log, and milestones with Changes, Checks, Reviews, and Details panels. The diff supports file filtering, per-file navigation, old/new line numbers, 400-row pages for large files, and exact patch download. Task actions include live steering while preparation runs, linked follow-up drafts, resume or stop where supported, and explicit candidate approval or rejection. Approval remains bound to the complete candidate and its evidence. Partial file acceptance is not supported.

The existing run workspace still provides the agent/task graph, task inspection, attempt and repair history, context evidence, check output, and deeper execution controls. Project readiness in the task composer exposes discovered packages and instruction files, command isolation, issues, and the actual configured or detected check commands. Detected commands can be copied into the recipe editor for explicit saving. Full package-root and saved-profile editing remains in the advanced run path.

Linked follow-ups persist a parent ID, retain the original goal and bounded prior result, inherit the exact immutable recipe and full saved run settings, and authorize both records in the same canonical project. Parent and child links survive reload and restart. Each child starts from the current project, without copying an unapplied candidate, and requires a new candidate decision.

Durable workflow records and checkpoint recovery exist in the runtime. Browser reconnection does not require a new build merely to inspect or approve a saved candidate. These are implemented capabilities; deterministic tests do not establish live-model quality, cost, or developer preference.

## Important remaining gaps

- **Candidate revision:** linked follow-ups now preserve task history and settings, but start from the current project. Revising an unapplied isolated candidate requires a separate revision operation with explicit base, lineage, recovery, and new verification semantics.
- **Project configuration:** the task composer now exposes concrete readiness evidence. Selecting package roots and saved project profiles still requires the advanced path; those controls need to join the same task configuration flow.
- **Delivery:** application to the local working tree and patch/receipt downloads exist. An integrated issue-to-PR lifecycle, branch publication, CI tracking, and review-comment synchronization do not exist in this task workspace. Buttons must not imply those capabilities.
- **Product evidence:** the redesign has not yet demonstrated lower intervention time or better accepted results on representative developer tasks. Visual density alone does not establish product value.

## Implementation decisions and next priorities

### 1. Linked follow-up tasks with preserved settings: implemented

This implementation closes a common review handoff without changing the meaning of an approved candidate. The following describes its contract.

Persist a `parent_workflow_id` on a new workflow. The worker resolves the parent, enforces the same authorized canonical project, and includes its recorded goal and outcome as context for the new request. The source task must belong to the same worker and remain accessible under the existing project/account boundary. Do not trust a browser-supplied parent summary as authoritative evidence.

Default to the parent's immutable template version and complete saved settings, including participant roles, models, effort, connection IDs, limits, checks, and package roots. If the user deliberately changes settings, show that before starting and record the resulting child specification. Loading the latest recipe silently is not equivalent to continuing the previous task.

Show “New candidate from current project” when drafting the follow-up. Include the requested correction separately from the previous goal and recorded outcome. Keep the context bounded; reject or disclose truncation instead of silently dropping the user's acceptance criteria. The original full record remains reachable by its parent link. No patch or previously approved status is inherited.

On the child, link back to its source task. On the parent, show related follow-ups. These links describe the history of requests. They do not imply a dependency scheduler, reuse of a provider conversation, or a candidate revision engine. Browser reload and worker restart must preserve them.

**Acceptance:** a developer can inspect a candidate, draft a correction, see the source task and exact inherited settings, start a separate candidate against the current project, and return to both records. Duplicate starts remain idempotent. Cross-project/account parent references are rejected. Changing a recipe after the parent ran cannot change the child's defaults. Both candidates retain independent digests and decisions.

**Later, true candidate revision:** an explicit revision operation would reuse or clone the previous isolated candidate, record its base and lineage, re-run relevant checks and independent review, and produce a new digest requiring a new decision. It needs its own recovery and concurrency design. A parent link alone does not provide this behavior.

### 2. Project readiness: assessment implemented, profile editing remains

The task path now reuses current assessment capabilities and shows its timestamp. Changing project, participants, or check settings invalidates the displayed result; late responses cannot replace newer inputs. Developers can inspect detected packages, instruction files, actual check commands, execution support, and reported provider issues before starting. The remaining work is selecting package roots and saved profiles in this same flow.

This follows the useful setup pattern in [Conductor's project configuration](https://www.conductor.build/docs/configure-your-project) while retaining Parallax's existing contracts. Assessment is read-only; using detected checks edits an unsaved recipe draft. It does not install dependencies or execute setup commands.

**Acceptance:** a developer configuring a monorepo can identify exactly which packages and commands will be used, choose a saved profile, and correct a blocked setup from the same new-task flow. The resulting saved run matches the reviewed configuration.

### 3. Make review and delivery easier to finish

Connect structured findings to matching changed files and line locations. Give the developer a compact account of checks run, reviewer results, unresolved concerns, and the current candidate's disposition. Preserve raw evidence for diagnosis. Feedback should carry the selected file/location into the linked follow-up from priority 1.

After application, provide a useful handoff containing the task outcome, changed files, commands/results, and verification-record reference. It can be copied or downloaded for an existing PR workflow. Any later Git-provider publishing needs real authenticated backend operations and explicit review of the destination, branch, and content.

**Acceptance:** from a finding, the developer reaches the relevant change and drafts a correction without retyping its context. After acceptance, they can use the handoff in their existing delivery process. Do not represent “applied locally” as “shipped,” “merged,” or “CI passed.”

## How to learn whether this earns repeat use

Observe a small set of real developers completing a bug fix, a scoped feature, and a multi-package change in their own repositories. Record setup failures, task completion, reasons for rejecting candidates, number of corrective interventions, time spent reviewing, and whether they return for a second task. Compare a subset against their usual single-agent workflow with the same acceptance criteria. Ask where they had to leave Studio and what information they needed there.

Use those observations to choose the next investment. A terminal, embedded editor, automation builder, or fleet dashboard should solve a demonstrated break in that loop before it becomes another navigation item.
