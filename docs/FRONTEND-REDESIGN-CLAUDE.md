# Parallax frontend redesign: the evidence ledger

October 12, 2026. Branch `claude/frontend-redesign`, based on `af7cc74`. This replaces the rejected Perspective identity (pale blue surfaces, Archivo, offset-plane mark). Earlier documents that say to retain that identity are superseded. Nothing here has been pushed, published or deployed, and no customer has reviewed it yet.

## Direction

The interface answers five questions in order: what am I working on, what is happening, what changed, what needs me, and what happens if I click. One idea carries the identity: every claim about a change is a separate recorded fact. The task view shows those facts as an **evidence ledger**, a vertical list beside the diff: baseline checks, changes, independent review, final checks, human decision, local delivery and GitHub delivery. Each fact has one state.

| Dot | Meaning |
| --- | --- |
| Filled green | Recorded and passing |
| Filled red | Recorded and failing |
| Filled amber | Needs attention (unavailable, advisory, failing baseline) |
| Indigo ring | Waiting on a person |
| Hollow | Not recorded yet |

Two Studio compositions were compared on a private concept canvas before implementation: a desk with the ledger in a right rail (chosen) and an attention queue with a pinned decision bar. The chosen build borrows the queue's grouped task list and the pinned decision on phones. The homepage, the blocked state and mobile were drawn with the same illustrative task.

## Design system

`studio/src/system.css` owns fonts, tokens and base elements. Legacy variable names (`--accent`, `--text`, `--muted` and so on) are mapped onto the new tokens so older advanced views stay coherent.

- **Type.** Instrument Sans for interface and display, JetBrains Mono for code, paths and digests only. Both are bundled (SIL OFL 1.1, notices in `assets/fonts/FONT-LICENSES.txt`). Programming ligatures are disabled so diffs show exactly what was recorded. Text has a 12px floor.
- **Color.** Near-monochrome: white paper, cool neutral canvas, graphite ink. Primary actions are ink pills. One indigo signal marks work that needs a person. Green, red and amber are reserved for evidence. Light and dark themes are both supported.
- **Shape.** Pill buttons at 40px (44px for primary page actions), 8 to 16px radii by hierarchy, hairline borders, a single soft shadow for raised layers.
- **No template chrome.** All-caps eyebrows, wide tracking and left-border callout cards were removed across the app.

## What changed

| Area | Result |
| --- | --- |
| Public website (`PublicEntry.tsx`, `site.css`) | Left-aligned editorial page. Hero shows an illustrative task whose ledger switches between a blocked candidate 1 and a ready candidate 2, labeled as not from a recorded run. Six-step "how it works", fit, solo and team use, install tabs with platform availability, data boundaries, questions. Preview-only features are qualified beside the install choice instead of in the hero. |
| Studio shell (`App.tsx`, `shell.css`) | Labeled sidebar: workspace switcher and account at the top; Tasks, Review inbox, Repositories, Settings; Advanced tools collapsed; machine, project and agent readiness at the bottom. The seven-item top bar became a slim breadcrumb that only adds a status when the runtime is unreachable. Below 860px the sidebar is a focus-managed drawer. |
| Task view (`TaskWorkspace.tsx`, `task.css`) | Header with project, status, title and byline; one decision bar; the ledger in a sticky right rail that reflows above the diff through a container query; Changes, Checks, Reviews and Details tabs with Activity as a toggle; correction and delivery as calm disclosures. Reading order stays decision, evidence, change. |
| Recovery guidance (`task-recovery.ts`) | Stopped tasks read the runtime's existing `/runs/{id}/recovery` classification and say what happened, what was kept, how much budget was used and which existing action applies. Read-only: no new operation, never implies a budget reset, offers resume only when the task can resume, and points viewers without delivery permission to a developer. |
| Reviewer handoff (`review-link.ts`) | A team task awaiting approval offers **Copy review link**. The link is `/studio#review=<workspace>.<machine>.<task>`: three UUIDs, no token, path or source, kept in the hash so servers never log it. Opening it checks the signed-in account's own workspace list; another workspace asks before switching, naming the role; a workspace or machine the person cannot reach gets a uniform unavailable message. After an explicit switch it selects the machine from the current authorized machine list and opens the exact task, including tasks beyond the latest 100. Opening never approves, runs or publishes. Links pasted into an open tab work too. |
| Browser and composer (`workflows.css`) | On-demand task browser that sits beside the task at 1280px and up and takes the surface below it. Focused composer with readiness, task, workflow, team and delivery. |
| Evidence content | Checks, verification record, reviews and run settings restyled as quiet cards. |
| Settings, dialogs, connections | Workspace settings open as a right-hand sheet with inline forms and member rows. Machines and account deletion share `dialogs.css`. Worker platform choice is a segmented control. Connections drawer rewritten in `connections.css`. The account menu now names team workspaces correctly instead of calling them personal. |
| Performance | The agent graph and its libraries load only when an advanced view opens. The local App chunk went from 258 kB to 230 kB, inside the 256 KiB packaging limit. |

