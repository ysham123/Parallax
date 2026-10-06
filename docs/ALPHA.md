# Parallax 1.1 developer alpha

This is a prepared local alpha, not a published release or a completed user study. Recruit five macOS developers only after separate authorization. Each participant performs three bounded tasks in a Python service, React/TypeScript app, or mixed repository they understand. Use local CLI connections for the initial study. Optional API connections remain experimental until separately credentialed smoke tests pass.

## Setup and task selection

Start a new Codex chat after installing the alpha. Open Studio, link a Git repository root, inspect project readiness, and save the detected package roots and check commands as a project profile. One implementer plus an independent reviewing provider is enough; the coordinator can review if it did not implement the candidate. Preserve explicit model and effort choices. Choose supported effort from the account catalog.

Use three tasks with written acceptance criteria before either workflow begins:

1. Fix a reproducible bug with failing acceptance tests, including an edge case.
2. Add a small user-facing feature with an existing test harness and a clear file scope.
3. Refactor a bounded module while preserving behavior and all required checks.

Time box each attempt to 45 minutes and retain failure evidence. Avoid tasks requiring deployment, credentials, a live production database, submodules, or unsupported dependency managers. Python setup supports declared PEP 621 dependencies and requirements.txt in a private venv. Node setup supports committed npm lockfiles with lifecycle scripts disabled. Select independent package roots for monorepos. npm workspaces, Yarn and pnpm installation need further adapter work and block preflight. A package requiring installation scripts is unsupported unless checks already have a supported private environment.

## Matched ordinary Codex comparison

Use the same initial effective Git snapshot, requirements, acceptance checks, coordinator model, supported effort, permission scope, and time budget for both attempts. Use fresh sessions without the other attempt's conclusions. The team necessarily has additional independent models; this comparison measures workflow outcomes, elapsed time and intervention burden, not identical inference compute.

Prepare two disposable copies without applying anything to the original project:

```sh
python3 scripts/prepare_alpha.py --project /path/to/project \
  --destination /path/outside/project/participant-1-task-1 \
  --spec /path/to/run-spec.json --participant 1 --task 1
```

The helper privately stores matching snapshot hashes and selected Codex settings. It captures staged, unstaged and nonignored untracked content without changing the real index. It does not start inference. Follow study.json's counterbalanced order. Across five participants and three tasks, each workflow runs first seven or eight times. There are 15 paired tasks and 30 attempts.

Run Parallax with parallax-spec.json against its disposable copy. Run ordinary single-agent Codex in the single-codex copy with the same requirements, model, effort, configured acceptance commands and 45-minute limit. Collect actual diffs, check exit codes, elapsed time, reported usage and manual intervention counts privately. Acceptance decisions come from the same fixed tests and a developer inspecting each result. Do not edit acceptance tests between attempts or let failed baseline tests excuse failed final checks.

## Optional local feedback

After a Parallax attempt finishes, Review's optional feedback form records bounded booleans, numbers and fixed categories locally. Mark setup success on task 1 only. Record the ordinary Codex attempt through the separate baseline option; it does not borrow Parallax's runtime or repair telemetry. Alternatively use:

```sh
python3 scripts/parallax.py feedback --run-id RUN_ID --spec metrics.json
python3 scripts/parallax.py feedback --baseline --spec codex-metrics.json
python3 scripts/parallax.py feedback --export
```

Required metric fields are accepted, setup_unassisted, minutes and task_number (1–3). Optional fields are manual_interventions, comparison (parallax or single_codex), order (first or second), unintended_edits and staging_loss. Baseline records require comparison=single_codex. No free-text fields are accepted. Recording the same Parallax run replaces its metric entry; baseline submissions are separate attempts.

Export includes aggregate counts, elapsed minutes, manual interventions, repair counts and failure categories. It omits prompts, source, keys, run/session IDs, absolute paths, endpoint information and command output. Exporting downloads a local file; nothing is transmitted. Recruitment, publishing and sharing feedback remain separate actions.

## Decision gates

- Zero unintended source edits or staging loss. Reproduce and fix every permission, data-loss and recovery bug before expanding access.
- Target at least 12 of 15 accepted Parallax task outcomes and four of five unassisted first-task setups.
- Compare task acceptance, time, interventions and failure categories against ordinary Codex. Report all failed and timed-out attempts, missing usage, order and setup problems.
- These are iteration gates for five developers, not statistical evidence of general superiority. No human alpha results have been collected in this prepared package.
