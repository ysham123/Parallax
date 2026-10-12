# Parallax: repository workflow and product experience

October 11, 2026. This follows the researched frontend work and the user's request to reassess the complete experience against polished AI products. The current Perspective identity is a working implementation, not a user-approved final design. Recommendations below are hypotheses to test; they do not establish market demand, superiority or live launch readiness.

## Product position

**Delegate a change. Get back a reviewed patch.** Parallax should coordinate supported coding agents the developer already uses, then make the resulting change, evidence, human decision and delivery understandable. Its first customer hypothesis is an individual or small engineering team with an existing Git repository and meaningful executable checks. Bounded bug fixes, refactors and compatibility-preserving migrations are appropriate first tasks.

A general agent dashboard is a crowded position. [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) supplies stateful orchestration and persistence; Parallax already uses it internally. [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) supplies a harness with subagents, filesystem/context tools and human intervention. [LangSmith Studio](https://docs.langchain.com/langsmith/studio) provides agent debugging, graph/chat views and experiments. [Fleet](https://www.langchain.com/langsmith/fleet) is a finished workspace with integrations, permissions and an approval inbox, while [dcode](https://www.langchain.com/dcode) is a configurable coding harness. LangChain is both infrastructure supplier and product competitor.

The proposed reason to choose Parallax is completing this repository workflow without building its isolation, artifact binding, role authorization, revision and delivery recovery yourself. Native-agent compatibility and honest acceptance evidence can make that useful, but competitors can implement similar policies. Prove value through repeat tasks, fewer integration failures and less active supervision. Do not claim unique multi-agent architecture, guaranteed correctness or established productivity gains.

Keep LangGraph internal. `Workflows._ensure_graph` owns prepare/approval/checkpoint boundaries; the existing engine owns provider execution, checks, isolation and budgets. Do not make LangSmith/Fleet an additional mandatory account or silently upload traces. An optional integration needs a concrete customer need, explicit data permission and verified adapter behavior.

## Design priorities

1. Put the current task and code change ahead of the number of agents. A contributor needs to know what changed and what to do next. Agent identity, activity and graph inspection explain the execution behind it.
2. Show one next action, with the relevant destination and current scope. Avoid showing every infrastructure control in the permanent header.
3. Preserve depth through named details and evidence tabs. Current failures, unknown scope and unavailable evidence stay visible; IDs and raw traces can be secondary.
4. Give setup its own focused path. Pairing a machine is an intermediate milestone, not verified provider quota, passed checks or an accepted task.
5. Make human roles visible. A Reviewer should reach permitted review work without installing agents or pairing a personal machine.

The research uses reference patterns, not copied branding. OpenAI and LangChain examples are useful for clear task focus, progressive controls and the transition from conversation to inspectable work. Their visual polish does not establish which layout causes commercial success. Compare compositions, inspect real screens and observe representative users before treating a preferred design as validated.

## Information architecture

Public website: product/workflow example, installation and compatibility, documentation, and visible account entry. Installation remains the primary entry. Accounts enable hosted/team use; local tools retain their account-free path. Newsletters, pricing and billing remain separate work.

Studio: **Tasks, Repositories, Review inbox, Settings.** Keep workspace and role identifiable. Name the selected project and execution machine where they affect the task. Place worker management, connections, members and recipes in settings or contextual setup, with graph/log inspection inside the task's advanced view.

Compare two working compositions before another broad visual rebuild:

- **Project change desk:** choose a repository, view its readiness and start a bounded task. On selection, the candidate occupies the main canvas; task selection collapses instead of adding another permanent column.
- **Attention desk:** show a scoped queue of running work and human actions, then open one task for full-width inspection. This favors team triage. Do not imply a workspace-wide inbox before the backend supports authorized aggregation across machines.

Both share the existing original type, palette and offset-plane identity. The comparison concerns navigation and attention, not another color exercise. On mobile, use a compact scope header, task chooser and one work surface. Evidence should require as little scrolling as practical without hiding a failed gate or a consequential destination.

## Zero to first useful change

| Stage | User decision and real behavior | Required distinction |
| --- | --- | --- |
| Obtain software | Choose the actual compatible release and installation route. | Public 1.3 local tools, supplied 1.4 preview and unpublished Mac app are distinct. A documentation link is not a working preview download. |
| Choose execution | Open local Studio, or expressly pair a user-owned machine into a hosted workspace. | An account does not provide compute or silently share an existing personal computer. |
| Choose project | Use an existing machine-approved Git folder; teams grant project membership separately. | A project folder is not GitHub authorization. Add repository currently manages access; it does not clone. |
| Inspect setup | Observe supported provider connections and configure real project checks. | Assessment does not run checks, establish credit/quota or prove inference. Credentials stay on the machine. |
| Delegate | Describe a bounded outcome, acceptance criteria and explicit execution budget. | Start is deliberate. Setup navigation does not execute agents. One-off settings need not become a saved recipe. |
| Inspect | Read the actual diff, baseline/final checks, fresh independent review and uncertainty. | Reviewed, checked, approved, locally applied and published are different facts. |
| Correct | Request a saved-candidate revision or a fresh task from the current project. | Saved revision preserves the original baseline and receives new evidence/approval; changed project state blocks it. |
| Decide | Personal self-approval or team approval by another permitted human. | Owners cannot bypass team peer approval. Reviewer assignment and current project permission matter. |
| Deliver | Explicit local application or a previewed draft PR publication. | Only the approved candidate is delivered. No automatic merge, force-push, rebase or deployment. |
| Follow up | Inspect CI/review feedback and explicitly request further work. | Feedback never starts agents automatically. Recovery reconciles durable operations and preserves consumed budget. |

The first implementation slice improves the existing pre-pairing instructions and machine connection entry. It adds explicit platform choice and progressive setup while retaining current roles, commands, privacy and reconnect behavior. Post-pair project/provider/check guidance must lead into existing authoritative assessment and composer controls. It must not invent a green completed-setup record.

## Platform and connection policy

| Experience | Current boundary | Product direction |
| --- | --- | --- |
| macOS | Source/plugin local tools; preview worker. Apple Silicon macOS 15+ desktop beta is prepared but not an official verified download. | Complete usable signing/notarization and exact-artifact fresh-Mac/live acceptance before publishing a native download. |
| Linux | Source/worker requires working bubblewrap, namespaces and the project/provider toolchain. Full live task acceptance remains separate. | Offer clear source instructions and capability diagnostics. Do not imply a native installer exists. |
| Native Windows | Worker/installer unavailable. | Display availability clearly. Browser access to an expressly paired supported machine is separate from Windows execution support. |
| WSL2 | Experimental Linux-side capability route; complete Windows/WSL2 task remains unverified. | Link the experimental guide. Do not present it as an ordinary supported Windows download. |
| GitHub | App authorization binds selected installation/repository/base to an existing approved project. | Keep sign-in, cloning and delivery permission distinct. A future clone flow requires worker-side authorization and implementation. |

GitHub delivery requires the captured baseline tree to match the selected remote base before execution and publication. Dirty-tree work can remain local. Publication uses a dedicated branch and draft PR; externally changed heads block updates. These are meaningful product constraints that belong near the relevant choice, with details available for diagnosis.

## Personal and team journeys

Solo local use needs no Parallax account or GitHub App. A hosted solo user pairs a selected machine and owns its provider setup. A team Owner creates membership, copies invitation links, pairs a team machine and grants project access. A Developer starts/revises work and asks another human to approve. A Reviewer opens permitted evidence, comments and approves; installation and delivery controls are unnecessary for that role.

Revocation, an offline worker, unavailable evidence or changed project state invalidate pending actions. Dispatched work remains recorded with its actor. Never infer permission from cached setup progress or switch silently to another machine. Reconnect uses the original worker state and approved paths.

## Growth without unsupported scale claims

Design tasks, queues and filters so the interface remains understandable as history grows. Current source allows three active workflows per worker; run workers default to three and cap at eight, and listing returns at most 100 workflows. Hundreds or thousands of agents are not an established capacity. Scheduling, fair resource admission, pagination, backpressure and load/recovery evidence are separate engineering work.

## Validation and release order

Validate each slice with real browser inspection, keyboard/focus, mobile reflow, current permission failures and existing functional contracts. A synthetic fixture can validate an interface transition but not real provider or GitHub readiness. Preserve evidence when a browser interaction is unexplained; record deliberate writes and guard inspection against consequential requests.

Next, observe individuals and Developer/Reviewer pairs completing first setup, a correction, approval and delivery. Measure wrong turns, help, time to first useful candidate, active human effort and repeat use. Compare representative tasks with ordinary single-agent and fresh-reviewer workflows at matched criteria/budgets. Count failures and unknown usage honestly.

The invited paid pilot remains closed until staging authentication, live providers, genuine role/account checks, GitHub App delivery/recovery, device installation and operator support/privacy/recovery gates pass. A polished design is one part of this release, not evidence those gates are complete.
