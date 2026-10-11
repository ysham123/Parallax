# Bounded legacy modernization

Evaluate **one component upgrade with a recorded compatibility contract** as a pilot use case. Keep the accepted individual and small-team pilot. This is a task focus to test, not evidence for a new enterprise product or demand for whole-system rewrites.

The prospective user is an experienced maintainer who owns a working repository, knows which behavior consumers depend on, and has a specific upgrade backlog item. A useful first task replaces a deprecated construction API, upgrades one library adapter, or retires one component while retaining its public interface. The owner must supply an executable baseline, allowed changes, an approved target and a rollback boundary. If these are absent, characterization and scoping are the first deliverable; a passing generated test suite cannot substitute for unknown business requirements.

## Existing alternatives

Official capabilities checked October 11, 2026. These are vendor documentation, not independent accuracy or productivity measurements.

| Alternative | Documented capability | Implication for Parallax |
| --- | --- | --- |
| [GitHub Copilot .NET upgrade](https://learn.microsoft.com/en-us/dotnet/core/porting/github-copilot-upgrade/dotnet-overview), updated September 25, 2026 | C#/Visual Basic framework, project-file, library and architecture upgrades; custom upgrade instructions. | A generic promise to modernize .NET competes with an existing domain-specific product. |
| [GitHub Copilot modernization for Java](https://learn.microsoft.com/en-us/azure/developer/java/migration/migrate-github-copilot-app-modernization-for-java), updated June 16, 2026 | Assessment, transformations, build/tests, behavioral unit tests and custom skills; Maven/Gradle and Java/Spring upgrades, plus Azure migration artifacts. | Specialized agents, reusable instructions and verification are already offered. Coordination alone is insufficient differentiation. |
| [AWS Transform custom](https://docs.aws.amazon.com/transform/latest/userguide/custom.html) | Natural-language custom transformations, language/API/framework upgrades, validation commands and reusable transformation definitions, including organization-specific changes. | Provider choice and a familiar local approval workflow are hypotheses to test; reusable recipes alone are not a defensible advantage. |
| [AWS Transform mainframe](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-mainframe.html) | Mainframe analysis, business-logic extraction, decomposition and Java refactoring with human inputs. | Parallax has no demonstrated mainframe analysis or COBOL conversion capability. Do not imply equivalent scope. |

The proposed wedge is the maintainer who wants a small patch on a user-owned worker, review from an independent configured provider, a saved-candidate correction and explicit human delivery. The implementation may fit that need, but fit, willingness to switch, reliability and willingness to pay remain unmeasured. Compare it with the maintainer's existing single-agent workflow on the same acceptance contract before making a commercial claim.

## Minimal workflow

1. The maintainer selects one component and freezes the versioned contract, representative inputs/outputs, protected files and required environments. Keep genuine independent acceptance cases outside the agent-readable candidate when possible.
2. Run baseline characterization against the captured source. Preserve failures and known limitations. A target-upgrade guard may intentionally fail on the old component; label baseline characterization and final target acceptance separately.
3. The coordinator assesses compatibility and decomposes the bounded task. An implementer edits only the allowed scope in an isolated candidate. Instructions can ask for a domain or compatibility perspective; they do not create new runtime role types or prove expertise.
4. Run final checks against the combined candidate and obtain independent provider review. The reviewing provider must not have contributed to that candidate. With the current two-provider flow, the coordinator assesses/decomposes and independently reviews, while the other provider implements; do not advertise extra domain-reviewer agents that did not run.
5. Inspect the exact diff and evidence. Request an explicit saved-candidate revision when needed, retaining the original baseline and fresh evidence/approval. A changed source fingerprint requires a fresh task.
6. Approve the exact candidate, then explicitly apply locally or separately publish a configured draft PR. Team approval needs another authorized human. Neither approval nor publication means deployment. The maintainer owns any ordinary Git rollback and any external consumer/data rollback.

## Runnable example

[The settlement fixture](../examples/legacy-modernization/README.md) is a dependency-free synthetic batch CLI with a fixed CSV input/report, versioned manifest and 34 black-box characterization tests. Only `settlement.py` may change. The parser upgrade must preserve per-transaction half-up rounding, refunds, inclusive dates, rejected input, output-file preservation, Unicode/CSV bytes and unusual option values.

The deprecated API is specifically `OptionParser(option_list=...)`. Current Python documentation retains optparse and describes subtle compatibility differences when migrating to argparse. This example demonstrates an owner-chosen parser standardization; it does not identify a vulnerable or removed module. [Python documentation](https://docs.python.org/3.13/library/optparse.html#creating-the-parser).

From `examples/legacy-modernization`, verify the unmodified baseline:

```sh
python3 acceptance/verify_candidate.py
```

The final task check adds `--require-modernized`. On the baseline, characterization passes and that guard intentionally fails. The guard verifies imports; a human must confirm argparse actually implements the CLI. The suite is public characterization evidence, not a hidden oracle or proof of complete business equivalence. The original fixture remains legacy so it can be delegated; a temporary local migration validates the exercise separately.

Use **Modernize one component** when included in the supplied preview, or **Safe refactor** with the fixture's explicit instructions. Follow [FIRST-TASK.md](FIRST-TASK.md) to configure the local worker, two usable independent providers, sandbox and delivery. A recipe does not install a language runtime or expand permissions. Required Python environments must already be available and their executable paths recorded.

## Demand and quality test

Recruit maintainers from the already agreed individual and small-team pilot who can supply a real bounded backlog item and frozen acceptance criteria. Record whether they complete setup, submit a suitable task, accept a patch, return with another task and agree to the manual commercial arrangement. Interview answers and this synthetic fixture are insufficient demand evidence.

Use separate individual/team cohorts and paired comparable tasks with the same acceptance criteria, alternating which workflow is tried first. Record active human setup, supervision, review and correction time separately from wall/execution time. Count every revision from the original baseline, including failed, cancelled and quota-blocked runs. Record independently accepted behavior regressions, rejected patches, total observed usage and explicitly unknown cost; compare complete lineages rather than only successful first candidates. Define each participant's worthwhile improvement and acceptable failure boundary before the trial. Continue this use case only when real maintainer tasks meet those boundaries and yield repeated voluntary use; narrow or stop it when preparation/review burden, unsafe regressions or unsuitable tasks dominate. See [PILOT.md](PILOT.md).

The October 11 live fixture attempt established native Codex coordination, then stopped after Antigravity refused implementation because its individual quota was exhausted. No patch or candidate approval resulted; the saved run retains diagnostics and consumed budget. A real migration, deliberate correction, fresh review, human approval and local delivery must still be exercised end to end. Hosted/team use additionally needs real account isolation, revocation and reviewer handoff. GitHub use needs configured staging/App credentials and live publication, CI/webhook/recovery evidence. Deterministic fixture tests do not close these gates or establish enterprise security, migration scale, superior economics or paid demand.
