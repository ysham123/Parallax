import { REPOSITORY } from "./session";

// Public main and marketplace manifests checked on October 14, 2026.
// This is a development preview; public source availability is not pilot acceptance.
export const PUBLIC_RELEASE = {
  version: "1.4.0",
  ref: "63c919e5893b260d61cd0589e8988ed4fd7ea6bb",
  claudePlugin: "parallax-team@parallax",
  claudeStudio: "/parallax-team:studio",
  claudeReview: "/parallax-team:review",
  claudeBuild: "/parallax-team:build",
} as const;

export const CLAUDE_INSTALL = `/plugin marketplace add ysham123/Parallax\n/plugin install ${PUBLIC_RELEASE.claudePlugin}`;
export const CODEX_INSTALL = "codex plugin marketplace add ysham123/Parallax\ncodex plugin add codex-claude-team@codex-claude-team";
export const SOURCE_INSTALL = `git clone ${REPOSITORY}.git\ncd Parallax\ngit checkout --detach ${PUBLIC_RELEASE.ref}\npython3 scripts/parallax.py doctor`;
export const SOURCE_DOWNLOAD = `${REPOSITORY}/archive/${PUBLIC_RELEASE.ref}.zip`;

// Setup follows current docs; example contracts stay pinned to the preview source.
const PREVIEW_GUIDE_REF = PUBLIC_RELEASE.ref;
export const PREVIEW_GUIDES = {
  setup: `${REPOSITORY}/blob/main/docs/FIRST-TASK.md`,
  windows: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/docs/WINDOWS.md`,
  modernization: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/examples/legacy-modernization/README.md`,
  contract: `${REPOSITORY}/blob/${PREVIEW_GUIDE_REF}/examples/legacy-modernization/CONTRACT.md`,
} as const;
