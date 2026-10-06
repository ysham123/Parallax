# Graph-first Studio validation

Validated locally on macOS on 2026-10-06. This UI update retains the unpublished 1.1 developer-alpha version and the codex-claude-team installation identity.

The workspace was checked using the recorded native four-provider build 90063c6e-8e4d-4d1d-a1ef-281ce071d3d4: Codex coordination, Claude implementation of the Python API, Antigravity web implementation and three Grok reviews. Both task assignments, reported model/effort settings, the two changed files, four passing final checks and two failed baseline checks came from the existing run record. No inference or new implementation run was started for UI QA.

Checked browser flows:

- Workspace is the initial view. Agent graph renders recorded dispatch/review relationships on first load and after event replay; inspection retains its pan/zoom state.
- Agent selection opens requested/effective settings, actual task ownership, public activity and provider sessions. Assignment navigation opens the original task brief and acceptance criteria. Changes opens the combined diff.
- Task graph exposes independent and combined reviews and candidate checks. List exposes the same inspector without requiring graph interaction.
- Check inspection retains the actual final output and baseline failures. Review presents compact evidence disclosures before findings, changes, checks and settings.
- Project filters, run search and status filters work. A linked project with no history opens an empty workspace instead of selecting another project's run.
- Desktop (1440), narrow (860) and Codex-panel (460) layouts were inspected. Narrow history and inspectors contain focus, Escape closes them, and nested assignment inspection restores the external trigger. Resizing an open inspector moves focus into the modal. Alt navigation is blocked while a modal is open.
- Dark/light presentation, graph zoom/fit and New run configuration/readiness were checked. Reduced-motion control remains available and the system preference is respected.

Production TypeScript/Vite build passes. npm test passes 59 portable assertions for connection identity, ambiguous ownership, task activity, observed process start/finish/resume boundaries, inactive/error states, selection scope, public tool summaries and exclusion of private thinking. The CI Studio job now runs these tests after building. Ten server/release regressions pass. Synchronized manifest, lock, launcher and compiled-asset validation passes.

This does not establish shared-account collaboration, remote worker support, paid live API coverage or remote CI execution. Existing runtime/native delivery evidence is retained separately in this directory.
