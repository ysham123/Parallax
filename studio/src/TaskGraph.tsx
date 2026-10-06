import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  type Node,
  type NodeProps,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ProviderMark } from "./Brand";
import { LABELS, type Data, type RunEvent, type RunResult } from "./types";
import {
  getRunAgents,
  graphText as label,
  graphTone as tone,
  reviewLabel,
  type RunAgent,
} from "./run-inspection";

type GraphData = {
  kind: "task" | "agent" | "review" | "checks";
  title: string;
  provider?: string;
  status: string;
  subtitle: string;
  detail?: string;
  assignment?: string;
  files?: string[];
  id: string;
  inspect: (id: string) => void;
  [key: string]: unknown;
};
type GraphNode = Node<GraphData, "record">;

function RecordCard({ data, selected }: NodeProps<GraphNode>) {
  const kindLabel =
    data.kind === "agent"
      ? "Agent connection"
      : data.kind === "checks"
        ? "Verification"
        : data.kind === "review"
          ? "Independent review"
          : "Task";
  return (
    <article
      className={`graph-task graph-record graph-${data.kind} ${selected ? "selected" : ""}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button
        className="graph-task-button nodrag"
        onClick={() => data.inspect(data.id)}
        aria-label={`Inspect ${kindLabel.toLowerCase()}: ${data.title}, ${data.status.replaceAll("_", " ")}`}
      >
        <span className="graph-task-top">
          {data.provider && <ProviderMark provider={data.provider} size={24} />}
          <span>
            {data.kind === "agent"
              ? data.subtitle
              : data.provider
                ? LABELS[data.provider] || data.provider
                : kindLabel}
          </span>
          <span className={`graph-status-dot ${tone(data.status)}`} />
        </span>
        <strong>{data.title}</strong>
        {data.kind !== "agent" && (
          <span className="graph-node-subtitle">{data.subtitle}</span>
        )}
        {data.detail && (
          <span className="graph-node-detail">{data.detail}</span>
        )}
        {data.assignment && (
          <span className="graph-node-assignment">{data.assignment}</span>
        )}
        {data.files?.length ? (
          <span className="graph-node-files">
            {data.files.slice(0, 2).join(" · ")}
            {data.files.length > 2 ? ` · +${data.files.length - 2}` : ""}
          </span>
        ) : null}
        <span className="graph-task-bottom">
          <span className="graph-node-kind">{kindLabel}</span>
          <span className={`status ${tone(data.status)}`}>
            {data.status.replaceAll("_", " ")}
          </span>
        </span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </article>
  );
}
const nodeTypes = { record: RecordCard };

function taskData(task: Data, onSelect: (id: string) => void): GraphData {
  const attempts = Number(task.attempts || 0);
  return {
    kind: "task",
    id: label(task.id),
    title: label(task.title, label(task.id)),
    provider: label(task.provider),
    status: label(task.status, "pending"),
    subtitle: attempts ? `Attempt ${attempts}` : "Planned assignment",
    files: Array.isArray(task.files)
      ? task.files.map((file) => label(file))
      : [],
    inspect: onSelect,
  };
}
function agentData(agent: RunAgent, onSelect: (id: string) => void): GraphData {
  const provider = agent.participant.provider;
  const effective = agent.effectiveSettings;
  const model = effective
    ? label(effective.model, "Model not reported")
    : label(agent.participant.model, "Account default");
  const effort = effective
    ? label(effective.effort)
    : label(agent.participant.effort);
  return {
    kind: "agent",
    id: agent.id,
    title: LABELS[provider] || provider,
    provider,
    subtitle: agent.roles.join(" · "),
    status: agent.state,
    detail: `${model}${effort ? ` · ${effort}` : ""} · ${effective ? "reported" : "requested"}`,
    files: agent.tasks
      .flatMap((task) =>
        Array.isArray(task.files) ? task.files.map((file) => label(file)) : [],
      )
      .filter((file, i, all) => all.indexOf(file) === i),
    inspect: onSelect,
    assignment: agent.assignment,
  };
}

function makeNode(
  id: string,
  data: GraphData,
  x: number,
  y: number,
  selected: string | null,
): GraphNode {
  return {
    id,
    type: "record",
    data,
    position: { x, y },
    selected: id === selected,
    width: 260,
    height: data.kind === "agent" ? 190 : 170,
    // Fixed wrapper dimensions preserve measured handle bounds during event replay.
    measured: { width: 260, height: data.kind === "agent" ? 190 : 170 },
    draggable: false,
    connectable: false,
    focusable: false,
    ariaLabel: `${data.kind}: ${data.title}`,
  };
}
function makeEdge(
  source: string,
  target: string,
  meaning: string,
  selected: string | null,
  repair = false,
): Edge {
  const highlighted = selected === source || selected === target;
  return {
    id: `${meaning}:${source}:${target}`,
    source,
    target,
    type: "bezier",
    label:
      meaning === "Independent review"
        ? "Review"
        : meaning === "Combined review"
          ? "Combined"
          : meaning,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: {
      stroke: repair
        ? "var(--teal)"
        : highlighted
          ? "var(--accent)"
          : "var(--graph-edge)",
      strokeWidth: highlighted ? 2 : 1.4,
      ...(repair ? { strokeDasharray: "5 5" } : {}),
    },
    labelStyle: { fill: "var(--muted)", fontSize: 10 },
    labelBgStyle: { fill: "var(--surface)" },
    ariaLabel:
      meaning === "Depends on"
        ? `Dependency: ${source} must finish before ${target}`
        : `${meaning}: ${source} to ${target}`,
    deletable: false,
    focusable: true,
  };
}

function TaskGraphCanvas({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: Edge[];
}) {
  return (
    <ReactFlow<GraphNode>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesReconnectable={false}
      deleteKeyCode={null}
      fitView
      fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
      minZoom={0.15}
      maxZoom={2.5}
      colorMode="system"
      onNodeClick={(_, node) => node.data.inspect(node.id)}
      ariaLabelConfig={{
        "controls.zoomIn.ariaLabel": "Zoom in on run graph",
        "controls.zoomOut.ariaLabel": "Zoom out of run graph",
        "controls.fitView.ariaLabel": "Fit all recorded run nodes",
      }}
    >
      <Background gap={24} size={1} color="var(--graph-grid)" />
      <Controls showInteractive={false} />
      {nodes.length > 6 && (
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) =>
            tone(node.data.status) === "good"
              ? "#66b4a3"
              : tone(node.data.status) === "bad"
                ? "#d18586"
                : "#9186d0"
          }
          maskColor="var(--graph-minimap-mask)"
        />
      )}
    </ReactFlow>
  );
}

export function TaskGraph({
  tasks,
  selected,
  onSelect,
  run,
  events = [],
  view = "tasks",
}: {
  tasks: Data[];
  selected: string | null;
  onSelect: (id: string) => void;
  run?: RunResult;
  events?: RunEvent[];
  view?: "tasks" | "agents";
}) {
  const graph = useMemo(() => {
    const byId = new Map(tasks.map((task) => [label(task.id), task]));
    const nodes: GraphNode[] = [];
    const edges: Edge[] = [];
    const agents = run ? getRunAgents(run, events) : [];
    let evidenceX = 0;
    if (view === "agents" && run) {
      const coordinator = agents.find((agent) => agent.coordinator);
      const workers = agents.filter(
        (agent) =>
          !agent.coordinator &&
          !agent.roles.every((role) => role === "reviewer"),
      );
      const reviewers = agents.filter(
        (agent) =>
          !agent.coordinator &&
          agent.roles.every((role) => role === "reviewer"),
      );
      if (coordinator)
        nodes.push(
          makeNode(
            coordinator.id,
            agentData(coordinator, onSelect),
            0,
            (Math.max(workers.length, reviewers.length, 1) - 1) * 125,
            selected,
          ),
        );
      workers.forEach((agent, index) =>
        nodes.push(
          makeNode(
            agent.id,
            agentData(agent, onSelect),
            340,
            index * 250,
            selected,
          ),
        ),
      );
      reviewers.forEach((agent, index) =>
        nodes.push(
          makeNode(
            agent.id,
            agentData(agent, onSelect),
            680,
            index * 250 + Math.max(0, workers.length - reviewers.length) * 125,
            selected,
          ),
        ),
      );
      agents.forEach((agent) => {
        if (coordinator && agent.id !== coordinator.id) {
          const taskIds = new Set(agent.tasks.map((task) => label(task.id)));
          const dispatched = events.some(
            (event) =>
              event.kind === "action" &&
              event.data.action === "dispatch" &&
              Array.isArray(event.data.task_ids) &&
              (event.data.task_ids.some((id) => taskIds.has(label(id))) ||
                (event.data.task_ids.length === 0 &&
                  agent.tasks.some((task) => Number(task.attempts) > 0))),
          );
          if (dispatched)
            edges.push(
              makeEdge(coordinator.id, agent.id, "Dispatched", selected),
            );
          if (
            run.spec.mode === "review" &&
            (agent.sessions.some(
              (session) =>
                session.mode === "consult" &&
                /^review-\d+$/.test(label(session.task_id)),
            ) ||
              agent.events.some(
                (event) =>
                  event.data.mode === "consult" &&
                  /^review-\d+$/.test(label(event.task_id)),
              ))
          )
            edges.push(
              makeEdge(
                coordinator.id,
                agent.id,
                "Independent assessment",
                selected,
              ),
            );
        }
      });
      run.reviews.forEach((review, index) => {
        const reviewer = agents.find((agent) =>
          agent.reviews.some((record) => record.index === index),
        );
        if (!reviewer) return;
        const taskId = label(review.task_id);
        const task = byId.get(
          taskId.startsWith("resolution-") ? taskId.slice(11) : taskId,
        );
        const implementation =
          taskId.startsWith("resolution-") && task?.resolved_by
            ? byId.get(label(task.resolved_by))
            : task;
        const contributors =
          taskId === "integration"
            ? agents.filter((agent) =>
                agent.tasks.some(
                  (item) =>
                    label(item.status) === "completed" &&
                    (run.spec.mode !== "compare" ||
                      label(run.artifacts.selected_task) === label(item.id)),
                ),
              )
            : agents.filter(
                (agent) =>
                  implementation &&
                  agent.tasks.some((item) => item.id === implementation.id),
              );
        contributors.forEach((agent) => {
          if (
            agent.id !== reviewer.id &&
            agent.participant.provider !== reviewer.participant.provider
          )
            edges.push(
              makeEdge(
                agent.id,
                reviewer.id,
                taskId === "integration"
                  ? "Combined review"
                  : "Independent review",
                selected,
              ),
            );
        });
      });
      const relationships = new Map<string, Edge>();
      edges.forEach((edge) => {
        const key = `${edge.source}->${edge.target}`;
        const existing = relationships.get(key);
        if (!existing) relationships.set(key, edge);
        else if (existing.label !== edge.label) {
          existing.label = "Review";
          existing.ariaLabel = `${existing.ariaLabel}; ${edge.ariaLabel}`;
        }
      });
      return { nodes, edges: [...relationships.values()] };
    } else {
      const cache = new Map<string, number>();
      const rank = (id: string, seen = new Set<string>()): number => {
        if (seen.has(id)) return 0;
        if (cache.has(id)) return cache.get(id)!;
        const task = byId.get(id);
        const deps = Array.isArray(task?.dependencies)
          ? task.dependencies
              .map((dep) => label(dep))
              .filter((dep) => byId.has(dep))
          : [];
        const result = Math.min(
          20,
          deps.length
            ? 1 +
                Math.max(
                  ...deps.map((dep) => rank(dep, new Set([...seen, id]))),
                )
            : 0,
        );
        cache.set(id, result);
        return result;
      };
      const columns = new Map<number, Data[]>();
      tasks.forEach((task) => {
        const level = rank(label(task.id));
        columns.set(level, [...(columns.get(level) || []), task]);
      });
      const maxRows = Math.max(
        1,
        ...Array.from(columns.values()).map((column) => column.length),
      );
      columns.forEach((column, level) =>
        column.forEach((task, row) =>
          nodes.push(
            makeNode(
              label(task.id),
              taskData(task, onSelect),
              level * 340,
              row * 215 + (maxRows - column.length) * 107.5,
              selected,
            ),
          ),
        ),
      );
      evidenceX = (Math.max(-1, ...columns.keys()) + 1) * 340;
    }
    tasks.forEach((task) => {
      if (Array.isArray(task.dependencies))
        task.dependencies.forEach((dep) => {
          if (byId.has(label(dep)))
            edges.push(
              makeEdge(label(dep), label(task.id), "Depends on", selected),
            );
        });
      if (byId.has(label(task.resolved_by)))
        edges.push(
          makeEdge(
            label(task.id),
            label(task.resolved_by),
            "Repair",
            selected,
            true,
          ),
        );
    });
    if (run) {
      run.reviews.forEach((review, index) => {
        const id = `review:${index}`;
        const taskId = label(review.task_id);
        const isCombined = taskId === "integration";
        const data: GraphData = {
          kind: "review",
          id,
          title: reviewLabel(review, index),
          provider: label(review.provider),
          status:
            review.ok === true
              ? taskId
                ? "approved"
                : "completed"
              : review.ok === false
                ? taskId
                  ? "rejected"
                  : "failed"
                : "recorded",
          subtitle: isCombined
            ? "Combined candidate"
            : "Independent assessment",
          detail: Array.isArray(review.findings)
            ? `${review.findings.length} recorded ${review.findings.length === 1 ? "finding" : "findings"}`
            : undefined,
          inspect: onSelect,
        };
        const reviewOffset =
          view === "agents"
            ? agents.filter(
                (a) =>
                  !a.coordinator &&
                  a.roles.every((role) => role === "reviewer"),
              ).length * 250
            : 0;
        const x = isCombined
          ? evidenceX + 340
          : view === "agents"
            ? 1020
            : evidenceX;
        nodes.push(makeNode(id, data, x, reviewOffset + index * 205, selected));
        if (byId.has(taskId))
          edges.push(makeEdge(taskId, id, "Independent review", selected));
        else if (taskId.startsWith("resolution-") && byId.has(taskId.slice(11)))
          edges.push(makeEdge(taskId.slice(11), id, "Repair review", selected));
        const reviewer = agents.find((agent) =>
          agent.reviews.some((record) => record.index === index),
        );
        if (view === "agents" && reviewer)
          edges.push(makeEdge(reviewer.id, id, "Reviews", selected));
      });
      const checks = run.checks;
      if (checks.length) {
        const passed = checks.filter((check) => check.ok === true).length;
        const failed = checks.some((check) => check.ok === false);
        nodes.push(
          makeNode(
            "evidence:checks",
            {
              kind: "checks",
              id: "evidence:checks",
              title: "Project checks",
              status: failed
                ? "failed"
                : passed === checks.length
                  ? "passed"
                  : "recorded",
              subtitle: `${passed} / ${checks.length} passed`,
              detail: "Recorded candidate evidence",
              inspect: onSelect,
            },
            evidenceX,
            view === "agents" ? 0 : run.reviews.length * 205,
            selected,
          ),
        );
        tasks
          .filter(
            (task) =>
              label(task.status) === "completed" &&
              (run.spec.mode !== "compare" ||
                label(run.artifacts.selected_task) === label(task.id)),
          )
          .forEach((task) =>
            edges.push(
              makeEdge(
                label(task.id),
                "evidence:checks",
                "Checks candidate",
                selected,
              ),
            ),
          );
        run.reviews.forEach((review, index) => {
          if (review.task_id === "integration")
            edges.push(
              makeEdge(
                "evidence:checks",
                `review:${index}`,
                "Combined review",
                selected,
              ),
            );
        });
      }
    }
    const ids = new Set(nodes.map((node) => node.id));
    return {
      nodes,
      edges: edges.filter(
        (edge) => ids.has(edge.source) && ids.has(edge.target),
      ),
    };
  }, [tasks, selected, onSelect, run, events, view]);
  const title =
    view === "agents"
      ? `${graph.nodes.filter((node) => node.data.kind === "agent").length} configured agents · ${tasks.length} recorded tasks`
      : `${tasks.length} recorded ${tasks.length === 1 ? "task" : "tasks"} · dependencies and evidence`;
  return (
    <div
      className={`task-graph-region graph-view-${view}`}
      aria-label={
        view === "agents"
          ? "Configured agents and recorded work graph"
          : "Recorded task dependency graph"
      }
    >
      <div className="graph-hint">
        <span>{title}</span>
        <span>Pan · Zoom · Select to inspect</span>
      </div>
      <div className="task-graph-canvas">
        {/* Refit only for a different run or graph view, never for selection or event updates. */}
        <TaskGraphCanvas
          key={`${run?.run_id || "tasks"}:${view}`}
          nodes={graph.nodes}
          edges={graph.edges}
        />
      </div>
      <p className="graph-accessibility">
        Tab and Enter inspect recorded nodes. Edges show assignments,
        dependencies, reviews, checks, and repairs.
      </p>
    </div>
  );
}
