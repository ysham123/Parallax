# Security

Report vulnerabilities privately through [GitHub's private vulnerability reporting](https://github.com/ysham123/Parallax/security/advisories/new). Please do not open public issues for security problems.

Useful reports name the affected version, the component (local runtime, Studio, hosted runtime, paired worker, or a plugin), and the steps to reproduce. Leave out real credentials, private prompts and project contents.

## Scope

- **Local runtime and Studio**: loopback binding, session handling, origin checks, workspace isolation, and anything that could let an agent write outside its owned files or skip the review and check gates.
- **Hosted Studio**: account and session handling, the workspace boundary between accounts, the sign-in flows (email, GitHub and Google through Supabase, and built-in GitHub), request and storage limits.
- **Paired workers**: the relay allowlist, approved-project resolution, and worker token scope.
- **Plugins**: the Codex and Claude Code plugin manifests, skills and MCP launcher.

Provider CLIs and APIs are maintained by their vendors; report issues in them to the vendor.
