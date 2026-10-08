# Vercel and Railway

The recommended default for Parallax users is local execution: existing CLI sign-ins, project files, development environments, snapshots, and integration stay on their computer. Vercel serves Studio. Without a runtime it serves an entry page that opens Studio through the installed plugin; it never connects to localhost in the background or uploads a launch token.

With a hosted runtime, the Vercel site becomes a public product entry with individual accounts. Anyone can sign up with email and password, GitHub, or Google and receive a private personal workspace. A personal workspace runs agents only on machines its owner pairs; it cannot use the hosted runtime's own execution engine, CLI sign-ins, or project clones. The deployment operator keeps a separate operator workspace, opened by configured owner accounts or the deployment access key, which retains hosted execution and the machines paired before accounts existed. See [Accounts and workspaces](#accounts-and-workspaces).

## Vercel

Import `ysham123/Parallax` with **Root Directory set to the repository root**, Framework Preset **Other**, and Node.js **22.x or 24.x**. The checked-in `vercel.json` supplies installation and build commands. Leave Output Directory unset: the build writes Vercel Build Output API v3 to `.vercel/output`.

With no environment variables, Vercel builds the local Studio entry page. No runtime, provider keys, or database are required. Deep links load the entry page; missing hashed assets return 404. API paths return a `local_runtime_required` diagnostic, rather than HTML pretending to be API data.

For a dedicated Railway-backed Studio, set this **build environment variable** on Vercel and redeploy:

```text
PARALLAX_RUNTIME_URL=https://YOUR-RUNTIME.up.railway.app
```

Only a public HTTPS origin is accepted. The build selects the public entry, sign-in pages, and workspace Studio, and proxies `/api/*` to Railway. Fetch calls, cookie authentication, SSE events, and downloadable patches/receipts remain on the Vercel origin. Do not put the operator access key, Supabase keys, GitHub client secret, or provider credentials in Vercel variables or any `VITE_*` variable. Every sign-in, whether through an account or the operator access key at `/operator`, is exchanged for an opaque Secure, HttpOnly, SameSite=Strict session cookie backed by a server-side session record. Reloading reconnects using that cookie, and signing out deletes the record. No key or token is saved in browser storage.

