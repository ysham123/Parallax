const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const root = path.resolve(__dirname, "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "parallax-hosted-"));
(async () => {
  try {
    execFileSync(
      process.execPath,
      [
        path.join(root, "studio/node_modules/typescript/lib/tsc.js"),
        "src/hosted-link.ts",
        "--target",
        "ES2022",
        "--module",
        "CommonJS",
        "--outDir",
        temp,
      ],
      { cwd: path.join(root, "studio"), stdio: "inherit" },
    );
    const { localStudioUrl } = require(path.join(temp, "hosted-link.js"));
    const local = "http://127.0.0.1:61968/?token=test-key&workspace=%2Fproject";
    assert.equal(localStudioUrl("  " + local + "  "), local);
    assert.equal(
      localStudioUrl("http://localhost:8765/?token=key"),
      "http://localhost:8765/?token=key",
    );
    for (const value of [
      "javascript:alert(1)",
      "https://evil.example/?token=key",
      "http://127.0.0.1.evil.example/?token=key",
      "http://user:pass@localhost/?token=key",
      "http://localhost/",
      "http://localhost/api/?token=key",
      "http://localhost/?token=key#fragment",
      "http://localhost/?token=a&token=b",
    ])
      assert.throws(() => localStudioUrl(value));
    const { outputConfig, runtimeOrigin } = await import(
      pathToFileURL(path.join(root, "scripts/vercel_config.mjs"))
    );
    const hosted = outputConfig();
    assert.equal(hosted.version, 3);
    assert.equal(
      hosted.routes.find((r) => r.src?.startsWith("/api")).dest,
      "/runtime-unavailable.json",
    );
    const cloud = outputConfig("https://runtime.example.com/");
    assert.equal(
      cloud.routes.find((r) => r.src?.startsWith("/api")).dest,
      "https://runtime.example.com/api/$1",
    );
    assert.equal(
      cloud.routes.find((r) => r.src?.startsWith("/api")).headers[
        "Cache-Control"
      ],
      "no-store",
    );
    assert.equal(cloud.routes.at(-1).dest, "/index.html");
    assert.equal(
      cloud.routes.find((r) => r.src === "/assets/.*" && r.status).status,
      404,
    );
    for (const origin of [
      "http://runtime.example.com",
      "https://key@runtime.example.com",
      "https://runtime.example.com/path",
      "https://runtime.example.com/?token=secret",
      "https://localhost",
    ])
      assert.throws(() => runtimeOrigin(origin));
    console.log("Hosted URL validation and Vercel routing checks passed.");
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
