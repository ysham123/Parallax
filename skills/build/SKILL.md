---
name: build
description: Have a Parallax team implement a task with independent review and real project checks before integration.
argument-hint: "<task>"
disable-model-invocation: true
---

Run a Parallax **Build** for this task, following the parallax skill.

Task: $ARGUMENTS

If no task was given, ask for one. Assess the project first and confirm the check commands that will gate integration. Then start the run, follow it to a settled state, and report the verified result or what needs attention. Do not edit the project yourself while the run is active.
