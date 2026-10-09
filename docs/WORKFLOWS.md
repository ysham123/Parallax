# Saved coding workflows

Studio's Workflows home takes a task through preparation, verification, your approval, and application. You can return after closing the browser or restarting the worker, inspect the same candidate, and decide whether to apply it. A completed candidate does not need another successful build simply because the connection was lost.

## Start a change

1. Open Studio locally, or select an online paired machine in hosted Studio. The project must be approved on that machine.
2. Choose **Verified change**, **Fix a bug**, or **Safe refactor**. These recipes use the same execution stages with different task instructions. Their initial team is Codex coordinating and Claude implementing.
3. Describe a specific outcome. Under **Team, time limit, and recipe settings**, choose providers, models, effort, reusable instructions, and explicit project checks if needed. With no explicit checks, Parallax uses the project's detected checks. Unsupported setup stops for attention.
4. Use **Check readiness**, then **Prepare a verified change**. Parallax builds in private worktrees, obtains independent review, and runs real project checks. It retains the verified candidate without applying it to your working project.
5. Select the workflow in **Recent workflows**. Read the summary, changed files, exact patch, and verification gates. **Open run evidence** shows the underlying tasks, reviews, and command results.
6. Choose **Approve and apply** or **Decline candidate**. Approval is tied to the candidate, original project snapshot, recipe settings, and verification evidence. Parallax checks them again immediately before applying. The application preserves staged work and unrelated files.

After application, download the verification record. It includes the candidate digest, recorded approval, checks, review providers, and preservation results. It omits prompts, raw sessions, absolute project paths, and command output. It is an unsigned evidence record, not a guarantee that every behavior is correct.

## Save a recipe

Adjust the team, time limit, instructions, and checks, enter a name, and select **Save as recipe**. Personal recipes appear in the saved recipe picker. **Save new version** changes the settings used by future starts; existing workflows retain their original template version and complete run specification. Built-in recipes can only be copied.

Instructions and check edits must be saved before starting. Provider selections and the time limit can be changed for a single execution. **Use this task again** fills the composer with the previous task and team and the latest version of its recipe; review those settings before starting a fresh candidate.

## Disconnects and interrupted work

| Situation | What happens |
| --- | --- |
| Browser closes or hosted connection drops | Execution continues on the machine. Reconnect to read progress. |
| Worker restarts while awaiting approval | The same verified candidate remains ready for your decision. No provider call is needed to approve it. |
| Worker restarts during preparation | The workflow offers **Resume saved work**. The engine reconciles its action records and remaining budget before continuing. Restart alone never starts new provider work. |
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

Update both the runtime/relay and paired workers to use these routes. Older workers show an update message in Studio; their existing New run flow remains available. Existing CLI/plugin review, build, and compare behavior is unchanged. The remote MCP tool set is unchanged; workflow approval is exposed in authenticated Studio and the scoped worker API.

## Validation and current scope

The workflow tests use real LangGraph checkpoints, SQLite, Git worktrees, file application, and deterministic providers. They exercise restart before the workflow records an engine run, waiting approval, persisted decisions, interrupted file application, duplicate requests, source and evidence changes, immutable recipes, cancellation, and account/project isolation. Browser QA covers recipe selection, readiness, candidate inspection, worker restart, approval, and receipt download.

This is a coding workflow product feature, not an arbitrary graph editor. It does not add scheduling, shared recipe libraries, uploaded executable templates, or remote MCP approval tools. Actual model quality and provider cost still need evaluation on representative projects with live providers; the deterministic tests do not establish those results.

The design decision is recorded in [the LangGraph proposal](LANGGRAPH-PROPOSAL.md).