The build uses [Vercel's Build Output API](https://vercel.com/docs/build-output-api/configuration) and [external rewrites](https://vercel.com/docs/routing/rewrites). End-to-end cookie forwarding and SSE should be checked on the actual Vercel/Railway domains before inviting a team. Preview domains must be added individually to Railway's origin/host configuration; no wildcard origins are accepted. Never point an untrusted preview build at a production runtime.

## Railway

Create a service from the same repository. The root `Dockerfile` and `railway.json` select the container, `/api/health` startup check, and one replica. Attach a **persistent volume at `/data`** before use. SQLite, journals, workspaces, private environments, and project clones need this volume to survive redeploys. There is one runtime process and one replica; do not enable autoscaling or serverless sleep for active runs.

Set these Railway service variables:

| Variable | Value |
| --- | --- |
| `PARALLAX_ACCESS_TOKEN` | A random secret of 32 to 512 characters (at least 12 distinct), for example from `openssl rand -base64 36` |
| `PARALLAX_STUDIO_ORIGINS` | Exact Vercel/custom HTTPS origin; comma-separated for explicitly trusted previews |
| `PARALLAX_ALLOWED_HOSTS` | Railway public hostname and Studio hostname, comma-separated, with no scheme, ports, paths or wildcards |
| `PARALLAX_PUBLIC_ORIGIN` | Studio origin used for sign-in callbacks; required only when several Studio origins are listed |
| `PARALLAX_SUPABASE_URL` | Supabase project URL, such as `https://abcd.supabase.co`; turns on email, GitHub and Google sign-in |
| `PARALLAX_SUPABASE_PUBLISHABLE_KEY` | The project's publishable key (or legacy anon key); used only by the runtime |
| `PARALLAX_SUPABASE_SECRET_KEY` | Optional secret key (or legacy service-role key); deletes the Supabase user when an account is deleted |
| `PARALLAX_OWNER_EMAILS` | Comma-separated verified emails that open the operator workspace |
| `PARALLAX_ALLOWED_EMAILS` | Emails admitted when `PARALLAX_SIGNUP=allowlist` |
| `PARALLAX_GITHUB_CLIENT_ID` | Built-in GitHub OAuth App client ID, for deployments without Supabase; set together with the secret |
| `PARALLAX_GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret |
| `PARALLAX_OWNER_GITHUB_IDS` | Comma-separated numeric GitHub account IDs that open the operator workspace |
| `PARALLAX_SIGNUP` | `open` (default), `allowlist`, or `closed` |
| `PARALLAX_ALLOWED_GITHUB_IDS` | Numeric GitHub IDs admitted when `PARALLAX_SIGNUP=allowlist` |
| `PARALLAX_MAX_ACCOUNTS` | Account limit, default 100 |
| `PARALLAX_HOME` | `/data/parallax` (container default) |
| `PARALLAX_PROJECTS_ROOT` | `/data/projects` (container default) |
| `PORT` | Railway supplies this automatically |

The access key, Supabase keys, and GitHub client secret are read once at startup and removed from the runtime's environment, so provider CLIs, project checks, and Git never inherit them. Generate the access key locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Keep it stable across restarts; rotating it ends every session it opened and any sign-in in progress, while account sessions continue. Set provider API keys on Railway as service secrets and configure connections using environment-variable references in Studio. macOS Keychain storage is unavailable in Linux containers.

The runtime binds `0.0.0.0:$PORT` only through the explicit `python -m parallax.cloud` entry point. Local CLI launch remains authenticated loopback-only. Startup fails when the access key, origins, or allowed hosts are absent or invalid. The Railway healthcheck hostname is allowed only for `/api/health`, per [Railway's healthcheck contract](https://docs.railway.com/deployments/healthchecks). Other requests require a session or bearer token. Cross-origin writes and project paths outside the configured project root, including escaping symlinks, are rejected. Browser sign-in uses a body, never a URL token. Durable sign-in and pairing limits complement a high-entropy access key; add platform traffic protection for internet exposure.

Clone projects under `/data/projects` using Railway's administrative shell and separately provision Git credentials. The service cannot see files or CLI sign-ins on a user's laptop. Work stays on the Railway clone; pushing its results still requires a separate authorized action.

## Accounts and workspaces

### Enable sign-in with Supabase (email, GitHub, Google)

Supabase Auth handles sign-up, email confirmation, password reset, and GitHub and Google sign-in. The runtime makes every call to Supabase itself: the browser only talks to `/api` on the Studio origin, keys never reach it, and the Supabase token is used once to read the user and then revoked. Parallax keeps its own server-side session, so the workspace boundary, limits and deletion below apply unchanged.

In the Supabase dashboard:

1. **Providers.** Under Authentication, Sign In / Providers:
   - Turn on Email with "Confirm email" on and a minimum password length of 10.
   - For GitHub, create a GitHub OAuth App with Homepage URL set to the Studio origin and Authorization callback URL `https://<project-ref>.supabase.co/auth/v1/callback`, then paste its client ID and secret into Supabase.
   - For Google, create a Web OAuth client in Google Cloud with the same callback as an authorized redirect URI, then paste its client ID and secret.
2. **URL configuration.**
   - Set the Site URL to the Studio origin, for example `https://parallax-studio-six.vercel.app`.
   - Add `<origin>/api/auth/oauth/callback` and `<origin>/reset` to the redirect URLs.
3. **Email templates.** Point the links at the runtime, so they work on any device:
   - Confirm signup: `{{ .SiteURL }}/api/auth/confirm?token_hash={{ .TokenHash }}&type=email`
   - Reset password: `{{ .SiteURL }}/reset?token_hash={{ .TokenHash }}&type=recovery`
4. **SMTP.** Supabase's built-in email sends only a few messages an hour. Under Authentication, Emails, SMTP Settings, use your own provider, for example Resend:
   - host `smtp.resend.com`, port `465`, username `resend`, password your Resend API key;
   - a sender such as `no-reply@<your domain>` on a domain verified in Resend.
5. **Rate limits.** Because every request comes from the runtime's address, raise the per-IP limits for sign-ups and sign-ins under Authentication, Rate Limits. Parallax applies its own per-address limits: 5 sign-ups and 3 reset emails per hour, and a 15-minute pause after 10 failed passwords.
6. **Keys.** Copy the publishable key and, optionally, the secret key from Project Settings, API Keys.

On the runtime, set `PARALLAX_SUPABASE_URL`, `PARALLAX_SUPABASE_PUBLISHABLE_KEY`, `PARALLAX_SUPABASE_SECRET_KEY` and `PARALLAX_OWNER_EMAILS`, then restart. `GET /api/auth/config` lists the providers the project has turned on. Both keys are read once at startup and removed from the runtime's environment.

### Built-in GitHub sign-in (without Supabase)

GitHub sign-in uses a GitHub OAuth App with the authorization code flow, PKCE (S256), and a state value bound to the browser that started sign-in. It requests no scopes, so Parallax reads only the public profile and cannot see repositories. The GitHub access token is used once to read the profile and is never stored. One-time setup:

1. In GitHub, open Settings, Developer settings, OAuth Apps, and choose New OAuth App.
2. Set Homepage URL to the Studio origin, for example `https://parallax-studio-six.vercel.app`.
3. Set Authorization callback URL to the same origin followed by `/api/auth/github/callback`.
4. Register the app, then generate a client secret.
5. Set `PARALLAX_GITHUB_CLIENT_ID` and `PARALLAX_GITHUB_CLIENT_SECRET` on the runtime, add your numeric GitHub ID to `PARALLAX_OWNER_GITHUB_IDS` (`gh api user --jq .id` prints it), and restart the runtime.

`GET /api/auth/config` reports whether sign-in is configured. Until it is, the public entry says so and the operator can still sign in at `/operator`. Startup fails if only one of the client ID and secret is set.

### What each workspace can do

| | Personal workspace | Operator workspace |
| --- | --- | --- |
| Opened by | Its account | Accounts in `PARALLAX_OWNER_EMAILS` or `PARALLAX_OWNER_GITHUB_IDS`, or the access key |
| Paired machines | Up to 3, visible only to this workspace | Up to 50, including machines paired before accounts existed |
| Hosted execution on the runtime | Not available | Available |
| Runtime CLIs, connections, profiles, project clones | Not reachable | Reachable |

The boundary is enforced on the server. Requests from a personal workspace may use only session, account, and machine routes; every other API route answers 403 with `hosted_execution_unavailable`. Machine, pairing, relay, cached evidence, event replay, and download operations require the caller's workspace, and another workspace's machine is indistinguishable from a missing one (404). Pairing codes carry the workspace that generated them. Worker tokens authenticate only their own queue and evidence, and cannot act as Studio sessions. Removing an email from `PARALLAX_OWNER_EMAILS`, or an ID from `PARALLAX_OWNER_GITHUB_IDS`, ends that account's operator access on its next request. With Supabase, a GitHub sign-in also matches `PARALLAX_OWNER_GITHUB_IDS` through its GitHub identity.

### Limits, retention, and deletion

Limits are stored in SQLite and survive restarts. A personal workspace can hold 3 machines, 3 unused pairing codes, and 20 new codes per hour. Relayed Studio requests are limited to 600 per five minutes per personal workspace, with at most 32 unanswered requests or 32 MiB queued per machine, 16 concurrent relayed requests, and 8 live event streams. Each machine's mirrored evidence is kept within 96 MiB, pruning the oldest events first; a restarted worker that replays its history cannot displace newer evidence. Single events above 256 KiB are mirrored as a truncation marker while the complete event stays on the machine. The operator workspace has larger limits. New accounts are limited to 30 per hour. Pending GitHub and Google sign-ins keep no server state (the browser's flow cookie is sealed with a key derived from the access key), so anonymous traffic cannot fill storage or displace anyone's sign-in. Rejected operator access keys, at `/operator` or as a bearer key, are limited to 20 per minute; a valid key is never throttled. Pairing codes carry 192 random bits and need no shared guess limit. Request bodies are bounded before routing, including chunked bodies: 2 MiB for Studio routes, 128 KiB for unauthenticated worker pairing, and 8 MiB plus framing for authenticated worker messages. Answers waiting for Studio to collect them count against each machine's 32 MiB queue budget and expire after five minutes, including for machines that go offline. When free disk space falls below 512 MiB, personal machines stop mirroring new evidence (workers from this release keep it and resend it later) and large relayed requests and answers pause, while run controls such as stop and steer keep working and local runs continue.

