import {
  LABELS,
  type Data,
  type Participant,
  type RunEvent,
  type RunResult,
} from "./types";

export const graphText = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : value == null ? fallback : String(value);

export const graphTone = (
  value: unknown,
): "bad" | "good" | "active" | "pending" =>
  /fail|error|cancel|reject|block|needs[ _]attention|changes[ _]requested|unavailable|unauthenticated/i.test(
    graphText(value),
  )
    ? "bad"
    : /\b(?:complete|completed|accepted|success|succeeded|resolved|approved|passed|integrated)\b|^verified candidate(?: ready)?$/i.test(
          graphText(value),
        )
      ? "good"
      : /\b(?:running|reviewing|working|active|implementing|coordinating)\b/i.test(
            graphText(value),
          )
        ? "active"
        : "pending";

const connectionOf = (member: Participant | Data) =>
  graphText(member.connection_id) ||
  (member.transport === "api" ? `${graphText(member.provider)}-api` : "local");

/** Coordinator and worker are separate dedicated sessions on a shared connection. */
export const agentKey = (
  member: Participant | Data,
  coordinator = false,
): string =>
  `${coordinator ? "coordinator" : "member"}:${graphText(member.provider)}:${graphText(member.transport, "cli")}:${connectionOf(member)}`;

export type IndexedReview = { index: number; review: Data };
export type RunAgent = {
  key: string;
  id: string;
  participant: Participant;
  coordinator: boolean;
  roles: string[];
  tasks: Data[];
  reviews: IndexedReview[];
  sessions: Data[];
  events: RunEvent[];
  latestEvent?: RunEvent;
  effectiveSettings?: Data;
  state: string;
  assignment: string;
};

function recordOf(value: unknown): Data {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Data)
    : {};
}

/** An ambiguous provider-only record is left unassigned rather than guessed. */
function ownerKey(
  record: Data,
  agents: RunAgent[],
  worker = false,
): string | undefined {
  if (!record.provider) return undefined;
  const coordinate =
    record.mode === "coordinate" ||
    (!record.mode && record.task_id === "coordinator");
  const candidates = agents.filter(
    (agent) =>
      agent.participant.provider === record.provider &&
      (!worker || !agent.coordinator) &&
      (!coordinate || agent.coordinator) &&
      (record.mode !== "edit" || !agent.coordinator) &&
      (!record.transport ||
        (agent.participant.transport || "cli") === record.transport) &&
      (!record.connection_id ||
        connectionOf(agent.participant) === connectionOf(record)),
  );
  return candidates.length === 1 ? candidates[0].key : undefined;
}

export function describeRunEvent(event: RunEvent): string {
  const data = event.data;
  const item = recordOf(data.item);
  const step = recordOf(data.step_update);
  if (
    ["thinking", "thought"].includes(graphText(data.type)) ||
    ["thinking", "reasoning"].includes(graphText(item.type)) ||
    ["thinking", "reasoning"].includes(graphText(step.step_type))
  )
    return "Provider update";
  const short = (value: string) => {
    const line = value.replace(/\s+/g, " ").trim();
    return line.length > 120 ? `${line.slice(0, 117)}…` : line;
  };
  if (event.kind === "task") {
    const attempt = recordOf(data.active_attempt);
    const phases: Record<string, string> = {
      running: "Implementation started",
      implemented: "Implementation recorded; awaiting independent review",
      reviewed: "Independent review recorded",
      interrupted: "Implementation interrupted",
      failed: "Implementation attempt failed",
    };
    if (phases[graphText(attempt.state)])
      return phases[graphText(attempt.state)];
    const states: Record<string, string> = {
      pending: "Task queued",
      running: "Task started",
      completed: "Task completed",
      failed: "Task failed",
      resolved: "Task resolved by its verified replacement",
      interrupted: "Task interrupted",
    };
    if (states[graphText(data.status)]) return states[graphText(data.status)];
  }
  for (const key of ["summary", "message", "title", "reason"])
    if (typeof data[key] === "string" && data[key]) return String(data[key]);
  const content = recordOf(data.message).content;
  if (Array.isArray(content)) {
    const publicBlocks = content
      .map(recordOf)
      .filter(
        (block) =>
          !["thinking", "redacted_thinking"].includes(graphText(block.type)),
      );
    const tools = publicBlocks.filter((block) => block.type === "tool_use");
    if (tools.length) {
      const summaries = tools.slice(0, 2).map((tool) => {
        const input = recordOf(tool.input);
        const description = graphText(input.description);
        const filePath = graphText(input.file_path).replaceAll("\\", "/");
        const detail =
          description ||
          filePath.split("/").filter(Boolean).slice(-2).join("/") ||
          graphText(input.command);
        return `${graphText(tool.name, "Tool")}${detail ? ` · ${short(detail)}` : ""}`;
      });
      return `${summaries.join("; ")}${tools.length > 2 ? `; +${tools.length - 2} tools` : ""}`;
    }
    const results = publicBlocks.filter(
      (block) => block.type === "tool_result",
    );
    if (results.length)
      return results.some((result) => result.is_error === true)
        ? "Tool returned an error"
        : results.length === 1
          ? "Tool completed"
          : `${results.length} tools completed`;
    const publicText = publicBlocks
      .filter(
        (block) => block.type === "text" && typeof block.text === "string",
      )
      .map((block) => graphText(block.text))
      .join(" ");
    if (publicText.trim()) return short(publicText);
    return "Provider update";
  }
  if (typeof item.command === "string")
    return `Reported command: ${short(item.command)}`;
  if (typeof step.tool_name === "string") {
    const state = graphText(step.state || step.status).toLowerCase();
    const toolInfo = recordOf(step.tool_info);
    const reportedState = toolInfo.error
      ? "error"
      : state === "done"
        ? "completed"
        : state;
    return `${step.tool_name}${reportedState ? ` · ${short(reportedState)}` : " · reported"}`;
  }
  if (
    step.step_type === "agent_response" &&
    typeof step.text_delta === "string" &&
    step.text_delta.trim()
  )
    return short(step.text_delta);
  if (typeof data.name === "string") return data.name;
  if (typeof data.status === "string") return data.status;
  return graphText(data.type || data.event || event.kind).replaceAll("_", " ");
}

