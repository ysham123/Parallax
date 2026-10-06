# Personal hosted workspace validation

Validated on October 6, 2026 with Vercel Studio and a persistent Railway Cloud Agent VM. This is a private operator workspace protected by an access key, not a multi-tenant public service.

- Standard Railway container: health and authentication worked, but the kernel rejected bubblewrap's required namespaces. Build and Compare correctly remained blocked. Its replacement VM enforced the required sandbox; no gate was bypassed.
- Linux VM: Python 3.13.7, native Node 24.21.0, Codex 0.160.1, Claude Code 2.1.289, Grok 1.0.46. Antigravity was not installed. Provider credentials were not imported from the operator's laptop.
- All 171 deterministic runtime tests passed on the actual VM (two platform-specific skips). These include real Python/Node project commands, Git integration, cancellation, recovery, dirty-tree preservation, and an API-command canary that attempted secret and external-file access.
- Studio: 60 graph inspection assertions passed, plus TypeScript compilation, local packaged assets, and hosted URL/routing checks. Failed independent assessments display a failed review state rather than a successful review badge.
- Public Vercel route: health, access-key exchange, Secure/HttpOnly/SameSite cookie authentication, refresh, durable run history, replaying SSE with Last-Event-ID, receipt/patch downloads, sign-out, foreign-origin rejection, and rejection of projects outside the configured root passed.
- Runtime supervisor was restarted. The original run and browser session survived and Studio reconnected to its stored event history. Sleep/wake is an operator lifecycle action; automatic VM boot of the supervisor has not been established.
- Real Grok consultation on a disposable project failed because the VM was unauthenticated. Diagnostics now correctly report sign-in required even when the CLI prints available models. This attempt is evidence of the authentication failure path, not a successful hosted inference/build demonstration.

The infrastructure and deterministic command tests establish execution capability. A successful native provider turn and a reviewed, checked build still require provider sign-in on the VM. Hosting does not authenticate providers or grant access to repositories on the operator's laptop.
