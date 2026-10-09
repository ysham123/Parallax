# Parallax Team

Run coding reviews and verified builds on machines you connect to your Parallax account. This package contains one remote HTTPS MCP connection and an onboarding skill. It does not install or execute a local MCP server.

Connect your account, open hosted Studio, and pair a worker on your own machine. Approve project directories and sign in to your chosen providers there. Reviews and builds consume those providers' quota. Personal accounts cannot execute code on the hosted runtime. Builds require an independent provider and the existing verification gates; applying a candidate requires the requested integration setting.

The remote tools return machine and project names, run status, bounded summaries and check results. They omit raw patches, logs, prompts, credentials and provider session records. Requested pairing codes are temporary credentials. Revoke app access in Studio's Connected apps page. Existing runs continue until stopped.

The package's linked privacy policy, terms and support page describe the hosted data flow. This source directory also contains proposed review cases. Passing local tests does not establish that the live service, OAuth configuration, reviewer credentials or demo recording are ready for submission.