A relayed command is deleted as soon as Studio receives its answer; answers nobody collected are dropped after five minutes and unanswered commands after one day. Disconnecting a machine revokes it and deletes its mirrored evidence from the runtime. Deleting an account removes its workspace, machines, pairing codes, mirrored evidence, and sessions, and with `PARALLAX_SUPABASE_SECRET_KEY` set, the Supabase user; GitHub and Google keep their own record of the authorization until the user revokes it there. Hosted data is visible to whoever administers the runtime and its volume; describe this to users and back the volume up as private data.

### Migrating an existing deployment

The migration runs at startup and only adds tables and indexes (and columns on its own new tables), so the previous release can run against the same database if you roll back. Operator machines keep working across a rollback. Personal machines and pairing codes are invisible to the previous release: it sees those machines as revoked and refuses their tokens, so their workers stop with an authorization error. After rolling forward again, users restart their workers; their saved connections are still valid, so no new pairing is needed. Machines and pairing codes that predate workspaces belong to the operator workspace, so existing workers keep their tokens and reconnect without pairing again. Evidence accounting is recomputed from stored rows. Back up the volume before upgrading anyway. Sessions from before this release are not accepted; sign in again or at `/operator`.

In 1.3, accounts from the GitHub-only release are copied into a provider-neutral accounts table at startup and keep their workspaces. If you then roll back to 1.2, existing accounts keep working but new GitHub sign-ins fail until you roll forward.

