# Constellation architecture

The developer's question is an outcome: what to build, which project to change, and which constraints to preserve. New run setup gives that outcome a coordinator, worker connections, review roles, model/effort selections, and bounded execution limits. Studio keeps these choices separate from the graph produced during execution.

The Workspace opens on project work. Its agent graph represents configured coordinator, implementation and reviewer sessions, with edges derived from recorded dispatch and review associations. The task graph represents tasks, dependencies, repairs, independent reviews and combined checks. A task inspector exposes assigned ownership, acceptance criteria, attempts, reviewer findings, and check evidence. The activity trace represents observed events: provider sessions, tool calls, coordinator actions, permissions, retries, and verification. It does not visualize private model reasoning. Both graphs can be panned and zoomed; selection does not reset the viewport or change dependencies. An accessible list reaches the same inspector. Narrow panels use focus-contained history and inspection drawers.

## Runtime decisions

The coordinator returns schema-constrained actions. Every coordinator turn is a fresh provider session compiled from durable run state, so no transcript accumulates across decisions; model and effort stay pinned from earlier turns. The runtime rejects duplicate IDs, cyclic dependencies, unavailable connections, and invalid ownership. It journals an action before executing it, then records completion or interruption. It owns worker limits, repair limits, cumulative run time, process groups, checkpoint steering, and integration. Provider-native recursive teams stay disabled.

Resume is reconciliation. It finds saved effects, private workspace fingerprints, matching provider sessions, and process identities. A provider conversation is resumed only to continue the same interrupted attempt, matched by attempt number; repairs keep the attempt's code but start a fresh session. It does not interpret an issued dispatch or integration record as proof of completion. An interrupted command with an unknown result needs attention. Applied integration has its own durable journal and cannot be applied twice.

Git changes start from the effective working tree using a temporary index. Worker and integration worktrees live outside the project. Changes are reviewed independently and combined privately. Source fingerprints, destination rechecks, reviews, and actual project checks gate application. Unrelated destination edits require refreshed verification. Conflicting edits preserve the patch and workspaces for inspection.

## Context isolation

Each provider call receives a context packet compiled for its role from durable state. A role compiler names every section an agent may see, each with a character budget; low-priority sections are trimmed first so a packet always fits the provider limit, and the request, task and variant directive are never cut. Sections are fenced with a hash of their own text, rendering is deterministic, and private run and checkout paths in tool output are rewritten to placeholders. A content-free manifest of section names, sizes and hashes is recorded as a `context` event before every call, and session records carry the role and packet hash.

- **Coordinator:** request, team, limits, checks, a compact task table, combined evidence, a diffstat with a fitted excerpt, patches it chose to inspect, the recent action journal, rejection feedback, its own memo from the previous turn, project memory, steering and status. Never attempt records, session ids, paths, provider answers or transcripts.
- **Worker:** request, its own task, the dispatch brief, a repair brief built only from its own previous attempt, completed dependencies, failing combined checks, baseline checks, project instructions and steering. Never another task's findings or a sibling variant's directive.
- **Reviewer:** request, the original requirements, the candidate's own patch and the candidate's own evidence. Never the implementer's identity or narrative, earlier reviews or other candidates.
- **Synthesizer:** assessments labeled A, B, C; the legend is attached to the summary afterwards.

This is push isolation: it governs what Parallax sends. Pull isolation depends on the provider's sandbox. Antigravity's gated tools and API agents are confined to their checkout; Codex's native sandbox does not confine reads, so a Codex agent could read sibling worktrees or the state directory. Do not store secrets there on the assumption that agents cannot read it.

## Exploration

In Build runs the coordinator can explore a task with two or more substantially different approach directives, optionally on different implementers. Variants run in parallel, each in its own checkout and sandbox and each seeing only its own directive. Each is reviewed against the task's requirements without its variant id or directive, then runs the project checks in its own checkout. Passing variants become candidates; nothing merges until the coordinator selects one, which resolves the task and discards the rest. There is no engine loop deciding what to try: the coordinator chooses repair, exploration or resolution from evidence, and budgets only cap it.

## Project memory

Each project has local memory on the executing machine, keyed by its real path and Git root commits. After a run, its facts are projected through a whitelist (goal, approaches, outcomes, review verdicts, check results); patches, tool output and provider answers are never stored. A fresh, quiet distiller session may then propose up to three conditional observations citing that evidence; the runtime validates grounding, polarity, scope and hygiene, merges duplicates, and adjusts each lesson's strength from supporting and contradicting runs. Only coordinators read memory, as dated records, through a primer computed once per run and a `search_ideas` action. The runtime itself never writes memory text into the run record or events (events carry counts and reason codes), and stored text has runtime paths scrubbed and project paths made relative. A coordinator can still quote memory in its own memo, query or summary, and those are part of the run record and any hosted mirror. `GET /api/memory`, `PATCH /api/memory/lessons/{id}` and `DELETE /api/memory` inspect, disable and forget it locally; `PARALLAX_MEMORY=off` turns it off.

## Connection and executor boundary

A CLI connection delegates inference and permitted tools to the installed native CLI. An API connection delegates inference to an HTTPS endpoint and provides runtime-owned tools. Protocols are Responses, Anthropic Messages, and OpenAI-compatible Chat Completions. API catalogs use model discovery where available and maintained/user-declared capability metadata. Credentials are Keychain items or environment references; run records contain connection IDs and effective settings, not keys.

API consult/coordinator sessions expose only list/read tools. API worker writes must match file ownership. Supported project verification commands execute with a macOS sandbox, a private HOME, a minimal environment, bounded output, and cancellation. Other platforms fail command execution explicitly. Native permissions differ and must pass provider-specific compatibility checks. CLI init tool lists alone do not prove enforcement; denial canaries and filesystem checks provide evidence.

Remote inference is a configured API endpoint. A future remote executor is a different capability: it must authenticate the remote worker, negotiate tool and sandbox capabilities, transfer a private snapshot, produce verifiable artifacts, and reconcile interrupted processes. Local Studio will remain loopback-only. Remote MCP or hosted-agent connections require an explicit tool allowlist and separate authorization; they must not bypass review and integration gates.

## Product sources

The design takes relevant patterns from [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/), including manager agents and observable tool activity. [Saved workflows](WORKFLOWS.md) embed [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) to coordinate preparation, durable approval, and application. Parallax's typed local action runtime still owns provider execution, verification, and recovery; it does not embed the OpenAI Agents SDK.

[React Flow accessibility](https://reactflow.dev/learn/advanced-use/accessibility) informs graph keyboard controls and node inspection. Native and API protocols follow the linked [OpenAI function-calling](https://developers.openai.com/api/docs/guides/function-calling), [Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort), [xAI reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning), and [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai) documentation. Catalogs and compatibility tests must be refreshed when providers change.
