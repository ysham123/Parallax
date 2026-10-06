#!/usr/bin/env node
// Reproduce graph-inspection checks against the current source.
// Run: npm test from studio/ after npm ci.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { execFileSync } = require("node:child_process");

const studio = path.resolve(__dirname, "../studio");
const compiled = fs.mkdtempSync(
  path.join(os.tmpdir(), "parallax-graph-inspection-"),
);
let passed = 0;
function check(name, assertion) {
  try {
    assertion();
    passed += 1;
  } catch (error) {
    error.message = `${name}: ${error.message}`;
    throw error;
  }
}

try {
  execFileSync(
    process.execPath,
    [
      path.join(studio, "node_modules/typescript/lib/tsc.js"),
      "src/run-inspection.ts",
      "src/types.ts",
      "--target",
      "ES2022",
      "--module",
      "CommonJS",
      "--moduleResolution",
      "Node",
      "--skipLibCheck",
      "--outDir",
      compiled,
    ],
    { cwd: studio, stdio: "inherit" },
  );
  const {
    getRunAgents,
    agentKey,
    eventsForSelection,
    graphTone,
    describeRunEvent,
  } = require(path.join(compiled, "run-inspection.js"));
  const member = {
    provider: "codex",
    model: "model-a",
    effort: "high",
    role: "implementer",
  };
  const coordinator = { ...member, role: "generalist" };
  const run = {
    run_id: "test",
    status: "running",
    spec: { coordinator, team: [member], mode: "build" },
    tasks: [
      {
        id: "checks",
        title: "Fix test",
        provider: "codex",
        status: "running",
        active_attempt: { state: "implemented", participant: member },
      },
    ],
    sessions: [
      {
        provider: "codex",
        transport: "cli",
        mode: "coordinate",
        task_id: "coordinator",
        effective_settings: { model: "actual-coordinator" },
      },
      {
        provider: "codex",
        transport: "cli",
        mode: "edit",
        task_id: "checks",
        effective_settings: { model: "actual-worker" },
      },
    ],
    reviews: [],
    checks: [],
    artifacts: {},
  };
  const events = [
    {
      run_id: "test",
      sequence: 1,
      kind: "provider",
      task_id: "coordinator",
      data: { provider: "codex", transport: "cli", mode: "coordinate" },
      timestamp: "2026-10-06T00:00:00Z",
    },
    {
      run_id: "test",
      sequence: 2,
      kind: "provider",
      task_id: "checks",
      data: { provider: "codex", transport: "cli", mode: "edit" },
      timestamp: "2026-10-06T00:00:01Z",
    },
    {
      run_id: "test",
      sequence: 3,
      kind: "check",
      data: { name: "test", ok: true },
      timestamp: "2026-10-06T00:00:02Z",
    },
  ];
  const agents = getRunAgents(run, events);
  check("dedicated coordinator and worker slots", () =>
    assert.equal(agents.length, 2),
  );
  check("stable distinct connection keys", () =>
    assert.notEqual(agentKey(coordinator, true), agentKey(member)),
  );
  check("coordinator does not own worker task", () =>
    assert.equal(agents[0].tasks.length, 0),
  );
  check("worker owns scoped task", () =>
    assert.equal(agents[1].tasks.length, 1),
  );
  check("coordinator effective settings", () =>
    assert.equal(agents[0].effectiveSettings.model, "actual-coordinator"),
  );
  check("worker effective settings", () =>
    assert.equal(agents[1].effectiveSettings.model, "actual-worker"),
  );
  check("implemented attempt awaits review", () =>
    assert.equal(agents[1].state, "awaiting review"),
  );
  check("coordinator observations scoped", () =>
    assert.deepEqual(
      eventsForSelection(run, events, agents[0].id).map((e) => e.sequence),
      [1],
    ),
  );
  check("task named checks remains inspectable", () =>
    assert.deepEqual(
      eventsForSelection(run, events, "checks").map((e) => e.sequence),
      [2],
    ),
  );
  check("aggregate checks use reserved selection", () =>
    assert.deepEqual(
      eventsForSelection(run, events, "evidence:checks").map((e) => e.sequence),
      [3],
    ),
  );
  check("run selection returns all events", () =>
    assert.deepEqual(
      eventsForSelection(run, events, "run").map((e) => e.sequence),
      [1, 2, 3],
    ),
  );
  check("interrupted attempt is not live", () =>
    assert.equal(
      getRunAgents({ ...run, status: "interrupted" }, events)[1].state,
      "interrupted",
    ),
  );
  check("destination attention preserves finished worker", () =>
    assert.equal(
      getRunAgents(
        {
          ...run,
          status: "needs_attention",
          tasks: [{ ...run.tasks[0], status: "completed" }],
        },
        events,
      )[1].state,
      "assignments complete",
    ),
  );
  check("Integrated state tone", () =>
    assert.equal(graphTone("Integrated"), "good"),
  );
  check("Verified candidate ready state tone", () =>
    assert.equal(graphTone("Verified candidate ready"), "good"),
  );
  check("Needs attention state tone", () =>
    assert.equal(graphTone("Needs attention"), "bad"),
  );
  check("incomplete is not complete", () =>
    assert.equal(graphTone("incomplete"), "pending"),
  );
  check("inactive is not active", () =>
    assert.equal(graphTone("inactive"), "pending"),
  );
  const assessment = {
    ...run,
    spec: { ...run.spec, mode: "review" },
    tasks: [],
    sessions: [
      {
        provider: "codex",
        transport: "cli",
        mode: "consult",
        task_id: "review-0",
      },
      { provider: "codex", transport: "cli", mode: "consult", task_id: null },
    ],
    reviews: [{ provider: "codex", ok: true, answer: "Assessment complete" }],
  };
  const assessmentAgents = getRunAgents(assessment, []);
  check("review synthesis belongs to coordinator", () =>
    assert.equal(assessmentAgents[0].sessions[0].task_id, null),
  );
  check("review slot belongs to member", () =>
    assert.equal(assessmentAgents[1].sessions[0].task_id, "review-0"),
  );
  check("review assessment ownership", () =>
    assert.equal(assessmentAgents[1].reviews.length, 1),
  );
  check("failed assessment is not shown as review complete", () =>
    assert.equal(getRunAgents({ ...assessment, status: "needs_attention", reviews: [{ provider: "codex", ok: false, error: { code: "authentication_required" } }] }, [])[1].state, "review failed"),
  );
  check("Verified candidate state tone", () =>
    assert.equal(graphTone("Verified candidate"), "good"),
  );
  const milestone = {
    run_id: "test",
    sequence: 4,
    kind: "task",
    task_id: "checks",
    data: { status: "completed" },
    timestamp: "2026-10-06T00:00:03Z",
  };
  check("provider-free task milestone reaches owner", () =>
    assert.deepEqual(
      getRunAgents(run, [milestone])[1].events.map((e) => e.sequence),
      [4],
    ),
  );
  check("single completed assignment shows task title", () =>
    assert.equal(
      getRunAgents(
        {
          ...run,
          status: "completed",
          tasks: [{ ...run.tasks[0], status: "completed" }],
        },
        [milestone],
      )[1].assignment,
      "Fix test",
    ),
  );
  const reviewRun = {
    ...run,
    spec: {
      coordinator,
      mode: "build",
      team: [
        { ...member, provider: "claude" },
        { ...member, provider: "grok", role: "reviewer" },
      ],
    },
    tasks: [
      {
        id: "feature",
        title: "Implement billing",
        provider: "claude",
        status: "running",
        active_attempt: { state: "implemented" },
      },
    ],
    sessions: [],
    reviews: [],
  };
  const processEvent = (sequence, provider, taskId, mode, type, pid) => ({
    run_id: "test",
    sequence,
    kind: "provider",
    task_id: taskId,
    data: { provider, transport: "cli", mode, type, pid },
    timestamp: "2026-10-06T00:01:00Z",
  });
  const reviewStart = processEvent(
    10,
    "grok",
    "review-feature",
    "consult",
    "parallax.process_started",
    77,
  );
  const reviewFinish = processEvent(
    11,
    "grok",
    "review-feature",
    "consult",
    "parallax.process_finished",
    77,
  );
  const reviewingAgent = getRunAgents(reviewRun, [reviewStart])[2];
  check("unfinished reported reviewer process is reviewing", () =>
    assert.equal(reviewingAgent.state, "reviewing"),
  );
  check("reviewer assignment uses actual task title", () =>
    assert.equal(reviewingAgent.assignment, "Implement billing"),
  );
  check("matched reviewer finish ends live phase", () =>
    assert.notEqual(
      getRunAgents(reviewRun, [reviewStart, reviewFinish])[2].state,
      "reviewing",
    ),
  );
  const combinedStart = processEvent(
    12,
    "grok",
    "review-integration",
    "consult",
    "parallax.process_started",
    78,
  );
  check("combined reviewer assignment identifies candidate", () =>
    assert.equal(
      getRunAgents(reviewRun, [combinedStart])[2].assignment,
      "Combined candidate",
    ),
  );
  const arbitrary = processEvent(
    14,
    "grok",
    "review-feature",
    "consult",
    "item.started",
    77,
  );
  check("arbitrary provider event does not imply live process", () =>
    assert.notEqual(getRunAgents(reviewRun, [arbitrary])[2].state, "reviewing"),
  );
  const coordinateStart = processEvent(
    15,
    "codex",
    "coordinator",
    "coordinate",
    "parallax.process_started",
    88,
  );
  const coordinateFinish = processEvent(
    16,
    "codex",
    "coordinator",
    "coordinate",
    "parallax.process_finished",
    88,
  );
  check("unfinished reported coordinator process is coordinating", () =>
    assert.equal(
      getRunAgents(reviewRun, [coordinateStart])[0].state,
      "coordinating",
    ),
  );
  check("coordinator assignment explains its decision stage", () =>
    assert.equal(
      getRunAgents(reviewRun, [coordinateStart])[0].assignment,
      "Coordinating the next decision",
    ),
  );
  check("matched coordinator finish ends live phase", () =>
    assert.notEqual(
      getRunAgents(reviewRun, [coordinateStart, coordinateFinish])[0].state,
      "coordinating",
    ),
  );
  const coordinateMessage = processEvent(
    17,
    "codex",
    "coordinator",
    "coordinate",
    "item.completed",
    88,
  );
  check("arbitrary later event does not close reported process", () =>
    assert.equal(
      getRunAgents(reviewRun, [coordinateStart, coordinateMessage])[0].state,
      "coordinating",
    ),
  );
  const wrongModeFinish = {
    ...coordinateFinish,
    data: { ...coordinateFinish.data, mode: "consult" },
  };
  check("finish is keyed by mode", () =>
    assert.equal(
      getRunAgents(reviewRun, [coordinateStart, wrongModeFinish])[0].state,
      "coordinating",
    ),
  );
  const wrongTaskFinish = { ...reviewFinish, task_id: "review-another-task" };
  check("finish is keyed by task identity", () =>
    assert.equal(
      getRunAgents(reviewRun, [reviewStart, wrongTaskFinish])[2].state,
      "reviewing",
    ),
  );
  check("paused reviewer is not marked live", () =>
    assert.notEqual(
      getRunAgents({ ...reviewRun, status: "paused" }, [reviewStart])[2].state,
      "reviewing",
    ),
  );
  check("interrupted coordinator is not marked live", () =>
    assert.notEqual(
      getRunAgents({ ...reviewRun, status: "interrupted" }, [
        coordinateStart,
      ])[0].state,
      "coordinating",
    ),
  );
  const resumed = {
    run_id: "test",
    sequence: 11,
    kind: "resumed",
    data: {},
    timestamp: "2026-10-06T00:02:00Z",
  };
  check("resume does not revive an old unfinished process", () =>
    assert.notEqual(
      getRunAgents(reviewRun, [reviewStart, resumed])[2].state,
      "reviewing",
    ),
  );
  const resumedStart = {
    ...reviewStart,
    sequence: 12,
    data: { ...reviewStart.data, pid: 79 },
  };
  check("new process after resume reports live phase", () =>
    assert.equal(
      getRunAgents(reviewRun, [reviewStart, resumed, resumedStart])[2].state,
      "reviewing",
    ),
  );
  const namedCoordinatorTask = {
    ...run,
    tasks: [{ ...run.tasks[0], id: "coordinator" }],
    sessions: [{ ...run.sessions[1], task_id: "coordinator" }],
  };
  check("task named coordinator remains a worker session", () =>
    assert.equal(
      getRunAgents(namedCoordinatorTask, [])[1].sessions[0].mode,
      "edit",
    ),
  );
  const conflictingProvider = {
    ...milestone,
    data: { ...milestone.data, provider: "grok" },
  };
  check("conflicting provider evidence is not reassigned by task", () =>
    assert.equal(getRunAgents(run, [conflictingProvider])[1].events.length, 0),
  );
  const activity = (data, kind = "provider") => ({
    run_id: "test",
    sequence: 50,
    kind,
    task_id: "feature",
    data,
    timestamp: "2026-10-06T00:03:00Z",
  });
  check("running task attempt summary", () =>
    assert.equal(
      describeRunEvent(
        activity({ active_attempt: { state: "running" } }, "task"),
      ),
      "Implementation started",
    ),
  );
  check("implemented task attempt summary", () =>
    assert.equal(
      describeRunEvent(
        activity({ active_attempt: { state: "implemented" } }, "task"),
      ),
      "Implementation recorded; awaiting independent review",
    ),
  );
  check("reviewed task attempt summary", () =>
    assert.equal(
      describeRunEvent(
        activity({ active_attempt: { state: "reviewed" } }, "task"),
      ),
      "Independent review recorded",
    ),
  );
  check("completed task milestone summary", () =>
    assert.equal(
      describeRunEvent(activity({ status: "completed" }, "task")),
      "Task completed",
    ),
  );
  const claude = (content) =>
    activity({ provider: "claude", type: "assistant", message: { content } });
  check("Claude tool description is public activity", () =>
    assert.equal(
      describeRunEvent(
        claude([
          {
            type: "tool_use",
            name: "Bash",
            input: { description: "Run package tests", command: "npm test" },
          },
        ]),
      ),
      "Bash · Run package tests",
    ),
  );
  check("Claude file path summary is shortened", () =>
    assert.equal(
      describeRunEvent(
        claude([
          {
            type: "tool_use",
            name: "Read",
            input: { file_path: "/isolated/project/web/src/totals.ts" },
          },
        ]),
      ),
      "Read · src/totals.ts",
    ),
  );
  check("Claude command activity stays bounded", () => {
    const summary = describeRunEvent(
      claude([
        {
          type: "tool_use",
          name: "Bash",
          input: { command: `python ${"x".repeat(300)}` },
        },
      ]),
    );
    assert.ok(
      summary.startsWith("Bash · python ") &&
        summary.length < 150 &&
        summary.endsWith("…"),
    );
  });
  check("Claude multiple tool requests are summarized", () => {
    const summary = describeRunEvent(
      claude([
        {
          type: "tool_use",
          name: "Read",
          input: { file_path: "/project/src/a.ts" },
        },
        { type: "tool_use", name: "Bash", input: { command: "npm test" } },
      ]),
    );
    assert.ok(
      summary.includes("Read · src/a.ts") &&
        summary.includes("Bash · npm test"),
    );
  });
  check("Claude public text excludes private blocks", () =>
    assert.equal(
      describeRunEvent(
        claude([
          { type: "thinking", thinking: "PRIVATE REASONING" },
          { type: "redacted_thinking", data: "PRIVATE REDACTION" },
          { type: "text", text: "The test failure is reproduced." },
        ]),
      ),
      "The test failure is reproduced.",
    ),
  );
  check("Claude thinking-only message reveals no text", () =>
    assert.equal(
      describeRunEvent(
        claude([{ type: "thinking", thinking: "PRIVATE REASONING" }]),
      ),
      "Provider update",
    ),
  );
  check("Claude tool result records completion", () =>
    assert.equal(
      describeRunEvent(
        claude([
          {
            type: "tool_result",
            tool_use_id: "tool-1",
            is_error: false,
            content: "Tests completed",
          },
        ]),
      ),
      "Tool completed",
    ),
  );
  check("Claude tool result records explicit error", () =>
    assert.equal(
      describeRunEvent(
        claude([
          {
            type: "tool_result",
            tool_use_id: "tool-1",
            is_error: true,
            content: "Permission denied",
          },
        ]),
      ),
      "Tool returned an error",
    ),
  );
  const antigravity = (step_update) =>
    activity({ provider: "antigravity", event: "step_update", step_update });
  check("Antigravity tool ACTIVE observation", () =>
    assert.equal(
      describeRunEvent(
        antigravity({
          step_type: "tool",
          tool_name: "run_command",
          state: "ACTIVE",
        }),
      ),
      "run_command · active",
    ),
  );
  check("Antigravity tool DONE observation", () =>
    assert.equal(
      describeRunEvent(
        antigravity({
          step_type: "tool",
          tool_name: "run_command",
          state: "DONE",
        }),
      ),
      "run_command · completed",
    ),
  );
  check("Antigravity explicit tool error observation", () =>
    assert.equal(
      describeRunEvent(
        antigravity({
          step_type: "tool",
          tool_name: "run_command",
          state: "DONE",
          tool_info: { error: "Permission denied" },
        }),
      ),
      "run_command · error",
    ),
  );
  check("Antigravity hidden reasoning is not shown", () =>
    assert.equal(
      describeRunEvent(
        antigravity({ step_type: "thinking", text_delta: "PRIVATE REASONING" }),
      ),
      "Provider update",
    ),
  );
  check("Antigravity public agent response is shown", () =>
    assert.equal(
      describeRunEvent(
        antigravity({
          step_type: "agent_response",
          text_delta: "The scoped change is implemented.",
        }),
      ),
      "The scoped change is implemented.",
    ),
  );
  check("Codex command activity preserves reported command", () =>
    assert.equal(
      describeRunEvent(
        activity({
          provider: "codex",
          item: { type: "command_execution", command: "npm test" },
        }),
      ),
      "Reported command: npm test",
    ),
  );
  console.log(`${passed} graph-inspection assertions passed`);
} finally {
  fs.rmSync(compiled, { recursive: true, force: true });
}
