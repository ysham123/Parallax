# Parallax frontend redesign: research and first direction

October 11, 2026. Round 1: audit, information architecture and rough layouts. Reviewed source: `6eaeb37`. This is a design study, not a redesigned release. Production frontend code is unchanged.

## The design problem

The user dislikes the current frontend and explicitly requested research before implementation. The website remains the main entry point, with Studio for working on tasks. Online accounts belong in the company/product plan. Updates and newsletters are later work; they are not part of this redesign implementation.

The user clarified that visual identity, layout/navigation and excess information all need improvement. Their chosen direction is a **polished and distinctive developer product**. Cohesion, clear hierarchy and ease of navigation are design requirements; every consequential decision must remain inspectable.

The initial customer hypothesis remains an experienced individual developer or small team using existing coding agents on a repository with meaningful checks. Parallax must make the accepted result and the human work around it understandable. Multi-agent infrastructure does not explain the product by itself.

**Recommended direction:** a distinctive website centered on a reviewed change, paired with a calmer, readable Studio. Give installation and account entry clear paths. Make project connection a primary setup action, then organize daily work around tasks and reviews.

This recommendation comes from the current product audit and reference patterns. It has not been validated with customers. The current research includes direct browser inspection of Parallax, Linear, Raycast and Conductor, source review, and first-party product/documentation research, including Cursor. It includes no customer interviews, conversion experiment or hands-on evaluation of competitors' paid workflows.

## What the audit found

| Observation in the current product | Design implication to test |
| --- | --- |
| The public hero describes an upcoming workflow while its install section supplies older public tools. The hero also contains multiple explanatory caveats and an abstract orbit illustration. | Give the visitor one clear result and an explicit availability/installation surface. Preserve accurate limitations near the relevant action. |
| Studio has an icon-only global rail, a second task sidebar and a separate machine/workspace bar. Many controls and metadata use 11–12px text. | Use labeled desktop navigation, one clear scope bar and more readable working text. Avoid multiple competing navigation systems. |
| At 390×844, the selected published fixture uses several context/navigation rows, followed by task metadata and a tall single-column result summary. The actual diff and delivery work require further scrolling. | Put the selected task and its next action first on mobile. Use a compact result followed by evidence; move the task list into a deliberate chooser. |
| Repository delivery is nested inside Workspace settings, beneath approved-worker/project and membership controls. | Put **Add repository** and **Connect GitHub delivery** in a dedicated project setup flow. Name what each action does. |
| GitHub binding authorizes delivery to a selected repository; it does not clone source onto a worker. | Offer an existing-folder path now. A guided clone/import path is a proposed capability requiring a worker-side implementation and authorization, not a cosmetic button. |
| The current state helpers do not explicitly project `approved`/`published` into the workflow steps, and approved tasks can be grouped as finished before delivery. | Model the next human action explicitly. Approved with delivery pending must remain actionable, without changing backend permissions. |

These are observed layout/source issues and proposed remedies. The synthetic fixture does not measure real developer performance.

## Reference evidence and its limits

