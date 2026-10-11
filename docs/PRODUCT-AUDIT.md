# Product audit: invited pilot

Audit date: October 9, 2026. Scope: the local `codex/delegation-pilot` implementation, its product copy, onboarding, workflow controls, privacy text and pilot measurement interfaces. This is a source and workflow audit. Browser evidence from the team uses deterministic providers and a mocked GitHub App; it does not prove live provider performance, staging authorization or real repository publication.

## Product decision

The local implementation exposes the intended sequence: configure a project, delegate, inspect a candidate and evidence, request correction, obtain human approval, then explicitly apply or publish a draft PR. Team handoff uses distinct authenticated humans. Local CLI/plugin and legacy Studio behavior remain supported.

Keep paid enrollment closed. A reviewed implementation and passing deterministic tests are preparation for acceptance; the live delegation, two-account onboarding and GitHub delivery gates remain required. No productivity, success-rate or provider-cost claim is established.

## Findings and disposition

| Severity | Finding and concrete user path | Disposition |
| --- | --- | --- |
| P1 | README and the workflow guide described a linked current-project task as the only correction path and presented every approval as file application. Users following them would miss saved-candidate revision and separate delivery. | Documentation corrected to distinguish revision/current-project starts, contract 2.0 decisions/delivery and legacy contract 1.0 behavior. |
| P1 | Hosted privacy wording implied all history or agent sessions stayed on the machine. `WorkerRuntime.snapshot` mirrors full run results and events; a result contains the task prompt/settings and session metadata, and non-quiet provider events can contain agent output. | README and pilot documentation now name that content. UI/legal copy was corrected by the integration owner; private working copies and complete local provider-session files remain distinguished from mirrored evidence. |
| P1 | Revise a valid parent, hit provider failure in its child, stop that child, then return to the original parent: the backend permits retry of the saved superseded candidate, but the UI hid **Revise candidate** on `superseded`. | Integration owner restored the action and added a frontend regression. The pilot recovery guide now describes returning to the saved parent. |
| P1 | Original task → revision A completes awaiting approval → revise A again: the lineage guard counts A itself as an active revision and refuses the requested child. Declining A first is an avoidable workaround; an approved A cannot simply be cancelled. | Fixed: exclude the selected parent from the other-active-revision check. Two failing-before/passing-after regressions verify second-generation awaiting/approved correction, baseline and parent preservation across restart, and active-sibling refusal. |
| P2 | Public entry promised running from anywhere without stating that controls and team project-filtered inspection require an online paired worker. A sleeping machine cannot run work. | Source copy and documentation now state the online requirement and distinguish personal cached evidence from authority to mutate. |
| P2 | The prerequisites presented one signed-in provider as sufficient, while Build/Compare require independent review from a provider that did not implement the candidate. Authentication discovery also cannot establish remaining quota. | README and pilot prerequisites corrected. Live provider availability remains an acceptance dependency. |
| P2 | Pilot reports treated any decision, including decline, as approval latency and defaulted unrecorded runtime to zero. | Integration owner corrected semantics and added regression tests: only approval records latency; missing runtime is `null`; a recorded zero remains zero. |
| P2 | Raw activity counts and selected-worker reports could be read as a productivity comparison, despite manual single-agent reports and incomplete provider costs. | Measurement protocol now states sampling, timing, baseline, intervention and cost limits. No inferred savings claim is made. |

## Remaining acceptance gates

| Severity | Gate | Evidence needed to clear it |
| --- | --- | --- |
| P0 release gate | No configured staging GitHub App or designated real test repository was supplied for this acceptance run. Mock publication does not establish live token permissions, webhook routing or remote reconciliation. | Owner-authorized App setup on staging; a real draft PR containing the exact approved tree; fresh CI/reviews; same-PR revision; interrupted publication, removed installation, expired token, base drift and external head refusal checks. |
| P0 release gate | Genuine two-account staging onboarding and permission/revocation checks remain distinct from local fixtures. | Personal isolation, explicit team worker pairing, project grant refusal, invitation expiry, separate-human approval, removed-member/worker/project-policy revocation, sessions/events/downloads and publication verified against the staged source head. |
| P1 release gate | Native provider acceptance has failed before producing a candidate because independent providers reported quota or balance exhaustion. | Available independent-provider budget; a successful live task, explicit correction, fresh final checks/review and separate human approval/delivery. Preserve failed attempts as outcomes. The latest Claude diagnostic reports a weekly limit resetting October 11 at 8 a.m. America/Detroit; recheck availability live rather than assuming the reset makes execution usable. |
| P1 release gate | The current full-flow repository example is a disposable local fixture with simulated GitHub delivery. | A shareable, authorized real repository example showing initial patch, correction, fresh evidence, recorded approval and real draft PR, with provider/model/settings and failures reported accurately. |
| P1 release gate | Retention, deletion, backup/restoration and support text describes responsibilities that source tests cannot establish for the deployed operator. | Confirm operator contacts and response expectations, actual storage/backup policies, account/team deletion procedure and a restoration exercise before enrolling users. |
| P1 release gate | Paid enrollment and commercial terms are a manual process, not an implemented billing workflow. | Participant-specific agreed price, scope, evaluation period, provider-charge responsibility, support and cancellation/refund terms before payment or enrollment. |
| P2 measurement | Automatic engine runtime, approval waiting and manual single-agent duration are different measures. Comments/revisions/steering are activity counts, not all human work. | Paired attempts on the same baseline and checks with consistent manual timing/intervention definitions, all failures and revisions included, unknown provider cost retained and individual outcomes shown. |

## Acceptance walkthroughs

Use separate accounts, disposable project clones and the designated test repository. Capture the staged source head and the request/operation IDs so the operator can reproduce recovery without clearing journals.

1. **Individual:** finish project/provider readiness, delegate a small change, inspect evidence, request a saved-candidate correction, approve, verify no developer-file application happened at approval, then explicitly apply and confirm unrelated staged/unstaged files remain preserved.
2. **Team:** pair a worker explicitly into a new team, bind only approved paths, invite a second person by copyable link, assign review and open **Awaiting your review** as that person. Confirm the requester and Owner cannot self-approve and a Reviewer cannot start/apply/publish. Approve as the authorized peer and deliver as a Developer.
3. **Correction failure:** force an independent-provider failure during a revision, inspect its recorded error and consumed budget, stop it, then retry the saved parent. Also revise a completed revision again to check a second-generation lineage rather than only the first child.
4. **Publication:** select GitHub delivery before delegation, verify baseline match, approve, inspect repository/base/branch/title/description, and explicitly publish. Interrupt at a durable boundary, reload and retry the recorded operation as its original actor. Confirm the same draft PR and exact approved tree, without unrelated local changes or force push.
5. **Drift and revocation:** edit the original project before revision, change remote base/head before publication, revoke membership/project/worker access while a command is queued, and remove the installation during recovery. Each case must refuse its consequential action and retain inspectable evidence for still-authorized users.
6. **Feedback and recovery:** refresh CI/reviews, add one finding to an explicit correction request and confirm no automatic agent launch. Repeat reviewer handoff, reload and recovery at desktop and mobile sizes, including worker offline and missing quota.

The launch checklist in [PILOT.md](PILOT.md#launch-checklist) remains the release authority. Detailed deterministic and live-attempt evidence belongs in [PILOT-IMPLEMENTATION.md](PILOT-IMPLEMENTATION.md); this audit does not replace those checks.