### Public launch checklist

Merging to `main` rebuilds the Vercel site only. The runtime changes when you update and restart it, so the public site keeps working against the previous runtime until then. Until then the public entry leads with installing the plugin, and the operator signs in at `/operator`.

1. Back up the runtime volume or VM state directory.
2. Set up Supabase ([Enable sign-in with Supabase](#enable-sign-in-with-supabase-email-github-google)), including its email templates and SMTP.
3. Set the Supabase variables and `PARALLAX_OWNER_EMAILS`. Choose `PARALLAX_SIGNUP` (`open` with `PARALLAX_MAX_ACCOUNTS`, or `allowlist` with `PARALLAX_ALLOWED_EMAILS` while testing). Set `PARALLAX_PUBLIC_ORIGIN` if more than one Studio origin is listed.
4. Update the runtime source to the release, reinstall `requirements.lock` with `--require-hashes`, and restart `python -m parallax.cloud`.
5. Check that `/api/health` reports the release version and `/api/auth/config` lists your providers. Then sign up with email and confirm it, log out and back in, reset the password, try GitHub and Google, pair a machine from a personal workspace, run a Review on it, and confirm that the operator workspace still opens.

## Execution readiness

The base image contains Python, Node/npm, Git, bubblewrap, and socat. It does **not** install or authenticate any provider CLI. Install tested native CLI versions in a custom image if needed. Provider status and model discovery must pass on that container before starting a team.

Installing bubblewrap alone is insufficient: the hosting kernel must allow its required user/network namespaces. Check `/api/deployment` after signing in and the project readiness screen before Build or Compare. These modes remain blocked when isolation is unavailable. API workers support project commands through macOS sandbox-exec or enforced Linux bubblewrap. API consultation and native CLI compatibility are separate capabilities; deployment readiness does not establish four-provider build readiness. Never disable sandbox gates to accommodate a hosting platform.

### Persistent VM for hosted coding

An ordinary Railway service can serve consultations but may reject the namespaces required for project commands. For personal hosted coding, use a [persistent Railway Cloud Agent](https://docs.railway.com/cloud-agents/quickstart) and verify the sandbox on that VM. Create it with `railway ca create parallax-worker --no-bootstrap`; connect using `railway ca ssh parallax-worker -- bash`. Its public app domain routes port 8080. Set Vercel's runtime URL to that domain and include both the VM and Studio hostnames in the runtime allowlist.

On the October 6, 2026 validated VM, Parallax's project-command sandbox worked, but native Codex 0.160.1 could not create its required user namespace. Claude's restricted file review worked. Do not treat this VM recipe as a verified native Codex build environment. Linux Codex diagnostics now probe its native sandbox separately and report `sandbox_unavailable` when it fails. Use a compatible worker host or an explicitly configured API connection; keep the isolation gates enabled.

Install this repository in `/app/parallax-runtime`, create a Python 3.13 virtual environment, and install `requirements.lock` with `--require-hashes`. Use the environment's interpreter to run `python -m parallax.cloud` under a process supervisor. With mise-managed Node, put the actual installation's `bin` directory ahead of mise shims in the runtime PATH; `mise which node` identifies it. npm's native wrapper and package are exposed to checks without exposing the rest of the user's toolchain.

Keep state and project clones under `/root/parallax-state` and `/root/parallax-projects`, respectively. Unlike the Docker service's `/data` layout, these locations are within the Linux command sandbox's protected home boundaries. Keep runtime configuration private (directory mode 0700, file mode 0600), outside every project. Optionally set `PARALLAX_WORKSPACE` to an existing project under `PARALLAX_PROJECTS_ROOT`; startup validates that boundary.

[Provider authentication is separate from Railway authentication](https://docs.railway.com/cloud-agents/configuration). Sign in to native CLIs on the VM, or configure API connections with private environment references. Do not copy local provider credentials without explicit authorization. A public model catalog does not prove sign-in; Grok diagnostics require an affirmative native login status.

Sleeping the VM stops its processes and compute billing while preserving its disk. Wake it and restart the runtime supervisor before reopening Studio. The process supervisor handles runtime crashes, but this deployment does not claim automatic boot after a VM sleep or restart. Stop active runs before planned maintenance; after restarting, inspect recovery status rather than dispatching duplicate work. GitHub pushes update the Vercel build; VM source updates and supervisor restarts are a separate operation. Preserve the old service and volume until migration is verified, then stop unused compute.

SQLite and run artifacts are private team data. Back up the Railway volume and avoid storing provider credentials in it. Volumes are mounted at runtime, not during image builds. See [Railway volumes](https://docs.railway.com/volumes).

## Verify before deploying

From the repository root:

```sh
npm ci --prefix studio
npm run test:hosted --prefix studio
node scripts/build_vercel.mjs
# Also test the optional connected build with a non-secret example origin:
PARALLAX_RUNTIME_URL=https://runtime.example.com node scripts/build_vercel.mjs
docker build -t parallax-runtime .
python3 scripts/smoke_container.py
```

The Docker smoke test uses a disposable container, a temporary access key, health checks, and authenticated API requests. It does not start inference or access a real project. CI builds both Vercel modes and the Railway image, runs authentication/origin/workspace boundary tests, and ensures hosted builds do not overwrite the packaged local Studio.

After deployment, verify `/api/health`, sign-in, refresh/reconnect, sign-out, model discovery, provider auth failures, downloaded receipts, and a replaying SSE connection through Vercel. Check Railway logs and the persistent volume after a restart. Run real CLI/provider smoke tests separately in disposable project clones. No deployment is created by these preparation commands.

## Paired local execution

Hosted Studio can control an explicitly paired local worker through an outbound HTTPS relay. Select **Machines** to pair, then choose its name in the **Execution machine** menu. Native sign-ins, project worktrees, checks, and verified integration stay on the chosen machine; the hosted workspace receives run evidence for graph inspection and replay. This bypasses the Railway native Codex compatibility problem by moving execution to a compatible machine, without disabling any sandbox gate. See [local worker setup, scope, and recovery](LOCAL-WORKERS.md).

Pairing approves the workspace that generated the code to operate the exact project roots declared on that worker. In a personal workspace that is only its account; in the operator workspace it is everyone with operator access. A sleeping Mac cannot execute work, and connection revocation reaches an offline worker only after it reconnects.
