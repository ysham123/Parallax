# Installation and acceptance continuation

October 10, 2026. Work ran in the isolated pilot checkout and disposable directories. The original developer checkout, provider settings, installed plugin configuration, production and GitHub repositories were not changed.

## Installation checks completed

| Check | Evidence and limit |
| --- | --- |
| Actual Python distribution | `uv build --offline` built the wheel and source distribution. Both contain the new team, authority, GitHub and pilot modules and packaged Studio. These are unpublished review artifacts, still version 1.4.0. |
| Private-file exclusion | A curated disposable source contained eight public dummy files shaped like credentials/runtime state: auth and credentials JSON, private key/PEM, worker connection, SQLite, provider configuration and API session. Neither built archive contains their public canary content. The wheel digest matched the build without canaries. This is Python packaging evidence, not Docker image evidence. |
| Fresh installed wheel | A new Python 3.13 virtual environment installed all 49 pinned dependencies with required artifact hashes, then the local wheel. The real installed command returned its version and worker help, initialized stdio MCP and listed 24 tools, started a disposable loopback server, initialized built-in recipes, served every referenced bundled JS/CSS asset, and wrote a mode-0600 descriptor. No provider was invoked; the server was terminated and its temporary state removed. |
| Real Claude plugin launcher | A 107-file generated plugin passed its existing directory checks. Its real launcher bootstrapped a new private runtime from hash-locked binary dependencies and returned the version. A second launch with `PIP_NO_INDEX=1` reused that prepared runtime without another installation. Only disposable runtime state was used. |
| Current install command syntax | The installed Codex and Claude CLIs accepted the documented marketplace-add and plugin-install/add forms through their help output. No marketplace was added and no user plugin was installed. |

The first offline clean dependency installation found an uncached package. A network-enabled retry installed it from the existing hash-locked requirement; this was not a product failure. The first installed-server attempt could not bind a loopback socket inside the outer tool sandbox. The permitted native process retry passed. A mistaken acceptance-test recipe URL was corrected to `/api/workflow-templates` before the passing run.

Logs and archives are in `/private/tmp/parallax-qa-packaging-20261010`, including `packaging-checks.json`, `fresh-installed-smoke.log`, `plugin-launcher-first-start.log` and `plugin-launcher-cached.log`. The initial final rebuild in its `final` subdirectory included the new public routing, website and workflow preview source and passed the installed server/asset smoke. The integration browser check then found a 36px approval target because a later-loaded workflow stylesheet overrode the mobile rule. That stylesheet now enforces 44px mobile consequential targets; the corresponding artifact snapshot is preserved in `final-mobile-correction`.

Expanded CI/review feedback also compressed desktop task panels enough to overlap the follow-up controls. Publication-bearing desktop tasks now scroll and keep a 380px panel minimum. The integration owner's rendered check measured the follow-up bottom at 582px and delivery top at 594px, with no overlap; mobile 44px targets remained intact. That review snapshot is preserved in `final-layout-correction`. The final public-install/private-path correction is in `final-public-sandbox`, with bundled `index-BpkAJL-B.js` and `index-eIYF01vZ.css`. Both archives match every Python/static file in the selected source snapshot, and the real installed CLI/MCP/server asset smoke passed again. Digests are recorded beside those artifacts. These are still unpublished review snapshots, not a signed desktop installer or a published release. Rendered verification belongs to the integration browser evidence.

Two additional frontend handler checks exercise actual components with controlled responses: the public root renders immediately without private session or executor requests, and failed/timed-out optional authentication configuration preserves the installation view. The complete handler harness now has 35 passing checks. This does not replace rendered browser acceptance.

## Safer reproducible browser fixture

The fixture now uses a home-relative named disposable directory, optional `--root`, `--port` and independent `--state-name`, and an absolute Studio build location. It snapshots that build at startup so a separate local build cannot replace the active fixture's routes/assets. It refuses unowned preexisting projects and project symlinks. Static requests cannot escape the build root. It binds only to loopback.

`/demo-session/owner` and `/demo-session/reviewer` establish only fake accounts and enter `/studio`; `/demo-session/public` clears that test cookie and opens the public website. A fake GitHub simulator records distinct commit identities and their original trees, updates the same draft PR for a correction, and refuses an unexpected head. The previous constant fake commit identity could not faithfully test published revisions.

Four focused fixture regressions pass: configurable owned state, developer-project/symlink refusal, static-file containment, and exact-tree/same-PR simulated revisions. These validate the acceptance harness, not a real GitHub App. See `tests/test_pilot_fixture_support.py` and `tests/pilot_fixture_support.py`.

```sh
PYTHONPATH=src:tests .venv/bin/python -m unittest test_pilot_fixture_support -v
PYTHONPATH=src:tests .venv/bin/python tests/pilot_browser_fixture.py --port 8766 --state-name acceptance
.venv/bin/python tests/installed_package_acceptance.py --cli /path/to/disposable-venv/bin/parallax
```

The installed-package script checks an already prepared local wheel environment. It does not install dependencies, use ordinary user state or invoke providers.

## Dependency-ordered review artifacts

Four sequential binary patches are prepared against the recorded base. Initial boundary checks passed: 41 revision/lineage/recovery tests, 91 account/team/dispatch tests and 76 GitHub/workflow/recovery tests. After the isolation correction, stage 1 passed all 48 workflow/private-path tests; stages 2 and 3 passed seven and nine private-path/App-key checks, respectively. Final stage 4 passed 15 metrics/preflight/restore/fixture tests, all 35 frontend handler checks, both deployment builds and installed-package smoke. Earlier-stage hosted helpers and TypeScript checks also passed. Patch replay reproduced the frozen source files and modes; final manifests identify the selected artifact snapshot. See [review boundaries](REVIEW-BOUNDARIES.md) and the portable bundle README for validation logs and replay identity. The working tree remains uncommitted and unpublished. Stages 1–3 are backend milestones; the complete shared Studio controls and packaged assets arrive in stage 4.

| Dependency order | Review focus | Coupled integration surfaces |
| --- | --- | --- |
| Candidate revision | Original baseline, managed candidate seeding, immutable lineage, fresh evidence/digest/budget and safe retry | Engine, workspace manager, candidate/workflow contracts and task controls |
| Team authorization | Membership/project grants, session revocation, separate-human approval and durable first dispatch | Account/team policy, relay/worker trusted context, pending request journals and role controls |
| GitHub delivery | App authorization, scoped tokens, exact candidate publication, expected remote heads and reconciliation | Team/project bindings, workflow delivery journals, relay publication and Studio preview/recovery |
| Product and instrumentation | Public installation path, local Studio, optional connected workspaces, privacy and truthful measurements | Public/Studio routing, sign-in callbacks, onboarding, packaged assets and deployment builds |

Keep the final source head, package version, archive digests and deployed artifact identity together. A link to the existing repository or latest public release does not deliver these local changes. Do not label an unmerged source archive as a newly released standalone application.

The parent continuation completed rendered desktop/mobile fixture flows and real Docker image exclusions/persistence/cold restore; see [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md). The remaining live gates stay open: compatible Linux execution/CI, a successful independent-provider task and correction, two-account staging authorization/revocation, real App publication and same-PR update, webhook/CI recovery, and actual staging backup/restore. Before release, repeat artifact identity checks against the selected committed source if it changes from these snapshots. None of the installation checks clears provider quota, real credentials or paid-pilot acceptance.
