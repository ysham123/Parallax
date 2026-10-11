import { REPOSITORY } from "./session";

// Public manifests verified at this immutable revision on October 10, 2026.
// The development preview has a separate package and installation guide.
export const PUBLIC_RELEASE = {
  version: "1.3.0",
  ref: "a5b0ccf84cee50ff0b9c0d69df522aaf1ed4e2ee",
  claudePlugin: "parallax@parallax",
  claudeStudio: "/parallax:studio",
  claudeReview: "/parallax:review",
  claudeBuild: "/parallax:build",
} as const;

export const CLAUDE_INSTALL = `/plugin marketplace add ysham123/Parallax\n/plugin install ${PUBLIC_RELEASE.claudePlugin}`;
export const CODEX_INSTALL = "codex plugin marketplace add ysham123/Parallax\ncodex plugin add codex-claude-team@codex-claude-team";
export const SOURCE_INSTALL = `git clone ${REPOSITORY}.git\ncd Parallax\ngit checkout --detach ${PUBLIC_RELEASE.ref}\npython3 scripts/parallax.py doctor`;
export const SOURCE_DOWNLOAD = `${REPOSITORY}/archive/${PUBLIC_RELEASE.ref}.zip`;

// Guides for the reviewed preview baseline, independently of public downloads.
const PREVIEW_GUIDE_REF = "19fe0806ffd18c08f328bbecee963135ad50198e";
export const PREVIEW_GUIDES = {
  setup: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/docs/FIRST-TASK.md`,
  modernization: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/examples/legacy-modernization/README.md`,
  contract: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/examples/legacy-modernization/CONTRACT.md`,
} as const;
