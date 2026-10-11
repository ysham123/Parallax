# Product improvements for the development preview

Parallax's public entry remains the website and local tools. Studio is the task and review workspace. This change addresses the install, first-task and reviewer handoff friction identified in the product audits. It does not open the paid pilot.

## Installation and first task

The website and hosted Studio launcher share the public release version and Claude plugin commands. Source clone and ZIP instructions identify the same public 1.3.0 revision. The new workflow is explicitly a separate 1.4.0 development preview; an operator must supply its versioned source archive and digest. There is no native installer or public preview download yet.

[FIRST-TASK.md](FIRST-TASK.md) describes the supplied preview, local setup, provider quota and charges, a disposable repository, inspection, correction, approval and separate delivery. The bundled `examples/first-change` exercise deliberately starts with a failing empty-input test. It verifies setup and check execution, not productivity value.

## Task setup

Instructions and checks can be changed for one task without saving a reusable recipe. Strict versioned settings are captured with the task and participate in request idempotency. Current-project followups inherit the parent's effective settings unless explicitly changed; saved-candidate revisions preserve them and the original baseline.

Paired workers advertise support for task settings. The relay keeps durable, machine-scoped requirements for accepted tasks and unanswered starts. Worker downgrade, cache pruning, relay restart and queue expiry cannot silently remove those requirements. Definitive refusals clear their provisional request record; an ambiguous failure remains protected until reconciled. Cancellation stays available. Revocation removes the worker's records.

Readiness uses the actual edited checks and current provider settings. Known current blockers and invalid command arguments stop Start. Delivery is selected before execution. Execution time is explained separately from provider charges.

## Human review

The task header names the requester, assigned reviewer and recorded human decision with its time. Comments show their recorded author and time. Names come from the authenticated workspace directory; missing legacy attribution remains explicitly unrecorded. Team approval still requires another human.

Reviews show findings as readable cards with optional file locations and selection for an explicit correction. Locations resolve only to files already in the saved candidate diff. Navigation opens the relevant page and highlights the line. Missing, binary, renamed, deleted and out-of-hunk locations have explicit fallbacks. Raw provider data remains available for inspection. New independent reviews can return structured locations; saved plain-text findings remain supported.

## Acceptance boundaries

Automated checks cover the authenticated task-setting contract, downgrade and interruption handling, lineage, reviewer attribution, UI handlers, finding navigation and publication guards. Browser checks use disposable repositories, deterministic providers and simulated GitHub. They verify interaction and real local check execution, not live provider quality or remote delivery.

Before pilot enrollment, complete the live gates in [PILOT.md](PILOT.md) and [STAGING-ACCEPTANCE.md](STAGING-ACCEPTANCE.md): clean onboarding, real provider execution, two-account authorization and revocation, configured GitHub App publication and recovery, and supported platform execution. Pricing, repeat use and measured customer value remain pilot questions. No productivity claim is established by these changes.
