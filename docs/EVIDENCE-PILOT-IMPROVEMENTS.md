# Evidence and pilot evaluation changes

This change extends the 1.4.0 development preview. Public downloads remain pinned to 1.3.0. It does not open the pilot, publish a release or establish comparative quality.

## Recorded observations

Each new check and review receives an immutable observation ID, canonical JSON SHA-256, phase/attempt identity and before/after workspace fingerprints. Final checks and the combined independent review share a verification-attempt identity. Check specifications, reviewed patches and review requirements have their own digests.

The append-only worker journal receives the observation before the mutable run result is updated. Interrupted checks, unavailable environments, cancelled reviews and discarded malformed reviewer responses can therefore remain inspectable and labelable without an approvable candidate. A new verification attempt immediately makes the previous attempt historical.

`readonly-workspace-state-v1` and `managed-workspace-state-v1` identify different recorded workspace inputs. They are not Git tree object IDs. `canonical-json-sha256-v1` identifies the observation content. IDs and content hashes identify records; portable records are not signed attestations.

New evidence must match its journal entry, final attempt, candidate workspace and captured verification contract before integration and candidate capture. Capture checks the workspace again after assembling the candidate identity. Changing code, Git state, the request or required checks invalidates the applicable evidence. Existing legacy records retain their previous receipt bytes, candidate digests and behavior.

New verification records use contract 1.2 and include safe observation identities, including journal-only observations. Snapshot downloads are available before application. Saved older records are returned unchanged. Exports omit prompts, raw sessions, absolute workspace paths and command output; the authorized worker retains the underlying local evidence.

## Studio result and evaluation

The task result separates current final checks, independent model review, human approval, local application and GitHub delivery. Baseline checks appear separately. Failed, unavailable, skipped and unrecorded evidence have distinct presentations. Historical passes do not establish current verification, and successful commands establish only their recorded coverage.

`POST /api/pilot/benchmark` accepts legacy measurements and an optional versioned `evaluation` object. New measurements support paired comparison IDs, attempt order, all failure outcomes, nullable elapsed and active human time, setup/review portions of the total, declared baseline scheme, provider settings, configured budgets and observed usage. Missing values stay unknown. Matching an external attempt's declared baseline remains a participant claim, not proof of its actual execution or equal resources.

`POST /api/pilot/observations` binds a human classification to a workflow, immutable observation ID and content digest. An optional finding index selects an existing review finding. The server records the authenticated actor and time. Labels are immutable annotations; they do not change check, approval or delivery gates.

Reports cover the selected worker's latest 100 authorized workflows and retained authorized ancestor effort for their revision lineages. Incomplete lineage and capped or invalid observations stay explicit. Distinct root tasks count as repeat task activity; revisions do not. Linked recovery/steering events count once. Readable observation selectors include failed history absent from the current result.

The additive measurement tables preserve older records. Requests are actor/workspace scoped and idempotent; conflicting reuse is refused. Team project permissions and current membership apply to inspection and mutations, including queued dispatch. Workers advertise `pilot-evaluation-v1` and `pilot-observations-v1`; unsupported workers require an update.

Provider session and repair records also retain bounded, sanitized pre-tool audit observations when supplied. Missing, malformed or truncated audits remain explicit. Observing a hook does not prove complete tool coverage. Tool permissions and execution budgets are unchanged.

## Presentation and pilot boundaries

The website remains the installation entry point, with Studio for tasks and reviews. Provider restrictions appear beside the provider list. Connected-workspace onboarding requires the operator-supplied preview before pairing; public install commands appear separately. The modernization exercise, compatibility contract and setup guide have direct links.

Use [the evaluation protocol](PILOT-EVALUATION.md) for comparisons against a developer's usual native-agent workflow. Record every failure and revision, total human attention and independent assessment. Cost, demand, repeat use and willingness to pay require observed evidence. Enrollment and commercial arrangements remain manual.

## Verification and remaining acceptance

Final verification on macOS, October 11, 2026:

| Check | Result |
| --- | --- |
| Full backend suite, Python 3.13.14 | 682 discovered: 680 passed, 2 platform skips |
| Full backend suite, Python 3.10.18 | 682 discovered: 680 passed, 2 platform skips |
| Frontend behavior and hosted suites | Passed, including 53 product behavior cases |
| Default, hosted and cloud builds | Passed; both Vercel build-output modes prepared without deployment |
| Loopback worker/relay HTTP acceptance | 18 assertions passed, including revisions, peer approval, publication retries and separate delivery |
| Browser inspection | Desktop 1440px and mobile 390px/320px; evidence download, measurements, finding assessment, reviewer handoff and simulated publication checked |
| Installed wheel execution | Disposable reviewed candidate, separate approval/application and unchanged protected check passed |
| Release consistency and archive preparation | Passed; source archives, wheel and SHA256SUMS prepared locally |

The skipped cases require actual Linux bubblewrap and WSL2. Browser testing found and fixed measurement-panel overlap and narrow navigation overflow. Vite still reports the existing large-bundle warning in the full Studio build; no performance improvement is claimed.

Deterministic fixtures simulate providers, accounts and GitHub; they cannot establish live sign-in, provider compliance, GitHub authorization, webhook delivery or production recovery. Builds and artifacts remain unpublished.

One real provider attempt used a disposable copy of the protected parser exercise, Codex and Antigravity, a five-minute run budget and 120-second provider-attempt limits. Antigravity invoked a prohibited tool and was stopped, then a second attempt timed out. The run exhausted its budget without a candidate or project changes. No quota error was observed. That attempt predates the added pre-tool diagnostic persistence; its saved evidence does not establish live hook coverage. It remains a failed acceptance attempt, rather than a completed migration or performance comparison.

Live acceptance still requires a supported provider run, staging configuration, genuine account/revocation checks and a configured GitHub App with a designated test repository. The pilot stays closed until [the launch checklist](PILOT.md) and [staging acceptance](STAGING-ACCEPTANCE.md) pass.
