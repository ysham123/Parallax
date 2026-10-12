# Reliability and modernization preview

This wave is local implementation in `Parallax-reliability-20261011`, on `codex/reliability-modernization`. It starts from the preserved product tree `557602e227f469aea80dee68423f7c3a6d899bec`. It has not been published, deployed or cleared for paid enrollment. See [the legacy modernization exercise](LEGACY-MODERNIZATION.md) and [live acceptance requirements](PILOT.md).

## Execution and dependency boundaries

Execution records an active interval in a separate durable budget table before provider work. Recovery on the same machine boot charges elapsed monotonic time through reconciliation, including unknown downtime. A changed boot or unavailable clock consumes the remaining allowance. Normal shutdown closes the interval, so subsequent offline approval wait does not count. Recovery cannot refund a saved interval; an explicitly requested revision gets a separate run and budget. This conservative policy can exhaust a task after a long outage. Inspect the interrupted work before starting another task.

Python dependency provisioning accepts exact pinned requirements with SHA-256 hashes or vetted local wheel files. It rejects source directories, editable/VCS/URL dependencies, unhashed registry inputs and custom index directives. The download step runs the trusted interpreter with sanitized requirements in a repository-free private staging directory. It admits only binary wheels; installation then runs offline. Supply a complete hash-locked wheel-compatible `requirements.txt` or `requirements.lock`, including transitive requirements. A wheel hash identifies bytes and does not establish that dependency code is trustworthy. These restrictions follow [pip's secure installation controls](https://pip.pypa.io/en/stable/topics/secure-installs/); they intentionally refuse projects needing automatic source builds.

Native provider permissions are enforced per supported adapter. This preview refuses native execution when the adapter cannot establish its required filesystem/tool boundary. In particular, native Grok is unavailable under this policy; use a supported API transport if appropriate. Claude and Antigravity have restricted tools and cannot use arbitrary shell/content-grep actions. Consult modes cannot edit candidates. Provider authentication may still require vendor-specific credential access for the vendor process; agent tools must not expose it. Canary tests establish the tested adapter and version boundaries, not immunity to every vendor implementation or prompt.

## Evidence and control

Native task recovery starts a fresh provider conversation against the saved candidate and consumed budget. It does not restore a vendor session whose permissions may predate this preview. Native session reuse is disabled until restoration of the scoped policy is verified; API session behavior remains separate.

An ordinary Build stops after an explicit quota refusal from its only independent implementer when that attempt produced no changes. The failed attempt, diagnostics and consumed budget remain saved for inspection and explicit recovery; remaining time does not reset the attempt limit. A configured alternative implementer can still complete the work. Transient rate limits retain their existing handling. This narrow stop does not cover Compare variants, partial patches or a coordinator acting as the only writer.

Independent review follows the same rule. A reviewer that reports exhausted plan or account quota is skipped for the rest of that execution, and the next independent provider in preference order reviews instead (configured reviewers first, then the coordinator and team, never a contributor to the candidate). When no independent reviewer has capacity left, at task review or the combined final review, the run stops with a `provider_quota` recovery category instead of spending coordinator turns on reviews that cannot succeed. Resuming clears the skip list so a restored provider is tried again; consumed time is kept. This came from the October 12 Excalidraw run, where the only independent reviewer ran out mid-run, the coordinator spent its remaining turns on failing reviews and the recorded stop read as a coordinator limit.

Workers batch mirrored evidence by serialized bytes and keep heartbeat/control separate from evidence transfer. Cancellation has reserved admission and processing capacity. A record exceeding the relay limit remains complete on its worker and produces a durable transport diagnosis. It is not truncated into a passing receipt. Studio must label that evidence unavailable remotely; team approval refuses evidence that cannot be fully mirrored. An operator can inspect the preserved run locally or reduce the scope of a fresh task. This preview has no chunked large-artifact delivery protocol.

History summaries omit comment bodies. A revoked team worker leaves a read-only audit archive of minimal task/run/operation identities, actors, status, digests and counts. Archive reads still require current membership and project access; archive counts do not establish that raw evidence is available. Personal worker removal remains a purge. Raw cached source, prompts and provider output are not retained by the team archive.

GitHub feedback refresh paginates checks, statuses, review comments and reviews. It limits each collection to 1,000 entries and 1 MiB of displayed fields, records refresh time, and marks page failures, changing counts/heads and exceeded limits incomplete. Review the linked GitHub PR when feedback is incomplete. Feedback never starts an agent automatically and is not a new approval decision. These requests use [GitHub's pagination parameters](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api).

## Interrupted publication after the original actor loses access

Revocation remains effective. Another member cannot reuse the removed actor's operation ID or invent a successful delivery receipt. Automatic takeover is not implemented. Do not delete the publication journal, restore revoked sessions, force-push or change the original operation actor to make a retry pass.

For the pilot operator, the safe recovery procedure is:

1. Stop publication retries and retain a cold backup of both relay and worker state. Record the workspace, workflow, original operation ID and actor, approved candidate digest, repository binding, expected base/head and any saved commit/PR identity. Keep credentials and source out of support messages.
2. Have an authorized repository maintainer inspect the dedicated branch and draft PR through GitHub. Compare the remote commit's tree, parent and exact operation marker to the saved approved tree. A matching branch name or title alone is insufficient. Recheck remote state after inspecting it.
3. If a remote commit or PR already exists, keep the original publication pending/unreconciled until the operator can reconcile it with the original authorized actor or a separately reviewed recovery implementation. The inspection is evidence, not a completed Parallax publication.
4. If the old actor remains revoked, the maintainer may explicitly manage or close the remote draft under their own GitHub identity. Record that manual action separately. Start any replacement task from a fresh clean remote baseline, with a new requester, checks, review and human approval. Do not reuse the stranded candidate as an unapproved publication.

This limitation is a pilot recovery gate, especially for teams. The procedure avoids an authorization bypass; it does not provide seamless takeover.

## Acceptance

Keep native canaries, dependency-egress checks, abrupt-process recovery, transport saturation/size cases, archive authorization tests, frontend checks and desktop/mobile inspection with the exact reviewed source. Deterministic providers and simulated GitHub remain fixtures. Live onboarding, two-account revocation, available independent-provider quota, real App publication/webhook recovery and a measured customer comparison remain required before opening the invited pilot.
