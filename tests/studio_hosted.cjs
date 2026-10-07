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
        "src/session.ts",
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
    const session = require(path.join(temp, "session.js"));
    assert.equal(session.signInError("?auth_error=denied"), "denied");
    for (const value of ["", "?auth_error=", "?auth_error=<script>", "?auth_error=__proto__", "?other=denied"])
      assert.equal(session.signInError(value), null);
    assert.match(session.signInErrorMessage("unknown"), /did not confirm/);
    assert.match(session.signInErrorMessage("__proto__"), /did not confirm/);
    assert.match(session.signInErrorMessage("toString"), /did not confirm/);
    assert.notEqual(session.executorKey("a"), session.executorKey("b"));
    const machines = [
      { id: "m1", name: "One", online: false, platform: "darwin", workspaces: ["/p"], last_seen: 0 },
      { id: "m2", name: "Two", online: true, platform: "linux", workspaces: ["/q"], last_seen: 0 },
    ];
    // Personal workspaces never select the hosted runtime, even from a stale or tampered choice.
    assert.equal(session.chooseMachine([], "railway", false), null);
    assert.equal(session.chooseMachine(machines, "railway", false), "m2");
    assert.equal(session.chooseMachine(machines, "m1", false), "m1");
    assert.equal(session.chooseMachine(machines, "someone-elses-machine", false), "m2");
    assert.equal(session.chooseMachine([machines[0]], null, false), "m1");
    assert.equal(session.chooseMachine([], null, true), "railway");
    assert.equal(session.chooseMachine(machines, "railway", true), "railway");
    // The operator prefers a connected machine, then the hosted runtime, before an offline machine.
    assert.equal(session.chooseMachine(machines, null, true), "m2");
    assert.equal(session.chooseMachine([machines[0]], null, true), "railway");
    const commands = session.workerCommands("https://studio.example.com");
    assert.match(commands.start, /--url https:\/\/studio\.example\.com /);
    assert.match(commands.install, /github\.com\/ysham123\/Parallax\.git/);
    assert.doesNotMatch(commands.start + commands.install, /token|code|key/i);
    const stored = new Map([
      ["parallax-executor:w1", "m1"],
      ["parallax-executor:w2", "m2"],
      ["parallax-executor", "legacy"],
      ["parallax-theme", "light"],
    ]);
    global.window = {
      localStorage: {
        get length() { return stored.size; },
        key: (index) => [...stored.keys()][index] ?? null,
        getItem: (key) => stored.get(key) ?? null,
        setItem: (key, value) => stored.set(key, String(value)),
        removeItem: (key) => stored.delete(key),
      },
    };
    session.writeStored(session.executorKey("w3"), "m3");
    assert.equal(session.readStored(session.executorKey("w3")), "m3");
    assert.equal(session.storedMachine("owner"), "legacy");
    assert.equal(session.storedMachine("personal-workspace"), null);
    session.forgetMachines();
    assert.deepEqual([...stored.keys()], ["parallax-theme"]);
    global.window = { get localStorage() { throw new Error("blocked"); } };
    assert.equal(session.readStored("x"), null);
    session.writeStored("x", "y");
    session.forgetMachines();
    delete global.window;
    assert.equal(
      session.initials({ account: { login: "ada", name: "Ada Lovelace", avatar_url: null } }),
      "AL",
    );
    assert.equal(session.initials({ account: null }), "OP");
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
    console.log("Hosted URL validation, session helpers, and Vercel routing checks passed.");
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
