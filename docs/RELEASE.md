# Draft GitHub release: Parallax 1.1 · Developer alpha

Prepared locally for review. No GitHub release, tag, push, or deployment has been published as part of this update.

Parallax turns an outcome into a reviewed, checked project patch from your Codex conversation. Choose Codex, Claude Code, Grok Build or Antigravity, assign the coordinator and roles, and select models and supported effort. Use existing CLI sign-ins or optional API connections.

Studio opens on a graph-first Workspace, with New run and Review; reusable presets; official provider marks; separate agent and task graphs with assignment inspection, dependencies, evidence and repair history; streaming activity; checkpoint steering; and pause, stop and resume. Dark and light themes, reduced motion, keyboard controls and a responsive layout are included.

Workers use private snapshots of the effective working tree. Independent reviews and actual combined project checks gate integration. Staged work and unrelated edits are preserved, or the run stops with its patch and workspaces available. A downloadable verification record identifies the patch, settings and gate outcomes without exposing prompts or raw provider sessions. It is evidence, not a correctness guarantee.

The repository, Parallax identity and `codex-claude-team` install ID are retained. The original Claude bridge arguments and result fields remain compatible. Users do not need Node to run the packaged Studio.

This update adds project readiness, saved package roots and check profiles, private baseline checks, per-package setup, contextual recovery and opt-in local alpha feedback. See [delivery behavior](DELIVERY.md) and the [matched five-developer alpha protocol](ALPHA.md).

## Validation

- The final 1.1 suite completed 142 cases on Python 3.13 locally, with one Linux-only live case skipped on macOS. Python 3.10 passed the earlier full suite and the final delivery and engine regressions. The real four-provider mixed-project build passed all four unchanged final checks and all five integration gates, and preserved the real index byte for byte. Two baseline test failures are retained.
- Deterministic native/API provider, engine, workspace, compatibility, server, receipt and release tests validated locally on macOS with Python 3.10 and 3.13. See the [validation index](validation/README.md) for exact coverage.
- Sixteen real native CLI cases passed across all four installed providers, including consultation, scoped editing, resume and permission boundaries.
- The representative four-provider build completed with a rejected implementation, repair, independent review and eight passing acceptance tests before application. The actual diff and final verification record are included.
- Desktop and mobile Studio flows, keyboard operation, modal focus behavior, graph inspection and dark/light presentation were checked against real provider metadata and recorded run evidence. Production build and npm audit passed.
- Hashed runtime dependencies, synchronized manifests, prebuilt assets, source archives, wheel, sdist and checksums are supplied. The enabled personal installation was migrated through Codex's installer and checked locally.

## Requirements and limits

macOS is the launch platform. Python 3.10+ and Git 2.38+ are required for implementation runs. The CI workflow targets macOS and Linux, but remote CI has not run for this unpublished branch. Linux sandbox command construction is regression tested; actual Linux execution remains unverified locally because Docker was unavailable. Native capabilities depend on installed CLI versions; diagnostics identify incompatibilities explicitly.

API protocol behavior and tool permissions have deterministic endpoint coverage. Real API inference needs separately configured account credentials and has not been verified on these accounts. Remote inference endpoints are supported; SSH workers, remote filesystems, external MCP tools and hosted agent execution are outside this release. API command execution currently requires the macOS sandbox.

Automatic environment setup supports Python requirements.txt/PEP 621 dependencies and locked npm projects with lifecycle scripts disabled. Yarn, pnpm and npm workspaces setup remains unsupported and blocks preflight. Linux commands require working bubblewrap with user namespaces. Git submodules and symlinks escaping the project require manual handling.

## Upgrade

Follow [UPGRADE.md](../UPGRADE.md), reinstall through your marketplace and start a new Codex chat to load the skill and MCP operations. Version 1.1 keeps the existing installation ID. The GitHub marketplace commands install the current published version until this release is published.

Attach the four archives and `SHA256SUMS` from `releases/` when publishing is separately requested. Use title **Parallax 1.1: Developer alpha** and tag **v1.1.0** only after the branch and release artifacts have been reviewed.
