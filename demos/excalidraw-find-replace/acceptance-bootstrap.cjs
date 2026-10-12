// This entire script and the acceptance source are frozen into the configured
// check argv. The checked repository cannot replace them by editing a file.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

const [encoded, expectedHash, encodedHarness] = process.argv.slice(1);
const source = Buffer.from(encoded || "", "base64");
if (!expectedHash || crypto.createHash("sha256").update(source).digest("hex") !== expectedHash) {
  throw new Error("Independent acceptance input failed its integrity check");
}
const project = process.cwd();
if (encodedHarness) {
  const protectedFiles = JSON.parse(require("node:zlib").inflateSync(Buffer.from(encodedHarness, "base64")));
  for (const [relative, expected] of Object.entries(protectedFiles)) {
    const absolute = path.resolve(project, relative);
    if (!absolute.startsWith(project + path.sep) || fs.lstatSync(absolute).isSymbolicLink()) {
      throw new Error("Invalid protected harness path: " + relative);
    }
    const actual = crypto.createHash("sha256").update(fs.readFileSync(absolute)).digest("hex");
    if (actual !== expected) throw new Error("Protected upstream test or configuration changed: " + relative);
  }
  console.log("Verified " + Object.keys(protectedFiles).length + " protected upstream test/configuration inputs");
}
const scratch = fs.realpathSync(fs.mkdtempSync(path.join(process.env.TMPDIR || require("node:os").tmpdir(), "parallax-acceptance-")));
const testFile = path.join(scratch, "find-replace.acceptance.test.tsx");
const configFile = path.join(scratch, "vitest.config.mts");
const reportFile = path.join(scratch, "results.json");
fs.symlinkSync(path.join(project, "node_modules"), path.join(scratch, "node_modules"), "dir");
fs.writeFileSync(testFile, source);
fs.writeFileSync(configFile, `
import base from ${JSON.stringify(path.join(project, "vitest.config.mts"))};
export default {
  ...base,
  root: ${JSON.stringify(scratch)},
  envDir: ${JSON.stringify(scratch)},
  resolve: {
    ...base.resolve,
    alias: [
      {find: /^@showcase\\/tests\\/(.*)/, replacement: ${JSON.stringify(path.join(project, "packages/excalidraw/tests/$1"))}},
      ...(base.resolve?.alias || []),
    ],
  },
  test: {
    ...base.test,
    setupFiles: [${JSON.stringify(path.join(project, "setupTests.ts"))}],
    include: ["find-replace.acceptance.test.tsx"],
    exclude: [],
    maxWorkers: 1,
    minWorkers: 1,
    reporters: ["default", "json"],
    outputFile: {json: ${JSON.stringify(reportFile)}},
    watch: false,
  },
};
`);
const result = spawnSync(process.execPath, [path.join(project, "node_modules/vitest/vitest.mjs"), "run", "--config", configFile], {
  cwd: project,
  env: { ...process.env, CI: "true" },
  encoding: "utf8",
  maxBuffer: 12 * 1024 * 1024,
  timeout: 240000,
});
process.stdout.write(result.stdout || "");
process.stderr.write(result.stderr || "");
if (result.error) throw result.error;
const report = JSON.parse(fs.readFileSync(reportFile, "utf8"));
const assertions = (report.testResults || []).flatMap((suite) => suite.assertionResults || []);
console.log(JSON.stringify({
  acceptance_sha256: expectedHash,
  total: assertions.length,
  passed: assertions.filter((test) => test.status === "passed").length,
  failed: assertions.filter((test) => test.status === "failed").length,
  skipped: assertions.filter((test) => !["passed", "failed"].includes(test.status)).length,
}));
if (assertions.length < 10 || assertions.some((test) => test.status !== "passed")) process.exit(1);
process.exit(result.status === 0 && report.success ? 0 : 1);
