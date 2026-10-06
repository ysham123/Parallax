# Vercel and Railway

The recommended default for Parallax users is local execution: existing CLI sign-ins, project files, development environments, snapshots, and integration stay on their computer. Vercel hosts the public entry page. It opens Studio through the installed plugin. The website does not connect to localhost in the background or upload its launch token.

An optional dedicated-team deployment serves Studio on Vercel and the runtime on Railway. This is a shared operator workspace, not a public multi-user SaaS: everyone with its access key can see the team's runs, manage connections, and operate projects. Use a separate service and volume for each trusted team. User accounts, tenant isolation, local executor pairing, and remote per-run workers need a separate implementation before opening this mode to unrelated customers.

## Vercel

Import `ysham123/Parallax` with **Root Directory set to the repository root**, Framework Preset **Other**, and Node.js **22.x or 24.x**. The checked-in `vercel.json` supplies installation and build commands. Leave Output Directory unset: the build writes Vercel Build Output API v3 to `.vercel/output`.

With no environment variables, Vercel builds the local Studio entry page. No runtime, provider keys, or database are required. Deep links load the entry page; missing hashed assets return 404. API paths return a `local_runtime_required` diagnostic, rather than HTML pretending to be API data.

For a dedicated Railway-backed Studio, set this **build environment variable** on Vercel and redeploy:

```text
PARALLAX_RUNTIME_URL=https://YOUR-RUNTIME.up.railway.app
```

Only a public HTTPS origin is accepted. The build selects the hosted sign-in screen and proxies `/api/*` to Railway. Fetch calls, cookie authentication, SSE events, and downloadable patches/receipts remain on the Vercel origin. Do not put the workspace access key or provider credentials in Vercel variables or any `VITE_*` variable. The workspace access key is entered at sign-in and exchanged for a Secure, HttpOnly, SameSite=Strict cookie. Reloading reconnects using that cookie. No key is saved in browser storage.

The build uses [Vercel's Build Output API](https://vercel.com/docs/build-output-api/configuration) and [external rewrites](https://vercel.com/docs/routing/rewrites). End-to-end cookie forwarding and SSE should be checked on the actual Vercel/Railway domains before inviting a team. Preview domains must be added individually to Railway's origin/host configuration; no wildcard origins are accepted. Never point an untrusted preview build at a production runtime.

## Railway

Create a service from the same repository. The root `Dockerfile` and `railway.json` select the container, `/api/health` startup check, and one replica. Attach a **persistent volume at `/data`** before use. SQLite, journals, workspaces, private environments, and project clones need this volume to survive redeploys. There is one runtime process and one replica; do not enable autoscaling or serverless sleep for active runs.

Set these Railway service variables:

| Variable | Value |
| --- | --- |
| `PARALLAX_ACCESS_TOKEN` | A random secret of at least 32 characters, up to 512 |
| `PARALLAX_STUDIO_ORIGINS` | Exact Vercel/custom HTTPS origin; comma-separated for explicitly trusted previews |
| `PARALLAX_ALLOWED_HOSTS` | Railway public hostname and Studio hostname, comma-separated, with no scheme, ports, paths or wildcards |
| `PARALLAX_HOME` | `/data/parallax` (container default) |
| `PARALLAX_PROJECTS_ROOT` | `/data/projects` (container default) |
| `PORT` | Railway supplies this automatically |

Generate the access key locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Keep it stable across restarts so sessions reconnect; rotating it invalidates existing sessions. Set provider API keys on Railway as service secrets and configure connections using environment-variable references in Studio. macOS Keychain storage is unavailable in Linux containers.

The runtime binds `0.0.0.0:$PORT` only through the explicit `python -m parallax.cloud` entry point. Local CLI launch remains authenticated loopback-only. Startup fails when the access key, origins, or allowed hosts are absent or invalid. The Railway healthcheck hostname is allowed only for `/api/health`, per [Railway's healthcheck contract](https://docs.railway.com/deployments/healthchecks). Other requests require a session or bearer token. Cross-origin writes and project paths outside the configured project root, including escaping symlinks, are rejected. Browser sign-in uses a body, never a URL token. A process-local sign-in throttle complements a high-entropy access key; add platform traffic protection for internet exposure.

Clone projects under `/data/projects` using Railway's administrative shell and separately provision Git credentials. The service cannot see files or CLI sign-ins on a user's laptop. Work stays on the Railway clone; pushing its results still requires a separate authorized action.

## Execution readiness

The base image contains Python, Node/npm, Git, bubblewrap, and socat. It does **not** install or authenticate any provider CLI. Install tested native CLI versions in a custom image if needed. Provider status and model discovery must pass on that container before starting a team.

Installing bubblewrap alone is insufficient: the hosting kernel must allow its required user/network namespaces. Check `/api/deployment` after signing in and the project readiness screen before Build or Compare. These modes remain blocked when isolation is unavailable. API worker command execution currently requires the macOS sandbox, so Linux API workers cannot run project commands. API consultation and native CLI compatibility are separate capabilities; deployment readiness does not establish four-provider build readiness on Railway. Keep production implementation runs local until the selected hosted provider and command checks pass. Never disable sandbox gates to accommodate a hosting platform.

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
