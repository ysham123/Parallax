# Saved coding workflows

Studio opens on **Tasks**, with a searchable queue and a workspace for the selected task. Filter the queue by project or status, follow the team's activity, and inspect changes, checks, and reviews beside it. You can return after closing the browser or restarting the worker, inspect the same candidate, and decide whether to apply it. A completed candidate does not need another successful build simply because the connection was lost.

## Start a change

1. Open Studio locally, or select an online paired machine in hosted Studio. The project must be approved on that machine.
2. Select **New task**, choose the project, and describe a specific outcome. The **Workflow** selector offers Verified change, Fix a bug, Safe refactor, and your saved recipes. Built-in recipes use the same execution stages with different task instructions. Their initial team is Codex coordinating and Claude implementing.
3. Under **Configure team, checks, and reusable instructions**, choose providers, models, effort, time limit, reusable instructions, and explicit project checks if needed. With no explicit checks, Parallax uses the project's detected checks. Unsupported setup stops for attention.
4. Use **Check readiness** to inspect package discovery, instruction files, command isolation, and the actual configured or detected check commands. Discovery does not execute checks. **Use detected checks** copies commands into the recipe editor for saving. Then **Start task**: Parallax builds in private worktrees, obtains independent review, and runs real project checks. It retains the verified candidate without applying it to your working project.
5. Select the task in the queue. **Changes** shows the exact patch by file; **Checks** shows command results; **Reviews** shows independent findings; **Details** shows the saved settings. **Open agent graph** shows the underlying agents, tasks, and dependencies.
6. Choose **Approve & apply** or **Decline**. Approval is tied to the whole candidate, original project snapshot, recipe settings, and verification evidence. Parallax checks them again immediately before applying. The application preserves staged work and unrelated files.

After application, download the verification record. It includes the candidate digest, recorded approval, checks, review providers, and preservation results. It omits prompts, raw sessions, absolute project paths, and command output. It is an unsigned evidence record, not a guarantee that every behavior is correct.

## Follow work and give direction

Use the queue's project filter, search, and status views to find tasks awaiting approval, in progress, needing attention, or completed and closed. Selecting a task keeps its activity and evidence together. Filter changed files and select a file to inspect its unified diff, with old and new line numbers. Large files are paged in groups of 400 rows; the patch download retains the entire diff.

While the team is preparing a change, **Direct the team** sends guidance to the active run. After execution, **Draft follow-up** opens a linked task with your new request, the original goal, and the parent's recorded result. It preserves the parent's exact workflow version and complete settings, including checks, package roots, provider connections, and limits. The composer permits explicit participant and time-limit changes before starting. Parent and child remain accessible through **Related tasks**.

A follow-up builds a separate candidate from the **current project**. It does not reuse unapplied code from the parent. Its digest and approval decision are independent. Long prior result summaries are explicitly truncated to 2,000 characters; the full parent record remains linked, and the original goal and new request remain intact. The worker authorizes both tasks and requires the same project. **Make a standalone task** removes the link and restores the latest selected recipe defaults.

Unsent feedback survives task switching, and an open new-task draft survives navigation to the agent graph. These browser drafts are not durable across page reload. **Resume task** continues interrupted work, and **Stop task** stops work when available.

## Save a recipe

In **New task**, adjust the team, time limit, instructions, and checks, enter a name, and select **Save as recipe**. Personal recipes appear in the **Workflow** selector. **Save new version** changes the settings used by future starts; existing tasks retain their original template version and complete run specification. Built-in recipes can only be copied.

Instructions and check edits must be saved before starting. Provider selections and the time limit can be changed for a single execution. **Use task again**, available for declined or stopped tasks, opens a linked draft with the previous request and exact saved recipe version; review those settings before starting a fresh candidate.

## Disconnects and interrupted work

| Situation | What happens |
| --- | --- |
| Browser closes or hosted connection drops | Execution continues on the machine. Reconnect to read progress. |
| Worker restarts while awaiting approval | The same verified candidate remains ready for your decision. No provider call is needed to approve it. |
| Worker restarts during preparation | The task offers **Resume task**. The engine reconciles its action records and remaining budget before continuing. Restart alone never starts new provider work. |
| Approval was recorded just before a restart | Resume reconciles the recorded decision and saved application state. A second approval cannot replace it. |
| File application committed before the result was saved | Resume reconciles the durable file transaction and records the receipt without applying the patch again. |
| An interrupted application cannot be proved complete | Parallax reports attention and does not replay the ambiguous write. Inspect the project and prepare a new workflow. |
| Project files, Git staging, candidate, or evidence changed | The old approval cannot apply the candidate. Prepare a fresh workflow against the current project. |
| Candidate declined or workflow stopped | The project remains unchanged; saved evidence remains available. |

Execution time limits carry across restarts. Time waiting for approval does not consume that budget. Up to three workflows can be active on a worker; the engine still allows only one implementation run per project. A candidate waiting for approval does not hold the project lock. A later project edit can therefore invalidate it.

## Storage and execution

LangGraph is an internal workflow coordinator. Its graph is `prepare → approval → apply`; rejection ends after approval. The existing Parallax engine owns provider dispatch, isolated worktrees, reviews, checks, repair budgets, and process recovery. WorkspaceManager owns file application and preservation checks.

Workflow records and immutable recipe versions live in the worker's `state.sqlite3`. LangGraph checkpoints live in `workflows.sqlite3` in the same private state directory. Graph state refers to workflow IDs; run records remain the source of execution evidence. Checkpoint serialization disables pickle and arbitrary object loading. Workflow invocation explicitly disables LangSmith tracing, including when tracing is enabled in the parent environment.

An immutable workflow operation key is saved atomically with each engine run before provider dispatch. Checkpoint replay reuses that identity. This prevents duplicate run creation across the tested crash boundaries; it does not promise exactly-once external provider execution under every possible failure.

Hosted Studio uses the existing account-scoped worker relay. Owners can reach only their paired machines, and workers enforce their approved project paths. Requested workflow summaries, prompts, settings, and candidate evidence can be cached by the relay under its existing retention and size limits. Provider credentials stay on the machine. Offline cached evidence cannot authorize work. Recipes are scoped to the selected machine in this release.

Update both the runtime/relay and paired workers to use these routes. Older workers show an update message in Studio; their existing direct controls remain available under **Advanced run**. Existing CLI/plugin review, build, and compare behavior is unchanged. The remote MCP tool set is unchanged; workflow approval is exposed in authenticated Studio and the scoped worker API.

## Validation and current scope

The workflow tests use real LangGraph checkpoints, SQLite, Git worktrees, file application, and deterministic providers. They exercise restart before the workflow records an engine run, waiting approval, persisted decisions, interrupted file application, duplicate requests, source and evidence changes, immutable recipes, cancellation, and account/project isolation. Linked-task tests cover inherited settings and old recipe versions, independent candidates, restart and chain context, bounded summaries, idempotency, and unauthorized or cross-project parents. Browser QA covers recipe selection, readiness, candidate inspection, linked follow-ups, live guidance, draft preservation, worker restart, approval, and receipt download.

This is a coding workflow product feature, not an arbitrary graph editor. It does not add scheduling, shared recipe libraries, uploaded executable templates, or remote MCP approval tools. Actual model quality and provider cost still need evaluation on representative projects with live providers; the deterministic tests do not establish those results.

The runtime decision is recorded in [the LangGraph proposal](LANGGRAPH-PROPOSAL.md). The application direction and competitor sources are recorded in [the Studio product design](STUDIO-PRODUCT-DESIGN.md).
