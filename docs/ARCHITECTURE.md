# Constellation architecture

The developer's question is an outcome: what to build, which project to change, and which constraints to preserve. New run setup gives that outcome a coordinator, worker connections, review roles, model/effort selections, and bounded execution limits. Studio keeps these choices separate from the graph produced during execution.

The Workspace opens on project work. Its agent graph represents configured coordinator, implementation and reviewer sessions, with edges derived from recorded dispatch and review associations. The task graph represents tasks, dependencies, repairs, independent reviews and combined checks. A task inspector exposes assigned ownership, acceptance criteria, attempts, reviewer findings, and check evidence. The activity trace represents observed events: provider sessions, tool calls, coordinator actions, permissions, retries, and verification. It does not visualize private model reasoning. Both graphs can be panned and zoomed; selection does not reset the viewport or change dependencies. An accessible list reaches the same inspector. Narrow panels use focus-contained history and inspection drawers.

## Runtime decisions

The coordinator uses a dedicated session and returns schema-constrained actions. The runtime rejects duplicate IDs, cyclic dependencies, unavailable connections, and invalid ownership. It journals an action before executing it, then records completion or interruption. It owns worker limits, repair limits, cumulative run time, process groups, checkpoint steering, and integration. Provider-native recursive teams stay disabled.

Resume is reconciliation. It finds saved effects, private workspace fingerprints, matching provider sessions, and process identities. It does not interpret an issued dispatch or integration record as proof of completion. An interrupted command with an unknown result needs attention. Applied integration has its own durable journal and cannot be applied twice.

Git changes start from the effective working tree using a temporary index. Worker and integration worktrees live outside the project. Changes are reviewed independently and combined privately. Source fingerprints, destination rechecks, reviews, and actual project checks gate application. Unrelated destination edits require refreshed verification. Conflicting edits preserve the patch and workspaces for inspection.

## Connection and executor boundary

A CLI connection delegates inference and permitted tools to the installed native CLI. An API connection delegates inference to an HTTPS endpoint and provides runtime-owned tools. Protocols are Responses, Anthropic Messages, and OpenAI-compatible Chat Completions. API catalogs use model discovery where available and maintained/user-declared capability metadata. Credentials are Keychain items or environment references; run records contain connection IDs and effective settings, not keys.

API consult/coordinator sessions expose only list/read tools. API worker writes must match file ownership. Supported project verification commands execute with a macOS sandbox, a private HOME, a minimal environment, bounded output, and cancellation. Other platforms fail command execution explicitly. Native permissions differ and must pass provider-specific compatibility checks. CLI init tool lists alone do not prove enforcement; denial canaries and filesystem checks provide evidence.

Remote inference is a configured API endpoint. A future remote executor is a different capability: it must authenticate the remote worker, negotiate tool and sandbox capabilities, transfer a private snapshot, produce verifiable artifacts, and reconcile interrupted processes. Local Studio will remain loopback-only. Remote MCP or hosted-agent connections require an explicit tool allowlist and separate authorization; they must not bypass review and integration gates.

## Product sources

The design takes relevant patterns from [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/), including manager agents and observable tool activity, and [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), including checkpoints and durable state. Parallax retains its own typed local action runtime; it does not claim to embed either orchestration SDK.

[React Flow accessibility](https://reactflow.dev/learn/advanced-use/accessibility) informs graph keyboard controls and node inspection. Native and API protocols follow the linked [OpenAI function-calling](https://developers.openai.com/api/docs/guides/function-calling), [Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort), [xAI reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning), and [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai) documentation. Catalogs and compatibility tests must be refreshed when providers change.
