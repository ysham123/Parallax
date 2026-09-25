# Contributing

Thanks for improving Codex Claude Team. Issues and focused pull requests are welcome.

1. Describe the behavior you want to change and why it matters to a Codex or Claude Code user.
2. Keep the skill instructions, README, and bridge behavior in sync when changing the workflow.
3. Run `python3 -m unittest discover -s tests -v` before opening a pull request.
4. Add a test when changing bridge behavior, especially permissions, process handling, or change detection.

Please avoid including private prompts, project files, credentials, or Claude session IDs in issues and test fixtures. For a security issue, use GitHub's private vulnerability reporting on this repository.
