# Dependency-ordered review changes

The local implementation is supplied as four sequential binary patches against `a83e8569b6547099035ac93ddb81ed51d55188e7`. They are review artifacts, not published commits or releases. The original dirty developer checkout remains untouched.

| Order | Patch | Scope and validation |
| --- | --- | --- |
| 1 | `01-revision.patch` | Immutable saved-candidate revision, original baseline, actor/operation contracts, recovery and the command-isolation foundation. 48 final tests passed: 41 workflow/lineage/data and seven private-path canaries. Future peer-approval fields remain dormant; unsupported GitHub targets are refused. |
| 2 | `02-team-authorization.patch` | Membership, invitations, project policies, paired workers and authenticated dispatch. 91 account/Supabase/executor/team/authorization tests passed before the late isolation change; seven final private-path checks passed at this boundary. |
| 3 | `03-github-delivery.patch` | GitHub App bindings, approved-tree draft publication, retry/reconciliation, signed webhooks and feedback. 76 focused transport/workflow/recovery/dispatch tests passed with simulated GitHub before the isolation change; nine final private-path/App-key checks passed. |
| 4 | `04-product-instrumentation.patch` | Complete Studio controls, website/install path, measurements, product/recovery documentation and final packaged assets. Fifteen final metrics/preflight/restore/fixture tests, 35 frontend handler checks, builds and installed-package smoke passed. Earlier patches are backend milestones; the complete interface arrives here because revision, team and publication controls share components. |

The portable subset is under `output/review-boundaries/` in the implementation checkout. Its README records apply commands, source manifests, per-stage checks, final patch replay and artifact hashes. The complete disposable reconstruction is in `review-artifacts/` under the sibling `Parallax-review-boundaries-20261010` checkout. Neither directory is a public download.

Review and apply the patches in order on an isolated checkout of the recorded base. For each patch, run `git apply --check --index <patch>` before `git apply --index <patch>`. Keep the stage-specific checks and final source manifest with the review. Applying a patch is not a commit, push, deployment or pilot authorization.

The complete implementation's current runtime, browser, package and container evidence is recorded in [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md). The review boundaries do not establish a successful live provider task, actual staging account isolation/revocation, real GitHub App/PR/webhook acceptance, or compatible Linux execution. The pilot remains closed pending those gates and manual participant terms.
