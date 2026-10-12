# Safe find and replace in the actual Excalidraw editor

Implement this feature in the pinned Excalidraw monorepo, using its existing SearchMenu, scene mutation, text-layout and history mechanisms.

## User experience

Open the existing canvas search with its normal shortcut. Keep match previews and occurrence navigation. Add a visible, accessibly named **Replace with** field that supports multiline text, and **Replace** / **Replace all** buttons. Replace changes only the focused eligible occurrence; Replace all changes all eligible matches from the current query once. Communicate skipped protected results clearly. Keep the controls compact and consistent with Excalidraw, including dark mode and keyboard focus.

## Required behavior

- Preserve existing case-insensitive literal search and its query trimming. Regular-expression characters are literal. Replacement text is literal, including `$&`, `$1`, `$$`, backslashes, Unicode and newlines. An empty replacement deliberately deletes matched text.
- Include text and explicitly named editable frames. Implicit default frame labels remain searchable, but replacement must not materialize a new frame name.
- Never alter a locked element or text bound to a locked container. Recheck current locks and current scene content when an action runs.
- Preserve text element IDs, originalText/display text consistency, container/arrow bindings, other elements, ordering and grouping. Recalculate text geometry through established editor APIs; a growing bound label must remain correctly laid out.
- Each Replace all is exactly one undoable edit, including text geometry and frame names. One undo restores the entire previous scene content and one redo restores the resulting content.
- Never act on stale query offsets. Query/scene changes while results refresh must recompute or disable safely.
- Empty/no-match/protected-only searches are non-mutating. Generated matches are not recursively replaced. Search remains available in view mode; replacement does not.
- Use app.ownerDocument / app.ownerWindow or node ownership for any new browser APIs, per the repository's AGENTS.md.

## Verification and implementation boundaries

The independent acceptance suite is frozen outside the editable checkout and supplied as immutable check arguments. The original test harness, configuration, manifests, lockfile and existing tests are hash-checked. Do not change those existing inputs, skip checks, update snapshots, add dependencies, access credentials, run external services, or change production deployment files. New focused tests may be added without weakening existing tests. All configured checks remain required even where the baseline fails because this feature is absent.

Use the existing native tools within their allowed scope. Do not delegate recursively or request unavailable tools. The coordinator may divide the work into coherent implementation and test tasks, but must keep the complete scene/history behavior consistent. The separate reviewing provider must inspect the combined candidate against these requirements and the actual check output. Report unresolved uncertainty honestly.

This is local experimental work only. Return a reviewed candidate for explicit human approval. Do not push, publish, merge or deploy.
