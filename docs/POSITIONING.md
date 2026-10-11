# Why Parallax

**Delegate a change. Get back a reviewed patch.**

Parallax coordinates your existing coding agents to prepare a change. Inspect its reviews and project checks, request a correction, then approve local application or a configured draft pull request. The website explains the workflow and installation; Studio, plugins and the CLI are entry points into the same runtime.

It is for developers who want to delegate a bounded feature or repair, mix providers deliberately, and return to one result with evidence. Their project often already has staged work, unfinished edits and untracked files. They should be able to choose a team without becoming its full-time scheduler or moving into another IDE.

## The product promise

The unit of work is an outcome with acceptance criteria. The unit of delivery is a patch with a verification record. Workers implement in private snapshots; a different provider reviews their changes; the runtime checks the combined candidate before application. Failed reviews and checks become repair work with a retained history. The runtime preserves the developer's staging and unrelated edits, or stops with the work available for inspection.

Model choice matters because a second perspective can expose a concrete error. It is a choice, not a guarantee that more agents outperform one. Parallax defaults to quality and records requested and effective settings so the team can be reproduced deliberately. CLI subscriptions and API connections can coexist; custom compatible models have an explicit capability catalog.

The task graph answers practical questions: What is blocked? Which attempt failed? Who reviewed the replacement? What is ready to integrate? It leads into the diff, recorded check output and verification gates. The graph does not expose private reasoning or promise that a visually complete plan is correct.

## What makes this a focused product

The focus is the complete delivery workflow: isolated implementation, independent review and repair, evidence tied to the applicable candidate, explicit human approval and careful delivery. The development preview supports personal and explicitly created team workspaces on user-owned workers. Team approval requires someone other than the requester. Approval, local application and GitHub publication are separate recorded actions. Legacy CLI/plugin runs retain their existing integration behavior.

Current products already do substantial work in this space. [DeckSpace Team](https://deckspace.dev/deckspace/docs/maestro/) documents recorded commit/tree review snapshots, a separate integration worktree, combined checks and recovery. [Superset](https://docs.superset.sh/orchestration) coordinates mixed coding agents in separate workspaces. [Conductor](https://www.conductor.build/docs/concepts/workflow) includes review and pull-request delivery. [OpenHands](https://www.openhands.dev/blog/20260506-the-verification-stack) documents automated verification, code review, functional QA and repair loops. These are documented capabilities, not comparative quality measurements. Orchestration, worktrees and verification alone are not novel claims.

Parallax should earn preference through easier setup, dependable acceptance and less developer attention on repeat tasks. Start with experienced developers and small teams that already use coding agents, own an existing repository and have executable acceptance checks. Bounded refactors, bug fixes and [one-component modernization](LEGACY-MODERNIZATION.md) are task classes to test. Demand, willingness to switch and willingness to pay remain hypotheses.

Keep local use available without a hosted account. Connected workspaces add explicit worker pairing, project permissions and reviewer handoff. The public source download and the supplied development preview are separate distributions; the preview is not a public release or an open pilot. Managed cloud execution, unrestricted system rewrites, automatic merge and deployment remain outside this release.

## Evidence and launch standard

The historical four-provider acceptance build starts from failing code. Codex coordinates, Claude and Antigravity implement, Grok rejects an incomplete implementation and reviews the repaired candidate. The unchanged acceptance command finishes with eight passing tests. The final patch changes two files. This is historical fixture evidence, not current adapter acceptance, a benchmark or proof of market demand. The development preview currently blocks native Grok under its isolation policy; Claude Code and Antigravity expose restricted file tools with shell and content-search tools disabled. Diagnostics, supported transport and available quota must be checked before execution.

Release validation also covers dirty-worktree preservation, concurrent edits, failed-check gates, permission denials, provider-specific resume, malformed streams, cancellation, recovery and duplicate-action prevention. Studio is checked on desktop and mobile, with keyboard interaction, light mode and reduced motion. API protocols are tested against deterministic endpoints; live API inference requires real account credentials and is reported separately.

The next market test is whether developers complete useful tasks repeatedly with less coordination effort. Observe first-run setup success, useful patches delivered, repair and check rejection rates, active human time, unintended file changes and repeat use. Compare against the developer's usual native-agent workflow on the same starting tree, acceptance criteria and configured time budget. Include its normal manual review and count every failed or blocked attempt. Human assessment of defects is separate from agent agreement; unreported usage and cost stay unknown. Numerical productivity or quality claims require measured customer results. See [the evaluation protocol](PILOT-EVALUATION.md) and [live launch gates](PILOT.md).