export function getRunAgents(
  run: RunResult,
  events: RunEvent[] = [],
): RunAgent[] {
  const agents: RunAgent[] = [];
  [run.spec.coordinator, ...run.spec.team].forEach((participant, index) => {
    const coordinator = index === 0;
    const key = agentKey(participant, coordinator);
    let agent = agents.find((a) => a.key === key);
    if (!agent) {
      agent = {
        key,
        id: `agent:${key}`,
        participant,
        coordinator,
        roles: [],
        tasks: [],
        reviews: [],
        sessions: [],
        events: [],
        state: "configured",
        assignment: "No recorded assignment",
      };
      agents.push(agent);
    }
    const role = coordinator ? "coordinator" : participant.role;
    if (!agent.roles.includes(role)) agent.roles.push(role);
  });
  const sessionOwner = (record: Data) => {
    if (run.spec.mode === "review") {
      const slot = /^review-(\d+)$/.exec(graphText(record.task_id));
      const member = slot ? run.spec.team[Number(slot[1])] : undefined;
      if (member && member.provider === record.provider)
        return agentKey(member);
      // The consultation workflow uses an unscoped coordinator synthesis call.
      if (
        !record.task_id &&
        record.mode === "consult" &&
        record.provider === run.spec.coordinator.provider
      )
        return agentKey(run.spec.coordinator, true);
    }
    return ownerKey(record, agents);
  };
  run.tasks.forEach((task) => {
    const participant = recordOf(recordOf(task.active_attempt).participant);
    const owner = ownerKey(
      Object.keys(participant).length ? participant : task,
      agents,
      true,
    );
    agents.find((a) => a.key === owner)?.tasks.push(task);
  });
  run.sessions.forEach((session) =>
    agents.find((a) => a.key === sessionOwner(session))?.sessions.push(session),
  );
  events.forEach((event) => {
    const owner = sessionOwner({ ...event.data, task_id: event.task_id });
    let agent = agents.find((candidate) => candidate.key === owner);
    if (!agent && !event.data.provider && event.task_id) {
      const candidates = agents.filter((candidate) =>
        candidate.tasks.some((task) => task.id === event.task_id),
      );
      if (candidates.length === 1) agent = candidates[0];
    }
    agent?.events.push(event);
  });
  run.reviews.forEach((review, index) => {
    const member =
      run.spec.mode === "review" ? run.spec.team[index] : undefined;
    let owner =
      member && member.provider === review.provider
        ? agentKey(member)
        : ownerKey(review, agents);
    if (!owner) {
      const taskId = graphText(review.task_id);
      const sessionOwners = agents.filter(
        (a) =>
          a.participant.provider === review.provider &&
          a.sessions.some((s) => graphText(s.task_id) === `review-${taskId}`),
      );
      if (sessionOwners.length === 1) owner = sessionOwners[0].key;
    }
    agents.find((a) => a.key === owner)?.reviews.push({ index, review });
  });
  const terminal =
    /^(completed|failed|cancelled|interrupted|paused|needs_attention)$/.test(
      run.status,
    );
  const continuationBoundary = Math.max(
    0,
    ...events
      .filter(
        (event) =>
          ["interrupted", "resumed", "cancelled"].includes(event.kind) ||
          (event.kind === "status" && event.data.status === "interrupted"),
      )
      .map((event) => event.sequence),
  );
  agents.forEach((agent) => {
    agent.events.sort((a, b) => a.sequence - b.sequence);
    agent.latestEvent = agent.events.at(-1);
    const effective = [...agent.sessions]
      .reverse()
      .map((s) => recordOf(s.effective_settings))
      .find((settings) => Object.keys(settings).length > 0);
    if (effective) agent.effectiveSettings = effective;
    const unfinished = new Map<string, RunEvent>();
    agent.events.forEach((event) => {
      if (event.sequence <= continuationBoundary) return;
      const type = event.data.type;
      const mode = graphText(event.data.mode);
      if (!["coordinate", "consult", "edit"].includes(mode)) return;
      const key = JSON.stringify([
        event.task_id || null,
        mode,
        event.data.pid || null,
      ]);
      if (type === "parallax.process_started") unfinished.set(key, event);
      else if (type === "parallax.process_finished") unfinished.delete(key);
    });
    const active = [...unfinished.values()].at(-1);
    const activeTaskId = graphText(active?.task_id);
    const reviewTaskId = activeTaskId.startsWith("review-")
      ? activeTaskId.slice(7)
      : "";
    const activeTask = run.tasks.find(
      (task) =>
        task.id ===
        (reviewTaskId.startsWith("resolution-")
          ? reviewTaskId.slice(11)
          : reviewTaskId || activeTaskId),
    );
    const working = agent.tasks.filter((task) => task.status === "running");
    if (active && !terminal && active.data.mode === "consult" && reviewTaskId) {
      agent.state = "reviewing";
      agent.assignment =
        reviewTaskId === "integration"
          ? "Combined candidate"
          : activeTask
            ? graphText(activeTask.title, graphText(activeTask.id))
            : run.spec.mode === "review"
              ? "Project assessment"
              : `Review · ${reviewTaskId}`;
    } else if (active && !terminal && agent.coordinator) {
      agent.state = "coordinating";
      agent.assignment =
        run.spec.mode === "review"
          ? "Synthesizing independent assessments"
          : "Coordinating the next decision";
    } else if (working.length && !terminal) {
      const phase = graphText(recordOf(working[0].active_attempt).state);
      agent.state =
        phase === "implemented"
          ? "awaiting review"
          : phase === "reviewed"
            ? "reviewed"
            : "running task";
      agent.assignment = graphText(working[0].title, graphText(working[0].id));
    } else if (agent.tasks.length) {
      const states = agent.tasks.map((task) => graphText(task.status));
      agent.state = states.every((state) =>
        ["completed", "resolved"].includes(state),
      )
        ? "assignments complete"
        : states.some((state) => state === "failed")
          ? "failed assignment"
          : working.length && terminal
            ? run.status
            : "pending assignments";
      agent.assignment =
        agent.tasks.length === 1
          ? graphText(agent.tasks[0].title, graphText(agent.tasks[0].id))
          : `${agent.tasks.length} recorded tasks`;
    } else if (agent.reviews.length) {
      const latest = agent.reviews.at(-1)!.review;
      agent.state =
        latest.ok === false || latest.error
          ? "review failed"
          : latest.ok === true
            ? "review complete"
            : "review recorded";
      agent.assignment = `${agent.reviews.length} independent ${agent.reviews.length === 1 ? "review" : "reviews"}`;
    } else if (agent.events.length || agent.sessions.length) {
      agent.state =
        agent.coordinator && terminal ? run.status : "session recorded";
      agent.assignment = agent.coordinator
        ? "Coordinates this run"
        : "Provider session recorded";
    }
  });
  return agents;
}

