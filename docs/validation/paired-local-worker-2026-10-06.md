# Paired local worker validation, October 6, 2026

Hosted Studio on Vercel relayed a real Build through Railway to an outbound macOS worker. Provider credentials stayed on the worker. Native Codex on the Railway VM still fails its user-namespace probe; local execution passed with the existing sandbox gates enabled.

## Native build

Run `2e34551f-8ed1-4a14-a6e8-7e9e38b9aa51` completed using Codex GPT-6.1-Sol/high as coordinator and independent reviewer, and Claude Sonnet/high as implementer. Eight native sessions were recorded. The disposable Git fixture contained a broken addition helper, a staged user note, and an untracked user note.

Claude changed only `math_utils.py`, from subtraction to addition. Codex reviewed both the task diff and the combined candidate. The unchanged supplied check passed five integer cases, including negative inputs and a large integer. Project commands used macOS seatbelt isolation. All five receipt gates passed: current verification, independent combined review, project checks, integration, and preservation. The intended file was applied, the original staging diff matched exactly, and the untracked note and check script remained unchanged. No fixture code was pushed.

The live graph displayed the actual task, implementation, review, provider models/efforts, and event activity. This small demonstration establishes the tested execution path, not productivity or universal provider compatibility. Grok was not authenticated on this Mac; no four-provider hosted build is claimed.

## Regression coverage

The final local suite ran 188 runtime cases successfully, with one Linux-only case skipped on macOS. The preceding 187-case source passed on the real Linux VM, with two platform-specific skips. CI checks macOS/Linux and Python 3.10/3.13. Studio passed 60 graph assertions, TypeScript/build checks, and hosted routing validation.

Relay tests cover one-use pairing, scoped tokens, approved-root and symlink boundaries, denied credential mutations, duplicate and interrupted dispatch, expired requests, worker/cloud restart journals, offline evidence, replayed events, and network retry versus revocation. The complete fake-provider build verifies independent review, checks, and integration with staged/untracked preservation. A revocation regression explicitly prevents PermissionError from being swallowed by the network-error handler.

A disconnected worker continues already authorized work. Revocation is observed after reconnection. Machines must remain awake with the worker process running; pairing does not install automatic boot. The hosted service is a private operator workspace, not a multi-tenant product.