| Primary reference | Observed pattern or guidance | Parallax proposal |
| --- | --- | --- |
| [Linear](https://linear.app/) | Public presentation includes product examples, lifecycle sections and identifiable account entry. | Explain the workflow with a readable result. Keep returning users' sign-in/Open Studio path visible. |
| [Raycast](https://www.raycast.com/) and [platform page](https://www.raycast.com/windows) | Acquisition and platform requirements have dedicated places; product tasks are demonstrated. | Show what can actually be installed, its platform and setup requirements. Do not imply unsupported installers exist. |
| [Conductor](https://www.conductor.build/) and [Superset](https://superset.sh/) | Their agent-work propositions lead into acquisition and recognizable workspace examples. | Show why Parallax belongs alongside the user's agents and what the finished change looks like. Use original composition, copy and artwork. |
| [Cursor](https://cursor.com/) and [Agents Window documentation](https://cursor.com/docs/agent/agents-window) | Public examples use recognizable tasks/review states and visible sign-in/download entry. Its workspace documentation connects repository context, agent work and diffs. | Give the visitor a recognizable result and returning users a direct workspace path. Let task progress and evidence share one coherent task surface. |
| [GitHub review documentation](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request) | Review is attached to files, changes, comments and recorded decisions. | Keep findings beside the relevant candidate diff. Model review, human approval and delivery remain distinct. |
| [NN/G progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) and [usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) | Frequent decisions should remain visible; uncommon configuration can be reached through clearly named secondary controls. Status and recognizable language matter. | Show the outcome, evidence and next action first. Put graph internals, raw logs, IDs and rare configuration behind named details. |
| [W3C contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) and [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) | Readability, target size/spacing and reflow have testable requirements. | Target WCAG 2.2 AA. Choose 44px main controls as a design target, beyond the AA minimum/spacing rule. Give code its own scroll area and preserve page reflow. |

Reference patterns do not establish what caused those products to succeed. No competitor's layout, numerical claim, customer logo or testimonial becomes Parallax evidence.

## Proposed structure

Public navigation: **Product · How it works · Install · Docs · Sign in**. Returning signed-in users get **Open Studio**. A future changelog gets its own place once maintained. Do not introduce public subscription pricing or a newsletter form during this work.

Homepage sequence:

1. Clear product promise and supporting explanation, one acquisition action and an inspectable example.
2. One complete change: request, patch, recorded finding, correction, checks and human decision. Label synthetic/simulated evidence.
3. Practical fit: bounded bug fixes, refactors and one-component modernization.
4. Available installation paths and requirements. Current source/plugin 1.3 and supplied preview 1.4 remain distinct; the Mac download stays unavailable until release gates pass.
5. Individual and team use, online accounts, and optional GitHub delivery.
6. Short data-boundary explanation, FAQ, support/privacy/security links.

Studio navigation: **Tasks · Repositories · Review inbox · Settings**. A repository card identifies both its worker-approved local project and any separate remote delivery binding. Keep the selected workspace visible; project and execution machine belong in one scope bar. The agent graph is a task detail. Provider connections, workers, members and saved recipes have named settings rather than a second set of competing main destinations.

Project setup: **choose an existing local project → identify its machine → check providers and project commands → optionally authorize/bind GitHub delivery**. Account sign-in and GitHub repository permission remain separate. Clone/import is a clearly marked future interaction until a worker can perform and approve it.

Task layout: task outcome and next required action → compact current evidence and uncertainty → Changes/Checks/Reviews/History. Show baseline checks separately, retain historical attempts and let findings lead to files. Keep revision feedback near the inspected candidate. Approval and local application/PR publication have separate explicit actions.

Mobile: one compact scope header, a task chooser, then the selected result. Evidence stays ahead of activity logs. Avoid squeezing the desktop's simultaneous sidebars and panels into multiple persistent header rows. Preserve the destination preview before delivery.

## Three directions to compare

**A. Decision desk, recommended.** A graphite product introduction, strong typography, a warm restrained accent and one large original candidate/result composition. Studio uses a quiet light working surface with labeled navigation and readable diffs. The website's identity and Studio's precision share typography, spacing and a simple offset-plane motif. Risk: an attractive invented result could imply proven quality; retain its evidence type and availability label.

**B. Local toolkit.** A light technical/editorial surface with a restrained blue accent. The installation selector and short first-task path lead the page; a reviewed result explains the payoff. Risk: it can look like another agent launcher if the result is secondary. Account access remains visible.

**C. Modernization field notes.** An editorial case-led layout with a compatibility contract, before/after code and correction narrative. Risk: current evidence supports a synthetic exercise, not a completed live migration or whole-system rewrite. Use it as a focused case page rather than narrowing the entire product before demand is observed.

These are compositions and story choices, not merely alternate palettes. The rough review board explores hierarchy; it does not settle final typefaces, artwork, motion or production component styling.

An independent review refined this board: the next human action now appears near the task heading, setup/results are labeled as shared hierarchy rather than falsely implying three fully designed variants, and mobile keeps a menu and named workspace. The board received browser inspection and interaction/reflow checks. It is not a completed task-flow prototype or a customer usability result.

## Contracts the redesign must preserve

Keep account, workspace, project, machine and remote repository distinct. Show progress, evidence applicability/result, human decision, local delivery, GitHub delivery and connectivity as separate facts. A historical pass, an AI review, an approval and a draft PR are different events.

Team requester/Owner self-approval remains refused. Reviewers inspect and approve; they cannot publish or apply. A saved-candidate revision retains the original baseline and fresh budget/evidence/approval. A new task from the current project captures current files. Changed sources and remote heads must remain actionable refusal states.

An offline team worker can block inspection; cached evidence cannot authorize an action. Recovery preserves consumed budget and durable operation IDs. A lost publication response requires reconciliation. Unknown provider cost stays unknown. Privacy copy names local execution, provider processing and optional relay evidence; online accounts do not grant repository access by themselves.

Online identity remains a first-class product capability. Whether a future native download requires an account is a separate distribution decision, not something inferred from newsletter plans. Existing local CLI/plugin behavior remains supported. Future newsletters need an explicit optional preference; an account is not an automatic marketing subscription.

## Iteration and evaluation

1. **This round:** review the audit, proposed structure and rough direction board.
2. **Next round:** develop two original homepage concepts and one coherent Studio result screen. Include the actual available-download state and a blocked/error state.
3. **Prototype round:** connect project setup, task inspection, revision, reviewer handoff and delivery preview. Compare with current screens using representative developers, counterbalancing task order where practical.
4. **Implementation:** build approved slices in order: public shell/homepage, project/account setup, task/review workspace, then supporting settings. Review desktop/mobile after each slice and preserve existing contracts/tests.
5. **Validation:** keyboard/focus, contrast, zoom/reflow, reduced motion, role restrictions, stale evidence, offline/recovery and honest availability. Then run live-provider/account/GitHub acceptance separately.

Use six formative participants if available: two individuals and two Developer/Reviewer pairs. This is a proposed small usability study, not market validation. Ask them to explain the product and current download, connect the right project, inspect baseline/final evidence, recognize stale review, request the right correction, hand off approval and identify the delivery destination. Record completion without help, wrong turns, comprehension, time and participant wording. Treat wrong-project delivery or stale-approval misunderstanding as a failure requiring another iteration.

No customer study has occurred yet. Research-informed directions are ready for feedback; final visual design and implementation remain later stages.
