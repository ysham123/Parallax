# Saved coding workflows

Studio opens on **Tasks**, with a searchable queue and a workspace for the selected task. Filter the queue by project or status, follow the team's activity, and inspect changes, checks, and reviews beside it. You can return after closing the browser or restarting the worker, inspect the same saved candidate, and decide whether to deliver it. A completed candidate does not need another successful build simply because the connection was lost.

New Studio tasks use contract **2.0**, which separates human approval from local application and draft GitHub PR delivery. Existing contract **1.0** records retain their original **Approve & apply** behavior; existing CLI/plugin runs are unchanged. Team workspaces and GitHub delivery are enabled only for configured staging or invited pilots. See [pilot setup, roles and launch gates](PILOT.md).

## Start a change

1. Open Studio locally, or select an online paired machine in hosted Studio. The project must be approved on that machine.
2. Select **New task**, choose the project, and describe a specific outcome. The **Workflow** selector offers Verified change, Fix a bug, Safe refactor, Modernize one component, and your saved recipes. Built-in recipes use the same execution stages with different task instructions. Their initial team is Codex coordinating and Claude implementing. The [modernization exercise](../examples/legacy-modernization/README.md) starts from a passing behavioral baseline and requires compatibility checks against the upgraded component.
3. Under **Configure team, task instructions, and checks**, choose providers, models, effort, time limit, task instructions, and explicit project checks if needed. With no explicit checks, Parallax uses the project's detected checks. Unsupported setup stops for attention.
4. Use **Check readiness** to inspect package discovery, instruction files, command isolation, and the actual configured or detected check commands. Discovery does not execute checks or establish provider quota. **Use detected checks** copies commands into the task's check editor. Then **Start task**: Parallax builds in private worktrees, obtains independent review, and runs real project checks. It retains the verified candidate without applying it to your working project.
5. Select the task in the queue. **Changes** shows the exact patch by file; **Checks** shows command results; **Reviews** shows independent findings; **Details** shows the saved settings. **Open agent graph** shows the underlying agents, tasks, and dependencies.
6. Inspect the evidence and choose **Approve candidate** or **Decline**. Approval is tied to the whole candidate, original project snapshot, recipe settings, and verification evidence. Personal users can approve their own request. In a team, an authorized human other than the current revision requester must approve; Owners follow the same rule. If a reviewer is assigned, that reviewer must make the decision.
7. An authorized Developer or Owner chooses **Apply locally**, or reviews the repository, base, branch, title and description before selecting **Publish draft PR**. Approval itself performs neither action. Local application rechecks the candidate and project and preserves staged work and unrelated files. GitHub delivery requires the selected repository binding and a clean captured remote baseline before execution and again before publication. Dirty-tree tasks remain available for local delivery.

After local application, download the verification record. It includes the candidate digest, recorded approval, checks, review providers, and preservation results. It omits prompts, raw sessions, absolute project paths, and command output. It is an unsigned evidence record, not a guarantee that every behavior is correct. A published task also records its branch, commit and draft PR link. CI and GitHub reviews are retrieved with **Refresh CI and review feedback**; feedback can fill an explicit correction request and never launches agents automatically.

## Follow work and give direction

Use the queue's project filter, search, and status views to find tasks awaiting approval, in progress, needing attention, or completed and closed. Selecting a task keeps its activity and evidence together. Filter changed files and select a file to inspect its unified diff, with old and new line numbers. Large files are paged in groups of 400 rows; the patch download retains the entire diff.

While the team is preparing a change, **Direct the team** sends guidance to the active run. After execution, enter a correction and optionally select recorded review findings with file locations. Two actions use different starting points:

- **Revise candidate** seeds a new isolated candidate from the parent's saved patch. It preserves the original project snapshot, goal, acceptance criteria, recipe version and settings. Baseline checks run against the original snapshot; final checks and independent review run against the revised candidate. Source drift refuses revision and directs you to start against the current project. Each revision has a new explicit execution budget, fresh evidence, digest and approval.
- **New task from current project** opens a linked draft using the parent's exact recipe and settings, with a new request and recorded context. It captures the current developer files and does not reuse unapplied parent code. The composer permits explicit participant and time-limit changes. Long prior summaries are truncated to 2,000 characters; the full record stays linked. **Make a standalone task** removes the link and restores the selected recipe defaults.

