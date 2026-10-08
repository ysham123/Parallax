# Live validation · 1.2.0

Real native CLI inference on a disposable copy of `tests/fixtures/python-service`, run on macOS on October 7, 2026, with a scratch state directory. It's a small fixture, not a user study. Machine-readable results, without prompts, paths or session identifiers, are in [live-1.2.json](live-1.2.json).

Providers: Codex 0.160.1 (gpt-6.1-sol), Claude Code 2.1.293 (sonnet), Grok Build 1.0.46 (grok-4.7), Antigravity 1.3.1 (gemini-3.8-flash). All four reported ready.

## Results

| Scenario | Outcome |
| --- | --- |
| Review, Codex synthesizing Claude and Grok | Completed. Both reviewers found the defect independently, and the synthesis labeled them A and B with the legend recorded afterwards. Every call recorded a content-free context manifest with no truncation. |
| Build, invoice total fix | Completed with all five integration gates passed. The coordinator ran 12 turns, each in a fresh session, and Codex accepted the strict action schema. The runtime rejected a coordinator-invented check command, as designed. A staged file and an untracked file in the user's project were preserved; the staged index hash was identical before and after. Distillation ran, but its one lesson was rejected for length. |
| Claude Code plugin, `/parallax:review` | Completed. The plugin was installed from a local marketplace into a scratch project only. A non-interactive Claude Code session ran the command. The plugin started the MCP runtime from its install folder and passed the absolute repository root. Codex synthesized Claude and Grok reviews blind, and Claude's reply reported each reviewer's evidence. The plugin was removed afterwards. |
| Build, discount feature with two designs | Exploration worked end to end: three rounds of isolated keyword-argument and helper variants, blind reviews, independent checks, and selection. The coordinator's packet included Project memory from the previous run. The run then looped on unverifiable process criteria and was cancelled; see finding 3. |

## Findings and fixes

1. **Integration reviews had no acceptance criteria.** The combined reviewer received only a "Combined integration" title. It rejected a correct `sum(values)` fix, and the coordinator added an unnecessary second task. The reviewer now receives every completed task's acceptance criteria and owned files, which come from the plan and never from an implementer.
2. **A reviewer misread the candidate patch.** It claimed the change was absent, although its checkout contained it. Review instructions now say the checkout already contains the candidate, and explain the patch's removed and added lines. A reply with no verdict is retried once in a fresh session, then reported as `no_verdict` rather than as a rejection.
3. **Process criteria blocked isolated reviews.** The coordinator wrote "both designs explored before selection" into acceptance criteria. Isolated reviewers can't see siblings, so they rejected correct candidates. Coordinators are now told that acceptance criteria describe observable behavior, never process. Reviewers are told that process steps are handled outside their view and are no reason to reject.
4. **Rejected variants cost whole rounds.** A failed variant can now be repaired inside its round, within the repair budget, instead of re-running every variant.
5. **The distiller didn't know the lesson limits.** Its instructions and schema now state 160 characters for `when` and 300 for `observed`.

Each fix has a regression test.

## Not yet covered

- A live rerun of the discount scenario with these fixes. The rerun started but stalled when the laptop slept nine seconds into its second coordinator turn, and was cancelled.
- Live API transports and hosted execution.
