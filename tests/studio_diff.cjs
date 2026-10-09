const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "parallax-diff-"));
try {
  execFileSync(
    process.execPath,
    [
      path.join(root, "studio/node_modules/typescript/lib/tsc.js"),
      "src/diff-model.ts",
      "--target",
      "ES2022",
      "--module",
      "CommonJS",
      "--outDir",
      temp,
    ],
    { cwd: path.join(root, "studio"), stdio: "inherit" },
  );
  const { parseDiff } = require(path.join(temp, "diff-model.js"));
  const patch = [
    "diff --git a/src/a.ts b/src/a.ts",
    "index 111..222 100644",
    "--- a/src/a.ts",
    "+++ b/src/a.ts",
    "@@ -10,3 +10,4 @@ function f()",
    " same",
    "-old",
    "+new",
    "+",
    " end",
    "\\ No newline at end of file",
    "@@ -100 +101 @@",
    "-before",
    "+after",
    "diff --git a/old.txt b/old.txt",
    "deleted file mode 100644",
    "--- a/old.txt",
    "+++ /dev/null",
    "@@ -1 +0,0 @@",
    "-deleted",
    "diff --git a/image.png b/image.png",
    "Binary files a/image.png and b/image.png differ",
    "diff --git a/old name.txt b/a/new name.txt",
    "similarity index 100%",
    "rename from old name.txt",
    "rename to a/new name.txt",
    'diff --git "a/caf\\303\\251.txt" "b/caf\\303\\251.txt"',
    '--- "a/caf\\303\\251.txt"',
    '+++ "b/caf\\303\\251.txt"',
    "@@ -1 +1 @@",
    "-old",
    "+new",
    "",
  ].join("\n");
  const files = parseDiff(patch);
  assert.equal(files.length, 5);
  assert.deepEqual(
    files.map((f) => f.path),
    ["src/a.ts", "old.txt", "image.png", "a/new name.txt", "café.txt"],
  );
  assert.equal(files[3].previousPath, "old name.txt");
  assert.equal(files[0].added, 3);
  assert.equal(files[0].removed, 2);
  assert.deepEqual(
    files[0].lines.filter((l) => l.kind === "addition").map((l) => l.next),
    [11, 12, 101],
  );
  assert.deepEqual(
    files[0].lines.filter((l) => l.kind === "deletion").map((l) => l.old),
    [11, 100],
  );
  assert.deepEqual(
    files[0].lines
      .filter((l) => l.kind === "context")
      .map((l) => [l.old, l.next]),
    [
      [10, 10],
      [12, 13],
    ],
  );
  assert.equal(files[1].removed, 1);
  assert.equal(files[2].added, 0);
  assert.ok(files[2].lines.some((l) => l.text.startsWith("Binary files")));
  assert.equal(
    files
      .flatMap((f) => f.lines)
      .map((l) => l.text)
      .join("\n") + "\n",
    patch,
    "Patch text must survive parsing without missing metadata or newline markers",
  );
  assert.deepEqual(parseDiff(""), []);
  assert.equal(
    parseDiff(
      "diff --git a/new b/new\n--- /dev/null\n+++ b/new\n@@ -0,0 +1 @@\n+new\n",
    )[0].lines.at(-1).next,
    1,
  );
  assert.equal(
    parseDiff(
      "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n---content\n+++content\n",
    )[0].added,
    1,
    "Header-like source text inside a hunk is a source line",
  );
  console.log(
    "Diff model: line numbers, multiple hunks, deletions, binary files, renames, quoted UTF-8 paths, and exact text preservation passed.",
  );
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