Parent and child remain accessible through **Related tasks**. Accepting a revision for execution supersedes its parent, preserving that parent's candidate and evidence. Only one revision in a lineage can remain active, including a child awaiting approval or delivery. Resolve or stop an unsuccessful child before retrying its saved parent. An unapplied published candidate can be revised; updating the same draft PR needs new checks, review and approval and refuses an externally changed PR head. Applied candidates need a new task against the current project.

Unsent feedback survives task switching, and an open new-task draft survives navigation to the agent graph. These browser drafts are not durable across page reload. **Resume task** continues interrupted work, and **Stop task** stops work when available.

## Save a recipe

In **New task**, adjust the team, time limit, instructions, and checks, enter a name, and select **Save as recipe**. Personal recipes belong to the selected machine; team recipes are shared as immutable versions within that workspace. **Save new version** changes the settings used by future starts; existing tasks retain their original template version and complete run specification. Built-in recipes can only be copied.

Instructions, checks, provider selections and the time limit can be changed for one execution without saving a recipe. The task captures those settings immutably. Saving a named recipe is optional reuse for future tasks. **Use task again**, available for declined or stopped tasks, opens a linked draft with the previous request and exact saved recipe version; review those settings before starting a fresh candidate.

## Disconnects and interrupted work

| Situation | What happens |
| --- | --- |
| Browser closes or hosted connection drops | Already dispatched execution continues on the machine while it is awake. Personal cached evidence may remain inspectable; team task requests require an online worker for project filtering. Reconnect the worker to send new commands. |
| Worker restarts while awaiting approval | The same verified candidate remains ready for your decision. No provider call is needed to approve it. |
| Worker restarts during preparation | The task offers **Resume task**. The engine reconciles its action records and remaining budget before continuing. Restart alone never starts new provider work. |
| Approval was recorded just before a restart | Contract 2.0 retains the decision and waits for explicit delivery. Legacy records reconcile their combined approval/application. A second approval cannot replace the saved decision. |
| File application committed before the result was saved | Contract 2.0 uses **Retry local application**; legacy recovery uses **Resume task**. Recovery reconciles the durable file transaction and records the receipt without applying the patch again. |
| An interrupted application cannot be proved complete | Parallax reports attention and does not replay the ambiguous write. Inspect the project and prepare a new workflow. |
| Project files, Git staging, candidate, or evidence changed | The old approval cannot apply the candidate. Prepare a fresh workflow against the current project. |
| Candidate declined or workflow stopped | The project remains unchanged; saved evidence remains available. |
| Provider reports quota, authentication or transport failure | Inspect the recorded error and provider connection. Discovery alone cannot establish quota. Eligible interrupted or needs-attention work may resume after the failure is resolved, within its remaining budget. Terminal failed/cancelled work starts a fresh task; a new task or revision receives an explicit new budget. |
| Publication interrupted or browser reloaded | Studio retrieves the saved operation. The original actor retries **Retry saved publication**, which reconciles remote state and the worker receipt. It does not recapture mutable developer files. |
| Base drift, removed GitHub installation or external PR head edit | Publication is refused. Inspect the remote state with the operator; do not force push, clear journals or treat an ambiguous operation as an unused request. |

Execution time limits carry across restarts. Time waiting for approval does not consume that budget. Up to three workflows can be active on a worker; the engine still allows only one implementation run per project. A candidate waiting for approval does not hold the project lock. A later project edit can therefore invalidate it.

## Storage and execution

LangGraph is an internal workflow coordinator. Contract 2.0 preparation ends at a saved human decision; application and publication are separate authenticated, durable operations. Legacy records retain `prepare → approval → apply`. The existing Parallax engine owns provider dispatch, isolated worktrees, reviews, checks, repair budgets, and process recovery. WorkspaceManager owns file application and preservation checks.

Workflow records and immutable recipe versions live in the worker's `state.sqlite3`. LangGraph checkpoints live in `workflows.sqlite3` in the same private state directory. Graph state refers to workflow IDs; run records remain the source of execution evidence. Checkpoint serialization disables pickle and arbitrary object loading. Workflow invocation explicitly disables LangSmith tracing, including when tracing is enabled in the parent environment.

