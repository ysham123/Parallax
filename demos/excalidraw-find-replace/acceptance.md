# Excalidraw find-and-replace acceptance contract

This is a real repository task, pinned to upstream Excalidraw commit
`2df993fb397dd6d64625908c9c10337727617f6f`. It extends the existing canvas
SearchMenu. The task is complete only when the accepted candidate passes the
protected tests and a real browser inspection. Passing checks does not establish
that Parallax improves productivity or that the feature is ready for upstream
release.

## Required behavior

1. Open canvas search with its existing Ctrl/Cmd+F entry. Keep ordinary search,
   occurrence previews, result counts, focus navigation and Enter cycling. The
   query remains case-insensitive and literal, including regexp metacharacters.
   Preserve the existing trimming of the query's outer whitespace.
2. In SearchMenu, provide an accessible field named **Replace with**, a button
   named **Replace**, and a button named **Replace all**. A multiline replacement
   must be possible. The replacement is a literal string; `$&`, `$1`, `$$`,
   backslashes and Unicode have no substitution meaning. The field may be empty
   to delete matches. No replacement happens merely by typing, searching,
   navigating, opening or closing the panel.
3. Replace changes only the focused occurrence, including the selected offset
   when an element contains several occurrences. Replace all changes every
   editable occurrence that existed for the current query at the start of that
   action. If replacement contains the query, it runs once, without recursively
   replacing generated text. Refresh previews, counts and focus after an edit.
4. Edit canvas text using its original text, not display wrapping. Recompute
   display wrapping, measurements and bound-text positions using the app's normal
   scene semantics. Preserve element identities, text/container relationships,
   arrow label relationships, unrelated elements, grouping and frame references.
   Bound text must fit its container; grow the container when needed and preserve
   valid geometry. Multiline originals and replacement, wrapped text, non-ASCII
   characters and supplementary Unicode characters must remain intact.
5. Include editable **explicit** frame names in replacement, matching existing
   search results. Implicit default frame names remain searchable but are never
   materialized or changed by replacement. Locked frames remain unchanged.
6. A locked text element is not editable. A label bound to a locked container is
   also not editable, even if the label itself is unlocked. Keep these elements,
   their containers and their geometry unchanged. Communicate excluded results
   visibly. When the focused result cannot be edited, disable Replace; when no
   editable match remains, disable Replace all. Search remains available.
7. Empty or no-match queries perform no scene changes and create no undo entry.
   View/read-only mode never permits replacement, including when enabled after
   opening the panel. It may hide or disable editing controls.
8. Each Replace is one undoable edit. Each Replace all is **one** undoable edit
   across all text, geometry changes and frame names. One normal canvas Undo
   restores the entire preceding scene; Redo restores the entire replacement.
   No partial per-element undo steps or incidental no-op history entries.
9. Before modifying anything, validate the **current** query, scene text,
   element existence and editability. A rapid query change must never apply an
   old query. A scene edit, deletion or late lock must never use an old object or
   offset. Either recompute safely at invocation, or disable/no-op while current
   results are pending and allow an explicit action once ready. Preserve external
   scene edits and locks.

Implementation is open: use the existing app actions, scene mutation, history,
text measurement and translation patterns. These requirements do not prescribe
new helper names, CSS selectors, state structure or an algorithm. Existing test
harnesses, baseline tests, configuration and dependency versions are protected
inputs, not a way to make this feature pass.

## Protected automated checks

`acceptance/parallax-find-replace.acceptance.test.tsx` contains 16 tests which
render the real Excalidraw component, operate SearchMenu through DOM controls,
and inspect the resulting real scene/history. It includes an ordinary-search
test which should pass before implementation; feature tests should fail before
implementation. It does not decide success from source text, invented functions,
agent summaries or mocked replacement behavior.

The check-owned runner lives in `acceptance-bootstrap.cjs`. Root freezes its
script, base64 test content, SHA-256 and protected upstream integrity manifest in
the configured check's argument vector. It writes its test/config/report only
under the check's `TMPDIR`, with aliases pointing to the checked candidate. It
must not copy tests into the agent-editable candidate. The result requires at
least 10 collected test cases, every collected case passed, and a successful
Vitest process/report. For this frozen contract the expected count is **16**.
Report the hash and actual passed/failed/skipped counts beside the run result.

In addition to the external contract, run the original upstream search suite,
the repository TypeScript check and the original test suite under their existing
configuration. Protect the original tests, helpers, setup, manifests, lockfile
and test configuration from candidate changes. A changed harness is a check
failure, not an accepted feature implementation.

Local harness proof can call Node directly with the frozen script and test
arguments; the Parallax configured check uses its actual sandbox/private-env
runner. The demonstration must preserve baseline test failures, provider
failures/timeouts, candidate checks and independent review. A failed attempt is
evidence to report, not a reason to reset the consumed budget silently.

## Real browser acceptance

Use a fresh browser context with the candidate's actual development/build app.
Import `acceptance/browser-scene.excalidraw` into its disposable canvas. This
fixture is external to the candidate, has no remote collaboration or personal
content, and includes editable text, a bound label, a locked text element, a
label in a locked container, an explicit frame name and an implicit frame.

Inspect at desktop and narrow/mobile viewport:

- Ctrl/Cmd+F focuses the existing search field. Search `target`; inspect the
  match previews and observe excluded locked results before changing anything.
- Set Replace with to `reviewed`. Replace one selected text occurrence; verify
  the other occurrences remain. Undo once and redo once using normal app UI.
- Replace all with a longer multiline label. Verify both editable text and the
  explicit frame name change, locked text and the locked bound label do not,
  bound text fits the grown container, and the implicit frame still has its
  default name. Undo once restores every edit and geometry; redo restores them.
- Search the literal `[a].*+$?^(){}|\` sample and replace with `$&-$1-$$-\-🧭`;
  inspect literal output. Search `猫🐈` and insert a multiline Unicode replacement.
- Clear the query, search a missing term, and enable view mode. Confirm replacement
  is unavailable and searching is still usable. Type a new query immediately
  before clicking Replace all; never observe an edit to the previous query.
- Inspect labels, focus visibility, disabled explanations, panel scrolling,
  keyboard navigation and touchable controls. No clipping or obscured canvas
  actions. Search count/focus stays coherent after edits and history actions.

Capture before/after and undo screenshots plus the actual app URL/build identity.
Record any browser limitations separately. A rendered fixture screenshot alone
is not completion; the feature must have been exercised in the accepted candidate.

## Evidence and limits

Save the pinned base, task text, protected check hash, configured commands,
providers/models when available, native run IDs, attempt failures/timeouts,
check counts, independent review and candidate digest. Keep the untouched source
clone clean. Do not merge, publish, deploy, or apply to unrelated developer work.
Human approval and local delivery are separate subsequent actions. GitHub
publication, genuine team-account approval, staging and comparative productivity
results remain unverified unless actually performed and recorded.
