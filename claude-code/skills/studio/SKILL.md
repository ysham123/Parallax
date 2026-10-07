---
name: studio
description: Open Parallax Studio for this project.
disable-model-invocation: true
---

Call `parallax_studio` with the repository root as the workspace and give the user the returned link to open in their browser. The link carries a local access token for this machine's Studio, so share it only with the user. If the Parallax tools are unavailable, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parallax.py" studio --workspace <repository root>` and share the URL it prints.
