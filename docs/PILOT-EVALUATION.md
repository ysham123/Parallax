# Evaluating accepted work

Use this protocol for the invited individual and small-team pilot. It measures a bounded task and its complete delivery history. The public characterization exercise, deterministic provider fixtures and green source tests are setup and reliability evidence; they do not establish customer value or comparative quality.

## Start with a real task contract

Choose one maintainer-owned refactor, bug fix or component upgrade with runnable checks. Record the starting tree, goal, allowed changes, protected acceptance cases, required environments and delivery target before either approach runs. Agree what improvement would be worthwhile and which failure outcomes are unacceptable before observing results.

For setup, use [the settlement parser exercise](../examples/legacy-modernization/README.md). Its unchanged baseline has 34 passing characterization tests and intentionally fails the final modernization guard. It is a synthetic fixture with public tests, not a hidden correctness oracle or a completed agent migration. Keep its protected runner and contract outside the candidate being assessed; invoke the baseline-owned runner against the saved candidate.

## Compare complete attempts

1. Prepare two disposable copies of the same clean baseline. Keep provider credentials outside both copies. Verify tree identity and the unchanged acceptance runner. Workspace fingerprints include more than a Git tree: record their scheme, and never compare hashes from different schemes as if they were interchangeable.
2. Run Parallax and the developer's usual native-agent workflow with the same goal, allowed files, tools, required checks and configured time limit. Include the usual workflow's normal manual review and corrections. Record providers, models, effort, settings and limits; do not assume a subscription supplies a known dollar or token budget.
3. Alternate which approach is tried first across comparable tasks. Record task and execution order. A participant who has seen the other result can learn from it; record that contamination instead of claiming a blinded experiment.
4. Count the entire lineage from the original task through every retry and revision. Retain failed, timed-out, cancelled and quota-blocked attempts. Each runtime revision receives a fresh allocated budget; include every allocation and its consumption under the experiment's agreed total limit. Revisions count toward the original task, rather than repeat use.
5. Assess both final patches against the unchanged contract and checks. Use a human assessor who did not implement the change for an independent assessment, and record the assessment method. A participant's own assessment remains useful but must be described as participant-reported. Agent agreement is not an independent outcome label.

Equal configured time limits establish a time-limit comparison. They do not establish equal total usage or cost. Report those dimensions separately, and use a matched-usage claim only when actual measurements support it.

## Record attention and defects

Record total active human seconds, including setup, supervision/correction and review. Studio records setup and review as portions of that total; do not add them to the total again. Count time spent actually working on the task; exclude waiting while doing unrelated work. Also record elapsed time, execution time, interventions and approval latency. Missing values stay unknown; a recorded zero means the observer measured zero. There is no automatic attention tracker.

Use Pilot measurements in Studio for an explicit comparison record. The server attaches Parallax's saved baseline, contract, configuration and lineage. An external attempt's declared baseline remains participant-reported. `matched` means the reported baseline identity matches the managed one; it does not establish that the other agent actually ran on that tree or that all resources were equivalent. A missing declaration is unverified; a different declaration is a mismatch.

Label a particular recorded check or review with one of: confirmed defect, false alarm, unresolved, or independently observed escape. Keep an unresolved label when there is insufficient evidence. Labels bind to the immutable observation and its digest, including failed observations before a candidate exists. A later revision receives new observations; labels are not silently copied forward. Labels are evaluation annotations and never approve a candidate, waive a check or trigger an agent.

Report confirmed defects, false alarms, unresolved findings and escapes separately. Do not infer recall from the reviewer's own findings: undetected defects require independent assessment. Passing tests support only their recorded scope. Do not infer browser, platform or production behavior from a generic successful command.

## Interpret the report

Pilot exports describe the selected worker and latest 100 authorized workflows, with full retained authorized ancestor effort for each included revision lineage. Missing or inaccessible ancestors make lineage totals incomplete. A later distinct root task is repeat task activity within this report window; it is not proof of voluntary return, retention across all workers or willingness to pay. Ask participants whether they chose to bring the next real task and record that observation separately.

Provider usage is reported only when observed. Unreported subscription usage, partial cost and missing measurements remain unknown. Keep software fees, model charges and compute charges separate. Manual enrollment and commercial terms remain the pilot default.

Exports are explicit and measurements stay in the authorized workspace/worker scope. Do not upload repository content or evaluation data to a cross-customer dataset without a separate agreement. Avoid credentials, prompts, raw command output and absolute workspace paths in portable evidence summaries.

Continue the use case only when participants meet their agreed improvement and failure boundaries and voluntarily return with another real task. Publish numerical claims only with task/repository scope, all failures and comparison limitations. See [the launch checklist](PILOT.md) and [staging acceptance](STAGING-ACCEPTANCE.md); this protocol does not open enrollment.