export function reviewLabel(review: Data, index: number): string {
  const taskId = graphText(review.task_id);
  return taskId === "integration"
    ? "Combined review"
    : taskId.startsWith("resolution-")
      ? "Repair review"
      : taskId
        ? `Review · ${taskId}`
        : `Independent assessment ${index + 1}`;
}

export function eventsForSelection(
  run: RunResult,
  events: RunEvent[],
  selection: string | null,
): RunEvent[] {
  if (!selection || selection === "run") return events;
  if (selection.startsWith("agent:"))
    return (
      getRunAgents(run, events).find((a) => a.id === selection)?.events || []
    );
  if (
    selection === "evidence:checks" ||
    (selection === "checks" && !run.tasks.some((task) => task.id === "checks"))
  )
    return events.filter((e) =>
      ["check", "baseline", "environment"].includes(e.kind),
    );
  if (selection.startsWith("review:")) {
    const review = run.reviews[Number(selection.slice(7))];
    if (!review) return [];
    const taskId = graphText(review.task_id);
    return events.filter((e) =>
      taskId
        ? e.task_id === `review-${taskId}` ||
          (e.kind === "review" && e.task_id === taskId)
        : e.data.provider === review.provider &&
          (e.kind === "review" || graphText(e.task_id).startsWith("review-")),
    );
  }
  return events.filter(
    (e) => e.task_id === selection || e.task_id === `review-${selection}`,
  );
}

export const agentLabel = (agent: RunAgent): string =>
  LABELS[agent.participant.provider] || agent.participant.provider;
