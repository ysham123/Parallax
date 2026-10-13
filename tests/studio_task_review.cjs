const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "parallax-task-review-"));
let passed = 0;
const check = (name, fn) => { fn(); passed++; console.log("PASS", name); };
try {
  execFileSync(process.execPath, [
    path.join(root, "studio/node_modules/typescript/lib/tsc.js"),
    "src/task-review.ts", "src/diff-model.ts", "--target", "ES2022",
    "--module", "CommonJS", "--outDir", temp,
  ], { cwd: path.join(root, "studio"), stdio: "inherit" });
  const { parseDiff } = require(path.join(temp, "diff-model.js"));
  const { actorLabel, requestLabel, recordedTime, relationKind,
    normalizeFinding, locateFinding, taskTitle, workflowTitle } = require(path.join(temp, "task-review.js"));
  const directory = [{ account: "owner", name: "Owner", login: "owner-login" },
    { account: "reviewer", name: "", login: "Reviewer" }];
  check("Only an exact recorded requester/viewer match means your request", () => {
    assert.equal(requestLabel("owner", "owner"), "Your request");
    assert.equal(requestLabel("owner", "reviewer"), "Task request");
    assert.equal(requestLabel(undefined, undefined), "Task request");
    assert.equal(requestLabel("", ""), "Task request");
  });
  check("Display current authenticated member names and login fallbacks", () => {
    assert.equal(actorLabel("owner", directory, "reviewer"), "Owner");
    assert.equal(actorLabel("reviewer", directory), "Reviewer");
  });
  check("Missing records do not infer the viewer and unknown actors expose no directory name", () => {
    assert.equal(actorLabel(null, directory, "owner"), "Unrecorded human");
    assert.equal(actorLabel("removed-member-secret-email", directory, "owner"), "Recorded member");
    assert.equal(actorLabel("owner", [], "owner"), "You");
  });
  check("Dates use only recorded timestamps and invalid or missing ones remain explicit", () => {
    assert.equal(recordedTime(null), "Time unrecorded");
    assert.equal(recordedTime("not-a-date"), "Time unrecorded");
    assert.notEqual(recordedTime("2026-10-10T12:30:00Z"), "Time unrecorded");
  });
  check("Saved candidate revisions and current project followups use contract metadata", () => {
    assert.equal(relationKind({ schema_version: "2.0", parent_workflow_id: "p", revision: { parent: "p" } }), "revision");
    assert.equal(relationKind({ schema_version: "2.0", parent_workflow_id: "p" }), "fresh");
    assert.equal(relationKind({ parent_workflow_id: "p" }), "unknown");
    assert.equal(relationKind({ schema_version: "2.0", parent_workflow_id: "p", revision: { parent: "different" } }), "unknown");
    assert.equal(relationKind({ schema_version: "2.0" }), "unknown");
  });
  check("Compact provider finding fields preserve text and explicit severity", () => {
    assert.deepEqual(normalizeFinding({ title: "Edge case", severity: "high", explanation: "Wrong output", file: "src/a.ts", line: 11, end_line: 13 }), {
      title: "Edge case", severity: "high", severityClass: "urgent", body: "Wrong output", file: "src/a.ts", line: 11, endLine: 13,
    });
    assert.equal(normalizeFinding("plain provider finding", 2).body, "plain provider finding");
    assert.equal(normalizeFinding(null, 2).title, "Finding 3");
  });
  check("Structured code location and line range are retained", () => {
    const finding = normalizeFinding({ priority: "P2", code_location: { absolute_file_path: "/project/src/a.ts", line_range: { start: "11", end: "12" } } });
    assert.equal(finding.file, "/project/src/a.ts");
    assert.equal(finding.line, 11);
    assert.equal(finding.endLine, 12);
    assert.equal(finding.severityClass, "warning");
  });
  check("Untrusted HTML remains display text and unsafe severity never becomes a CSS class", () => {
    const input = '<img src=x onerror="steal()">';
    const finding = normalizeFinding({ title: input, body: input, severity: input, file: input, line: input });
    assert.equal(finding.title, input); assert.equal(finding.body, input);
    assert.equal(finding.severityClass, "info"); assert.equal(finding.line, undefined);
  });
  check("Invalid, negative, fractional and excessive line numbers cannot target a patch row", () => {
    for (const line of [0, -1, 1.5, "junk", Number.MAX_SAFE_INTEGER + 1, {}, true])
      assert.equal(normalizeFinding({ line }).line, undefined);
    assert.equal(normalizeFinding({ line: 10, end_line: 2 }).endLine, undefined);
  });
  const patch = [
    "diff --git a/src/a.ts b/src/a.ts", "--- a/src/a.ts", "+++ b/src/a.ts",
    "@@ -10,3 +10,4 @@", " same", "-old", "+new", "+extra", " end",
    "diff --git a/gone.txt b/gone.txt", "deleted file mode 100644", "--- a/gone.txt", "+++ /dev/null", "@@ -1 +0,0 @@", "-deleted",
    "diff --git a/image.png b/image.png", "Binary files a/image.png and b/image.png differ",
    "diff --git a/old.ts b/new.ts", "rename from old.ts", "rename to new.ts", "--- a/old.ts", "+++ b/new.ts", "@@ -2 +4 @@", "-before", "+after",
  ].join("\n");
  const files = parseDiff(patch);
  check("Finding lines target the candidate side of changed code", () => {
    const result = locateFinding(files, { file: "src/a.ts", line: 11 });
    assert.equal(result.path, "src/a.ts");
    assert.equal(files[0].lines[result.row].kind, "addition");
    assert.equal(result.notice, "");
  });
  check("Workspace-relative, absolute and Git-prefixed paths map only to recorded files", () => {
    for (const file of ["src/a.ts", "./src/a.ts", "a/src/a.ts", "/project/src/a.ts"])
      assert.equal(locateFinding(files, { file, line: 11 }, "/project").path, "src/a.ts");
    assert.equal(locateFinding(files, { file: "/other/src/a.ts", line: 11 }, "/project").path, undefined);
    assert.equal(locateFinding(files, { file: "../src/a.ts", line: 11 }, "/project").path, undefined);
  });
  check("Deleted findings show the original side with an explicit notice", () => {
    const result = locateFinding(files, { file: "gone.txt", line: 1 });
    assert.equal(files[1].lines[result.row].old, 1);
    assert.match(result.notice, /deleted.*original line/);
  });
  check("Renamed original paths target original lines, current paths target new lines", () => {
    const old = locateFinding(files, { file: "old.ts", line: 2 });
    const current = locateFinding(files, { file: "new.ts", line: 4 });
    assert.equal(old.path, "new.ts"); assert.equal(current.path, "new.ts");
    assert.equal(files[3].lines[old.row].old, 2);
    assert.equal(files[3].lines[current.row].next, 4);
    assert.match(old.notice, /renamed/);
  });
  check("Missing, binary, absent-line and out-of-hunk findings explain unavailable navigation", () => {
    assert.match(locateFinding(files, { file: "missing.ts", line: 1 }).notice, /not in the recorded/);
    assert.match(locateFinding(files, { file: "image.png", line: 1 }).notice, /binary/);
    assert.match(locateFinding(files, { file: "src/a.ts", line: 100 }).notice, /outside.*incomplete/);
    assert.match(locateFinding(files, { file: "src/a.ts" }).notice, /No line/);
    assert.match(locateFinding(files, { file: "" }).notice, /No file/);
  });
  check("Ambiguous old/new path matches do not guess a file", () => {
    assert.equal(locateFinding([files[0], { ...files[0], path: "other.ts" }], { file: "src/a.ts", line: 11 }).path, undefined);
  });
  check("Finding navigation opens the correct page of a long saved diff", () => {
    const long = parseDiff(["diff --git a/long.ts b/long.ts", "--- /dev/null", "+++ b/long.ts", "@@ -0,0 +1,900 @@", ...Array.from({ length: 900 }, (_, i) => "+row " + (i + 1))].join("\n"));
    const result = locateFinding(long, { file: "long.ts", line: 820 }, "", 400);
    assert.equal(result.page, 2); assert.equal(long[0].lines[result.row].next, 820);
    assert.ok(result.row >= 800 && result.row < 1200);
  });
  check("long-form requests show their first meaningful line as the title", () => {
    assert.equal(taskTitle("# Safe find and replace in the actual Excalidraw editor\n\nImplement this feature"), "Safe find and replace in the actual Excalidraw editor");
    assert.equal(taskTitle("\n\n  - **Fix   undo**\nmore"), "Fix undo");
    assert.equal(taskTitle("Fix addition"), "Fix addition");
    assert.equal(taskTitle("   \n#  \n"), "Untitled task");
    assert.equal(taskTitle(undefined), "Untitled task");
    const long = taskTitle("x".repeat(300));
    assert.equal(long.length, 120); assert.ok(long.endsWith("…"));
  });
  check("a revision keeps its task's goal as the title", () => {
    assert.equal(workflowTitle({ title: "Fix the plural wording in the status", original_goal: "# Safe find and replace\n\nDetails", revision: { lineage: "a" } }), "Safe find and replace");
    assert.equal(workflowTitle({ title: "# Plain task\nmore", original_goal: "ignored without a revision" }), "Plain task");
    assert.equal(workflowTitle({ title: "Correction only", revision: { lineage: "a" } }), "Correction only");
  });
  console.log(`Task review: ${passed} meaningful identity, lineage and finding navigation checks passed.`);
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
