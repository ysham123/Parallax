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
        "src/oauth.ts",
        "src/workflow-state.ts",
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
    const workflows = require(path.join(temp, "workflow-state.js"));
    const candidate = {digest: "a".repeat(64), gates: [{status:"passed"},{status:"passed"},{status:"passed"}]};
    assert.equal(workflows.canApprove("awaiting_approval", candidate), true);
    for (const state of ["queued", "preparing", "interrupted", "needs_attention", "applying", "applied", "rejected", "cancelled"])
      assert.equal(workflows.canApprove(state, candidate), false);
    assert.equal(workflows.canApprove("awaiting_approval", {...candidate, gates:[{status:"passed"}]}), false);
    assert.equal(workflows.canApprove("awaiting_approval", {...candidate, gates:[{status:"passed"},{status:"unknown"},{status:"passed"}]}), false);
    assert.equal(workflows.canApprove("awaiting_approval", candidate, {action:"approve"}), false);
    assert.equal(workflows.workflowGroup("interrupted"), "attention");
    assert.equal(workflows.workflowGroup("awaiting_approval"), "approval");
    assert.ok(workflows.workflowStep("rejected") < 2, "Declining never marks application as complete");
    assert.ok(workflows.workflowStep("cancelled") < 2, "Stopping never marks application as complete");
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
    const oauth = require(path.join(temp, "oauth.js"));
    const authId = "b783d119-0110-42c0-8c17-1ecc6a8dca8d";
    assert.equal(oauth.consentIdentifier(`?authorization_id=${authId}`), authId);
    for (const search of ["", "?authorization_id=../", `?authorization_id=${authId}&authorization_id=${authId}`])
      assert.equal(oauth.consentIdentifier(search), null);
    for (const url of ["https://chatgpt.com/callback?code=abc", "http://127.0.0.1:1455/callback?code=abc"])
      assert.equal(oauth.oauthDestination(url), url);
    for (const url of ["javascript:alert(1)", "http://evil.example/", "https://user:pass@app.example/", "https://app.example/#token", "https://app.example/\\evil", " https://app.example/"])
      assert.throws(() => oauth.oauthDestination(url));
    assert.equal(session.signInError("?auth_error=denied"), "denied");
    for (const code of ["credentials", "unconfirmed", "weak_password", "invalid_email", "link_expired"])
      assert.equal(session.signInError(`?auth_error=${code}`), code);
    assert.match(session.signInErrorMessage("credentials"), /don't match/);
    assert.deepEqual(session.signInMethods(null), []);
    assert.deepEqual(session.signInMethods({ github: true, signup: "open" }), ["github"]);
    assert.deepEqual(session.signInMethods({ github: false, signup: "open" }), []);
    assert.deepEqual(
      session.signInMethods({ github: true, identity: "supabase", providers: ["email", "google"], signup: "open" }),
      ["email", "google"],
    );
    const member = { login: "ada", name: "Ada", avatar_url: null, email: "ada@example.com", provider: "email" };
    assert.equal(session.accountName(member), "ada@example.com");
    assert.equal(session.accountName({ ...member, provider: "github", login: "octocat" }), "@octocat");
    assert.equal(session.accountName({ ...member, email: null }), "@ada");
    assert.equal(session.deletionConfirmation(member), "ada@example.com");
    assert.equal(session.deletionConfirmation({ ...member, email: null }), "ada");
    for (const value of ["", "?auth_error=", "?auth_error=<script>", "?auth_error=__proto__", "?other=denied"])
      assert.equal(session.signInError(value), null);
    assert.match(session.signInErrorMessage("unknown"), /could not be confirmed/);
    assert.match(session.signInErrorMessage("__proto__"), /could not be confirmed/);
    assert.match(session.signInErrorMessage("toString"), /could not be confirmed/);
    assert.equal(session.legalPage("/privacy"), "privacy");
    assert.equal(session.legalPage("/terms/"), "terms");
    assert.equal(session.legalPage("/support"), "support");
    for (const value of ["/", "/privacy/extra", "/Privacy", "/login", "/toString", "/__proto__"])
      assert.equal(session.legalPage(value), null);
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
    const discovery = cloud.routes.find(r => r.src?.includes("well-known"));
    assert.equal(discovery.dest, "https://runtime.example.com/.well-known/$1");
    assert.equal(discovery.headers["Cache-Control"], "no-store");
    for (const route of ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/api/mcp", "/.well-known/openai-apps-challenge"])
      assert.match(route, new RegExp(`^${discovery.src}$`));
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