Removed: `WorkflowPreview.tsx`, `workflow-preview.css`, `perspective.css`, the Archivo and Plex Mono files, the Studio footer slogan, and the legacy shell, button and evidence rules they depended on.

## Contracts preserved

No backend file changed. Request routing (`api()` versus `relayApi()`), executor scoping, stale-response guards, request IDs, expected digests, role checks and the separation of approval, local application and publication are untouched. Labels the tests rely on are preserved. One existing assertion changed on purpose: the primary navigation order (Review inbox now follows Tasks). Studio's isolation key stays `scope:machine`; it gains a suffix only after a review link opens, to force a fresh mount.

## Verification

At the head of `claude/frontend-redesign`:

- `npm --prefix studio test`: all 17 suites pass, including the new `studio_task_recovery.cjs` (6 checks) and `studio_review_link.cjs` (7 checks).
- `npm --prefix studio run test:hosted`: passes.
- TypeScript, local, hosted and cloud builds succeed. Packaged assets in `src/parallax/static` are rebuilt.
- `scripts/validate_release.py` passes. `scripts/build_claude_plugin.py --check` passes.
- Python `test_release`, `test_deployment`, `test_desktop_runtime` and `test_pilot_fixture_support` pass.
- Browser inspection on a fresh fixture with frozen cloud assets (port 8847): website, owner and reviewer task, checks, reviews, task browser, composer, repositories, settings, machines, workspace sheet, 390px task and navigation, dark theme, keyboard focus. Screenshots are in `output/redesign/claude/` (ignored). The recovery screenshot uses intercepted responses to show a stopped state; nothing was written.
- Review link, end to end on a fresh fixture (port 8850): the reviewer copied the link, moved to their personal workspace, opened the link, saw the switch prompt, switched once and landed on the exact task. Forged workspace and machine identifiers showed the unavailable states. The only writes were the two workspace switches.
- Delivery, end to end on a fresh fixture (port 8851) with simulated GitHub: the reviewer approved, the owner saw Apply locally and the GitHub delivery panel, opened the publication preview (repository, base, branch, title, body), published a draft PR, and the ledger showed GitHub delivery as published. Writes: one approval, one preview, one publication.
- axe-core 4.10 (WCAG 2.0, 2.1 and 2.2 A/AA rules) reports zero violations on the website, task, checks, reviews, details, activity, task browser, composer, repositories, settings, machines dialog, workspace sheet, and the 390px task and website, in light and dark themes. Fixes made to get there: line numbers and small labels moved to a darker gray, and scrollable code and data blocks became keyboard-focusable. Automated rules cover only part of WCAG; this is not a conformance claim.
- Sign-in, sign-up and password reset were inspected in their enabled state by intercepting `/api/auth/config`. No marketing opt-in appears anywhere.
- Local mode was inspected on a disposable server (`PARALLAX_HOME` under `/private/tmp`) against a copy of the fixture project, with consequential requests blocked.

The fixture uses deterministic providers and simulated GitHub. None of this proves live provider, account, GitHub, platform or customer acceptance.

## Remaining work

- **Reviewer handoff, server preview.** The link works without backend changes because every read already goes through the relay's current authorization. It does not implement the proposed `/api/workspaces/{id}/review-target/...` preview from `output/redesign/round8/backend-plan.md`, so the task title is not shown before the person switches workspace, and a team worker without `workflow-v2` shows the existing update message after entry rather than a refusal before it.
- **Advanced views.** The run workspace, agent graph and advanced run composer inherit the tokens and readability fixes but keep their older layouts. `style.css` (about 3,100 lines) and `workspace.css` (about 1,300 lines) still hold those rules.
- **Real sign-in.** The enabled forms were seen with a mocked configuration only; no real Supabase, email or OAuth round trip was exercised.
- **People.** No usability study, manual accessibility audit (screen readers, zoom, voice control) or conversion test has been done.
- **Release gates.** Everything listed in `docs/PILOT.md` and `docs/STAGING-ACCEPTANCE.md` remains open.
