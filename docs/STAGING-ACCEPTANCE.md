# Proposed staging acceptance setup

This is a prepared setup, not an existing deployment or repository. Use a separate Railway staging environment, a dedicated Vercel staging Studio project with a stable HTTPS origin, and a private `ysham123/parallax-pilot-acceptance` repository containing only disposable code. Keep production credentials, volumes, workers and projects out of this environment.

Railway supports [isolated service environments](https://docs.railway.com/environments). Vercel supports [Preview environments](https://vercel.com/docs/deployments/environments); a separate staging project gives this test a stable origin for cookies, sign-in callbacks and the GitHub App callback. The operator must select and record the actual Studio and relay URLs before configuring credentials.

## Prepare the services

1. Build and deploy the reviewed checkout to a separate Railway staging service with one replica and a new persistent volume at `/data`. Record the source head and image digest. Do not duplicate production volume content or credentials.
2. Build the staging Studio with `PARALLAX_RUNTIME_URL=<HTTPS_RELAY_ORIGIN>`. Set that value only for the staging project/environment.
3. On the relay, use a new random `PARALLAX_ACCESS_TOKEN`, exact `PARALLAX_STUDIO_ORIGINS=<HTTPS_STUDIO_ORIGIN>`, `PARALLAX_PUBLIC_ORIGIN=<HTTPS_STUDIO_ORIGIN>`, and exact `PARALLAX_ALLOWED_HOSTS` containing the Studio and relay hostnames without schemes or ports. Keep the protected project root at `/data/projects` and relay state on the mounted volume.
4. Configure separate staging sign-in credentials using the existing [deployment guide](DEPLOYMENT.md). Keep `PARALLAX_SIGNUP=allowlist` and admit only the two designated test accounts. Both should have normal personal account workspaces; do not give both operator access as a substitute for account isolation.
5. Confirm anonymous protected API denial and cross-account worker isolation before enabling `PARALLAX_PILOT_ENABLED=on` in staging. Production keeps its current feature setting.
6. Pair a disposable worker state directory explicitly into the staging personal/team workspaces. Approve only the test repository clone. Keep the original project and existing paired worker state separate.

## Native Linux execution gate

The default local Docker container has `bubblewrap` installed but cannot create the required namespaces. It refuses Build before recording a run or dispatching providers. Do not make it pass with privileged containers, disabled security profiles or host namespace-setting changes. Docker relay persistence acceptance is separate from coding-worker execution.

The prepared runtime CI matrix uses a normal user on `ubuntu-22.04`, a [currently supported GitHub full-VM runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). After the source is reviewed and pushed through the normal authorized release process, its Linux job installs bubblewrap, requires a live enforceability probe and runs the actual secret-file canaries plus the full suite. This job has not run remotely. Runner selection alone is not proof of namespace compatibility; a failed probe stops acceptance.

On a designated disposable native Linux worker that already supports unprivileged user namespaces, run the same checks from the reviewed checkout. Keep execution under a normal user and install missing packages through that host's usual provisioning. No GitHub App or provider secrets are needed for these synthetic tests:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python - <<'PY'
import os
from parallax.assessment import execution_capability
assert os.geteuid() != 0, "Run acceptance as a normal user"
capability = execution_capability()
print(capability)
assert capability["enforced"], "Stop here; do not weaken host security"
PY
PYTHONPATH=tests .venv/bin/python -m unittest test_isolation_secrets test_github_isolation test_delivery test_connections -v
.venv/bin/python -m unittest discover -s tests -v
```

Record the reviewed source head, Python/Node/bubblewrap versions, actual canary results and the full-suite result. Only then test a live provider on that paired worker. No compatible additional Linux VM or worker is configured in the current local environment.

## GitHub authorization that the owner completes

Create a private test repository with a small failing test and a clean committed baseline. Register a staging GitHub App separate from Parallax sign-in. Use the [pilot App configuration](PILOT.md#github-app-setup): Contents and Pull requests write; Checks, Commit statuses and Actions read; no workflow-file modification. Install it for the selected test repository only.

Use `<HTTPS_STUDIO_ORIGIN>/api/github/connect/callback` for App user authorization and `<HTTPS_RELAY_ORIGIN>/api/github/webhook` for signed webhooks. Configure the six `PARALLAX_GITHUB_APP_*` settings server-side. Mount the private key outside approved projects; it must not enter the repository, Studio environment, image build context, worker payloads or chat. Use a new webhook secret. [GitHub installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) support repository scoping and expire after one hour; Parallax requests a fresh scoped token for each operation.

As the workspace Owner, choose **Authorize GitHub delivery**, complete GitHub authorization, then bind the selected installation/repository to the approved test clone. Account sign-in alone does not authorize delivery.

## Read-only preflight and prepared release commands

The October 10 local check found Railway CLI 5.41.3 and Vercel CLI 58.9.0. This checkout has no linked Railway project or `.vercel/project.json`. A Railway status request also failed to refresh authentication because its network request failed. Existing production links and credentials were not changed. Do not use a bare `railway up`: this CLI can create a project and service when the directory is unlinked.

Record these concrete values before a release:

| Needed | Where it belongs |
| --- | --- |
| Dedicated Railway project/environment/service IDs and a new `/data` volume | Staging only; one runtime and one replica |
| Dedicated Vercel project and stable Studio HTTPS origin | Staging only; root build configuration |
| Relay HTTPS origin | Studio's `PARALLAX_RUNTIME_URL` and relay host allowlist |
| New operator access key, exact origins/hosts, explicit state/project roots | Relay secrets/configuration |
| Separate sign-in provider configuration and two admitted test accounts | Relay; `PARALLAX_SIGNUP=allowlist` |
| All six GitHub App settings and a private RSA key mount | Relay; never Studio variables or source |
| App installation authorized for the disposable repository and a clean clone | Owner completes authorization; worker approves the clone |

The relay image includes a read-only configuration checker. Run it inside the intended staging runtime, with platform-provided configuration already present. It prints check names and static guidance, never values, credentials or key data. The check confirms the key is readable, private and usable for RSA signing, but makes no GitHub request:

```sh
python /app/scripts/staging_preflight.py
# After the delivery App and test accounts are configured:
python /app/scripts/staging_preflight.py --delivery
# After isolation checks pass and the staging pilot gate is enabled:
python /app/scripts/staging_preflight.py --delivery --pilot
```

For a source checkout, use `.venv/bin/python scripts/staging_preflight.py` instead. Missing configuration returns exit code 1. Passing configuration does not prove authentication, installed repository access, provider execution, publication or pilot readiness.

The following commands are prepared examples, not actions executed during the audit. Replace every placeholder with recorded staging identifiers, inspect the selected target, and deploy only the reviewed source. Set secrets using the platform's private configuration interface rather than command-line literals. The Vercel `--prod` flag below applies to the separate staging project so its stable staging domain receives the release:

```sh
railway link --project <STAGING_PROJECT_ID> --environment staging --service <STAGING_SERVICE_ID>
railway status --json
railway up --project <STAGING_PROJECT_ID> --environment staging --service <STAGING_SERVICE_ID> --ci
vercel deploy --project <DEDICATED_STAGING_PROJECT> --scope <VERCEL_TEAM> --prod
```

Check the `/data` volume attachment before the Railway command. Keep production identifiers out of this checkout. A local upload includes uncommitted source, so retain its source manifest and image digest; the branch head alone does not identify this audit's changes.

## Native cold-restore exercise

Two disposable cold-backup tests now copy complete worker and relay state after shutdown, remove the original fixture state, restore it to its original path, and check SQLite integrity. Worker restoration preserves the saved candidate digest, consumed duration/coordinator budget, original approval operation and developer index; retrying the interrupted approval makes no provider call and leaves local delivery pending. Relay restoration preserves an active Owner session, project grant and worker token, while refusing the removed Reviewer's session, an outsider's worker access and a revoked worker token.

Run them with `PYTHONPATH=src:tests .venv/bin/python -m unittest test_adversarial_restore -v`. The fixture uses real Git, SQLite and native isolated checks with simulated providers/sign-in. This is native recovery evidence, not a staged volume or Linux/container restore. Restore actual worker state to its original filesystem layout because managed candidate metadata records absolute paths. Keep the full state tree and worker candidate directories together; a database-only backup cannot recreate candidate files. Repeat the exercise on the real staging relay volume and disposable worker before enrollment.

The final local Docker image also passed a separate relay-volume cold restore using `python3 scripts/smoke_container.py --image <AUDIT_IMAGE_TAG> --restore`. It stopped the source runtime, copied complete synthetic state into a different empty volume, compared file hashes, and started the replacement runtime on that restored volume. Active session state and signed-out/revoked state remained correct; the test removed both volumes. This is local container evidence, with no real provider or participant data. It does not replace the actual staging backup and worker-candidate exercise.

## Evidence required before enrollment

Run the [pilot launch checklist](PILOT.md#launch-checklist) against the recorded staged source. At minimum retain:

- Anonymous entry, two independent account sign-ins, personal isolation, explicit team pairing, project grants, invitation expiry and removed-member/session/worker revocation results.
- One successful task with available independent-provider quota, an explicit correction, new checks/review/digest, different-human team approval, and separate local/GitHub delivery. Record failures as outcomes.
- A draft PR containing exactly the approved tree on `parallax/<workflow-id>`, then an approved revision updating the same PR. Confirm original branch/index and unrelated local edits remain preserved.
- Interrupted publication recovery with the original operation ID, remote base drift, external PR-head edits, removed installation, token expiry, invalid/duplicate webhook deliveries, and fresh CI/review retrieval.
- Desktop/mobile screenshots of setup, correction, reviewer handoff, approval, publication and recovery; a real container smoke including state/credential exclusions and Linux isolation.
- A cold backup and restore exercise using only staging state and the disposable worker.

Do not enroll paid participants until these checks pass. Agree price, scope, provider-charge responsibility, support and cancellation terms manually. Public prices and productivity claims remain unset.

Current live blockers: actual staging URLs/repository/App authorization are not configured for this run, and Claude's fresh live attempt hit quota before a candidate. Docker started on the October 10 retry: the real image, credential-canary exclusions, three-container persistence/revocation smoke and cold volume restore passed. Default container namespaces remain unavailable, and Parallax refuses execution safely; validate Linux coding on a compatible worker host. Final local desktop/mobile screenshots and the simulated same-PR revision walkthrough are recorded in [website-first acceptance](WEBSITE-FIRST-ACCEPTANCE.md). Live-provider/GitHub delivery must still be recorded separately. None of the local fixtures establishes live pilot readiness.
