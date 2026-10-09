# Remote MCP for Parallax Team

Phase 3 adds an optional account-authorized MCP endpoint for the OpenAI directory. It does not change the existing local Codex or Claude Code installations. The endpoint is off until `PARALLAX_REMOTE_MCP=on` is set. Merge and production rollout remain separate steps.

## What is implemented

`POST /api/mcp` implements stateless Streamable HTTP with JSON responses. It supports initialization, ping, tool discovery and tool calls. GET streaming and session deletion return 405. Discovery is served at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/api/mcp`. OpenAI's verification token is served at `/.well-known/openai-apps-challenge` when configured. Vercel forwards these paths to the runtime.

The eight tools list machines, generate pairing instructions, assess projects, start reviews, start builds, read runs, list runs and stop runs. Every operation uses the account's personal workspace and the existing worker relay. Projects are selected with handles from `list_machines`, not supplied filesystem paths. No hosted execution or operator access is granted. An operator account must use a separate personal account for remote tools.

Reviews and builds continue on the paired machine after the tool responds. A timeout is ambiguous: inspect history before retrying a start. `stop_run` uses the engine's cancellation route. Builds default to retaining a candidate; `apply_changes=true` requests integration through the existing gates. Builds still require an independent provider. Worker disconnects, quotas and relay limits retain their existing behavior.

Responses contain bounded summaries and check outcomes. The facade excludes raw prompts, patches, logs, provider sessions, artifact directories and workspace account IDs. Machine and run IDs are opaque handles needed for follow-up tools. Common secrets and absolute paths are scrubbed from free text, but this is not a general guarantee that provider-authored prose contains no sensitive project content. Users should connect only clients they trust with run summaries. Pairing codes are intentionally returned only by the pairing tool and expire after five minutes.

## OAuth and consent

Supabase remains the authorization server. Parallax validates asymmetric JWT signatures using its fixed project's JWKS endpoint, the exact issuer, expiration, issuance time, client ID and a resource-specific audience. Ordinary account JWTs with audience `authenticated`, ID tokens, operator keys and browser cookies cannot authorize MCP. Key caching is bounded; an unknown key can trigger at most one refresh every 30 seconds.

The `/oauth/consent` page signs the person in by email/password, GitHub or Google, establishes a Parallax session, then shows the actual requesting client and requested identity scopes. The consent POST requires that session, its short-lived consent cookie and the Studio origin. Social consent uses a separate PKCE flow and signed cookie bound to the authorization ID.

Normal Studio sign-in still discards the Supabase token immediately. Consent keeps an access token in process memory only, valid for five minutes; cleanup runs every 15 seconds, and decisions or sign-out discard it immediately and attempt to revoke that provider session. Refresh tokens are never retained. Restarting the process requires signing in again. Run one runtime process per state volume, as with the existing relay; this transient state is not shared between replicas.

An explicit approval records a local account/client grant. Each MCP request checks that grant and the active account. `/connections`, also linked from the account menu, revokes access immediately for subsequent requests. Supabase consent for a locally revoked client is cleared on the next consent sign-in, forcing a fresh approval when reconnecting. Already-started runs continue until stopped. Account deletion removes its grants. Revocation is account scoped.

## Configure staging before enabling production

1. Finish the custom-domain setup from [DEPLOYMENT.md](DEPLOYMENT.md). The public origin must be the canonical HTTPS Studio origin. Keep the runtime's host/origin allowlists exact.
2. Configure normal Supabase sign-in and confirm it works. Enable the Supabase OAuth 2.1 server and dynamic client registration. Set the authorization/consent path to `/oauth/consent` on the Studio site. Add `https://parallax.yosefshammout.com/api/oauth/callback` to the sign-in redirect allowlist alongside the existing normal callback.
3. Use an asymmetric Supabase signing key (ES256, RS256 or EdDSA). Install and enable the custom access-token hook below. It sets the MCP audience only for OAuth-client tokens, including refreshes, and leaves ordinary Studio tokens alone. Do not enable remote MCP with the default `authenticated` audience.
4. On the runtime set `PARALLAX_REMOTE_MCP=on`, retaining the existing Supabase and public-origin settings. Set `PARALLAX_OPENAI_CHALLENGE` to the exact token the OpenAI dashboard supplies. This value is public; do not use an account credential here.
5. Deploy the matching Studio and runtime revisions. Confirm the discovery document's `resource` is exactly `https://parallax.yosefshammout.com/api/mcp`, its issuer is the configured Supabase project's `/auth/v1`, and a request without a token returns 401 with `WWW-Authenticate`.
6. Connect through developer mode in ChatGPT and Codex. Verify email and social consent, approve/deny, all eight tools, expired/wrong-audience tokens, disconnected machines and revocation. Use two personal accounts to check that machine/run identifiers never cross workspaces.