An immutable workflow operation key is saved atomically with each engine run before provider dispatch. Checkpoint replay reuses that identity. This prevents duplicate run creation across the tested crash boundaries; it does not promise exactly-once external provider execution under every possible failure.

Hosted Studio uses the authenticated workspace-scoped worker relay. Personal machines are never shared automatically with teams. Workers enforce exact locally approved project paths; the relay resolves membership, roles and team project grants and checks queued authorization again before dispatch. Requested workflow summaries, task prompts, settings, candidate evidence, agent output and session metadata can be retained by the relay under its existing size and retention limits. Private working copies and provider credentials stay on the machine. Offline cached evidence cannot authorize work. Team requests fail closed on older runtimes or workers that cannot enforce their scope.

Update both the runtime/relay and paired workers to use these routes. Older workers show an update message in Studio. Personal workspaces retain compatible direct controls under **Advanced run**; team advanced views are inspection-only and route execution through Tasks. Existing CLI/plugin review, build, and compare behavior is unchanged. The remote MCP tool set is unchanged; workflow approval is exposed in authenticated Studio and the scoped worker API.

## Validation and current scope

The workflow tests use real LangGraph checkpoints, SQLite, Git worktrees, file application, and deterministic providers. They exercise restart before the workflow records an engine run, waiting approval, persisted decisions, interrupted file application, duplicate requests, source and evidence changes, immutable recipes, cancellation, and account/project isolation. Linked-task tests cover inherited settings and old recipe versions, independent candidates, restart and chain context, bounded summaries, idempotency, and unauthorized or cross-project parents. Browser QA covers recipe selection, readiness, candidate inspection, linked follow-ups, live guidance, draft preservation, worker restart, approval, and receipt download.

This is a coding workflow product feature, not an arbitrary graph editor. It does not add scheduling, managed cloud execution, automatic merge, uploaded executable templates or remote MCP approval tools. Team shared recipe versions are included in the invited pilot. Actual model quality, provider cost and real GitHub App delivery still need live acceptance; deterministic tests and mock browser flows do not establish pilot readiness. See the [implementation evidence and remaining gaps](PILOT-IMPLEMENTATION.md) and [launch checklist](PILOT.md#launch-checklist).

The runtime decision is recorded in [the LangGraph proposal](LANGGRAPH-PROPOSAL.md). The application direction and competitor sources are recorded in [the Studio product design](STUDIO-PRODUCT-DESIGN.md).

### Studio project and setup handoff

For paired machines, the task composer offers only projects in the worker's current permission response. Historical task folders remain available for filtering history; they do not grant permission to start another task. Local Studio retains its project-path field. A missing grant or unavailable permission lookup requires refreshing access or asking the workspace Owner.

**Check readiness** explicitly inspects the selected project's environment, provider configuration and check plan. The result describes setup; it does not run the checks, establish successful inference or verify quota. Issues stay visible above the task, with exact commands and package discovery below it. **Use detected checks** applies those commands to this task and invalidates the previous observation. No saved recipe is required for one-off task settings.

Studio refreshes authorization before setup inspection and task creation. A reconnect, provider-settings visit, worker/project change or edited configuration invalidates earlier setup evidence; reconnecting preserves the unsent task and its settings. Manual inspection is optional, while current blockers remain visible and the execution engine performs its own validation on Start task. Team Reviewers go directly to permitted task evidence and their review inbox.

### Task browsing and supporting records

**Task list** opens the selected machine's authorized task browser. **Review queue** uses the existing reviewer eligibility rules. Search, project/status filters and archived receipts remain available there. On compact screens the list uses the working surface; closing it preserves the selected candidate, evidence tab and correction draft. Cmd/Ctrl+K opens search, Escape from the browser returns focus, and choosing a task focuses its title. Background inbox updates can change eligibility without dismissing the list.

Open a task's **Details → Pilot measurements and human assessments** for optional evaluation records. This loads on demand and retains unsent values when switching evidence tabs or collapsing the disclosure. Owner/Developer comparison recording and permitted human observation labels remain separate from task approval and delivery. **Task list → Pilot report** offers a report-only export for the selected worker, including when no task is selected.