Example Supabase SQL hook, for this dedicated Parallax Auth project. Review the canonical audience before applying it. Merge with any existing token hook rather than replacing unrelated claims or policy:

```sql
create or replace function public.parallax_mcp_access_token(event jsonb)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  claims jsonb := event->'claims';
begin
  if coalesce(claims->>'client_id', '') <> '' then
    claims := jsonb_set(claims, '{aud}', '"https://parallax.yosefshammout.com/api/mcp"'::jsonb);
    event := jsonb_set(event, '{claims}', claims);
  end if;
  return event;
end;
$$;
grant usage on schema public to supabase_auth_admin;
grant execute on function public.parallax_mcp_access_token(jsonb) to supabase_auth_admin;
revoke execute on function public.parallax_mcp_access_token(jsonb) from authenticated, anon, public;
```

Select this function in Supabase Authentication's Custom Access Token hook settings. A correct hook alone does not grant access: Parallax also requires an existing local client consent. If the Auth project serves other APIs, restrict the hook to the applicable client IDs instead of changing all OAuth audiences. Verify a newly issued token and a refreshed token against the actual staging endpoint before rollout. This SQL is prepared configuration, not applied configuration.

Sources checked October 9, 2026: [Supabase OAuth setup](https://supabase.com/docs/guides/auth/oauth-server/getting-started), [token security and custom audiences](https://supabase.com/docs/guides/auth/oauth-server/token-security), [custom-token hook contract](https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook), and [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization). The authorization/consent REST paths are verified against Supabase's [auth-js implementation](https://github.com/supabase/supabase-js/blob/master/packages/core/auth-js/src/GoTrueClient.ts).

## Reviewer environment and package

Use a dedicated confirmed-email personal account, a password, no MFA, and sample data only. Enter those credentials in the private dashboard review form, never the ZIP or repository. Keep its worker online throughout review.

The earlier plan's Claude-only VM can demonstrate reviews but cannot demonstrate a successful build: the engine requires another provider. For complete coverage, provide an always-on worker with both Claude and Codex (for example, a dedicated Mac) or adapt the review case to a supported, configured independent API provider. A Railway worker may need an API connection for the second provider. Do not remove the independent-review gate. Paid VM and provider configuration need to be settled before the live review.

Prepare a small Git sample project with one documented parser bug, deterministic passing/failing checks and no credentials. Keep the worker's state outside that project. Run every case in `openai/review-cases.json` against the dedicated account and record the outcome on both supported clients. Record a walkthrough using the same setup. The cases are proposed until these live runs are recorded.

Build a review draft locally:

```sh
python3 scripts/build_openai_plugin.py --draft
```

After recording, build the upload ZIP with the actual accessible video URL:

```sh
python3 scripts/build_openai_plugin.py --demo-recording-url https://your-video-host/your-recording
```

The ZIP is `dist/parallax-team-openai.zip`. It contains a portable `plugin.json`, remote `mcp.json`, one onboarding skill, the icon, README and license. The existing Codex install ID remains `codex-claude-team`; the directory package is `parallax-team`. The builder refuses a non-draft package without a recording URL, but it does not verify identity, domain ownership, live OAuth, reviewer credentials or actual case results.

Complete individual developer verification and the required organization/project setup, upload the ZIP, verify the domain, scan the tools, supply private reviewer access, and submit only after the live cases pass. The user performs the portal submissions. See [OpenAI's submission requirements](https://developers.openai.com/plugins/deploy/submission).

To disable remote access, set `PARALLAX_REMOTE_MCP=off` and restart the runtime. Existing local plugins and ordinary Studio sessions keep their original behavior. No PR merge, production rollout, account creation or directory submission is implied by a passing local build.

## Draft question for OpenAI support

Subject: Public directory support for a local MCP coding plugin

Hi OpenAI support,

I'm building Parallax, an open-source app that coordinates coding providers on a user's own machine. Its existing Codex plugin uses a local stdio MCP server because it launches locally signed-in CLIs and works in approved project directories. We're also preparing a remote HTTPS MCP integration that relays account-authorized requests to paired machines.

Can a plugin with a local stdio MCP server be reviewed for the public Plugins Directory, or is public distribution currently limited to skills-only packages and remote HTTPS MCP servers? If local plugins require a separate review process, what materials would you need?

Source: https://github.com/ysham123/Parallax

Thanks,
Yosef Shammout

This note is a draft for the user to send; it has not been sent.
