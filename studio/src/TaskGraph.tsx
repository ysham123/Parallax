import { useEffect, useMemo, useRef, useState } from "react";
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
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ProviderMark } from "./Brand";
import { LABELS, type Data } from "./types";

type TaskNode = Node<{ task: Data; inspect: (id: string) => void }, "task">;
const label = (value: unknown, fallback = "") =>
  typeof value === "string" ? value : value == null ? fallback : String(value);
const state = (value: unknown) => label(value, "planned").replaceAll("_", " ");
const tone = (value: unknown) =>
  /fail|error|cancel|reject|block/.test(label(value))
    ? "bad"
    : /complete|accepted|success|resolved/.test(label(value))
      ? "good"
      : /running|review|work|active/.test(label(value))
        ? "active"
        : "pending";

function TaskCard({ data, selected }: NodeProps<TaskNode>) {
  const task = data.task;
  const provider = label(task.provider);
  const id = label(task.id);
  return (
    <article className={`graph-task ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button
        className="graph-task-button nodrag"
        onClick={() => data.inspect(id)}
        aria-label={`Inspect task ${id}: ${label(task.title, id)}, ${state(task.status)}`}
      >
        <span className="graph-task-top">
          <ProviderMark provider={provider} size={28} />
          <span>{LABELS[provider] || provider}</span>
          <span className={`graph-status-dot ${tone(task.status)}`} />
        </span>
        <strong>{label(task.title, id)}</strong>
        <span className="graph-task-bottom">
          <code>{id}</code>
          <span className={`status ${tone(task.status)}`}>
            {state(task.status)}
          </span>
        </span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </article>
  );
}
const nodeTypes = { task: TaskCard };

export function TaskGraph({
  tasks,
  selected,
  onSelect,
}: {
  tasks: Data[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const canvas = useRef<HTMLDivElement>(null);
  const [instance, setInstance] = useState<ReactFlowInstance<TaskNode> | null>(
    null,
  );
  useEffect(() => {
    if (!canvas.current || !instance) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        void instance.fitView({ padding: 0.23, maxZoom: 1, duration: 0 });
      });
    });
    observer.observe(canvas.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [instance]);
  const graph = useMemo(() => {
    const byId = new Map(tasks.map((t) => [label(t.id), t]));
    const cache = new Map<string, number>();
    const rank = (id: string, seen = new Set<string>()): number => {
      if (seen.has(id)) return 0;
      if (cache.has(id)) return cache.get(id)!;
      const task = byId.get(id);
      const deps = Array.isArray(task?.dependencies)
        ? task.dependencies.map((d) => label(d)).filter((d) => byId.has(d))
        : [];
      const result = Math.min(
        20,
        deps.length
          ? 1 +
              Math.max(...deps.map((dep) => rank(dep, new Set([...seen, id]))))
          : 0,
      );
      cache.set(id, result);
      return result;
    };
    const columns = new Map<number, Data[]>();
    tasks.forEach((t) => {
      const r = rank(label(t.id));
      columns.set(r, [...(columns.get(r) || []), t]);
    });
    const maxRows = Math.max(
      1,
      ...Array.from(columns.values()).map((c) => c.length),
    );
    const nodes: TaskNode[] = [];
    columns.forEach((column, r) =>
      column.forEach((task, row) =>
        nodes.push({
          id: label(task.id),
          type: "task",
          position: {
            x: r * 320,
            y: row * 184 + (maxRows - column.length) * 92,
          },
          data: { task, inspect: onSelect },
          selected: selected === label(task.id),
          width: 244,
          height: 136,
          draggable: false,
          connectable: false,
          focusable: false,
          ariaLabel: `Task ${label(task.id)}: ${label(task.title)}`,
        }),
      ),
    );
    const edges: Edge[] = tasks
      .flatMap((task) =>
        (Array.isArray(task.dependencies) ? task.dependencies : []).map(
          (dep) => ({
            id: `${label(dep)}-${label(task.id)}`,
            source: label(dep),
            target: label(task.id),
            type: "bezier",
            animated: /running|active/.test(label(task.status)),
            markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
            style: {
              stroke:
                selected === label(task.id) || selected === label(dep)
                  ? "var(--accent)"
                  : "var(--graph-edge)",
              strokeWidth:
                selected === label(task.id) || selected === label(dep)
                  ? 2
                  : 1.4,
            },
            ariaLabel: `Dependency: ${label(dep)} must finish before ${label(task.id)}`,
            deletable: false,
            focusable: true,
          }),
        ),
      )
      .filter((e) => byId.has(e.source) && byId.has(e.target));
    const repairs: Edge[] = tasks
      .filter((task) => byId.has(label(task.resolved_by)))
      .map((task) => ({
        id: `resolution-${label(task.id)}-${label(task.resolved_by)}`,
        source: label(task.id),
        target: label(task.resolved_by),
        type: "bezier",
        label: "Repair",
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: {
          stroke: "var(--teal)",
          strokeDasharray: "5 5",
          strokeWidth: 1.6,
        },
        labelStyle: { fill: "var(--muted)", fontSize: 11 },
        labelBgStyle: { fill: "var(--surface)" },
        ariaLabel: `Resolution: failed task ${label(task.id)} was resolved by replacement ${label(task.resolved_by)}`,
        deletable: false,
        focusable: true,
      }));
    return {
      nodes,
      edges: [...edges, ...repairs],
      dependencies: edges.length,
      repairs: repairs.length,
    };
  }, [tasks, selected, onSelect]);
  return (
    <div
      className="task-graph-region"
      aria-label="Recorded task dependency graph"
    >
      <div className="graph-hint">
        <span>
          <i className="graph-status-dot active" /> {tasks.length} recorded{" "}
          {tasks.length === 1 ? "task" : "tasks"} · {graph.dependencies}{" "}
          dependencies
          {graph.repairs > 0 &&
            ` · ${graph.repairs} ${graph.repairs === 1 ? "repair" : "repairs"}`}
        </span>
        <span>Pan · Zoom · Select a task to inspect</span>
      </div>
      <div className="task-graph-canvas" ref={canvas}>
        <ReactFlow<TaskNode>
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          onInit={setInstance}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesReconnectable={false}
          deleteKeyCode={null}
          fitView
          fitViewOptions={{ padding: 0.23, maxZoom: 1 }}
          minZoom={0.15}
          maxZoom={2.5}
          onNodeClick={(_, node) => onSelect(node.id)}
          colorMode="system"
          ariaLabelConfig={{
            "controls.zoomIn.ariaLabel": "Zoom in on task graph",
            "controls.zoomOut.ariaLabel": "Zoom out of task graph",
            "controls.fitView.ariaLabel": "Fit all recorded tasks",
          }}
        >
          <Background gap={24} size={1} color="var(--graph-grid)" />
          <Controls showInteractive={false} />
          {tasks.length > 5 && (
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) => {
                const t = (n.data as TaskNode["data"]).task;
                return tone(t.status) === "good"
                  ? "#66b4a3"
                  : tone(t.status) === "bad"
                    ? "#d18586"
                    : "#9186d0";
              }}
              maskColor="var(--graph-minimap-mask)"
            />
          )}
        </ReactFlow>
      </div>
      <p className="graph-accessibility">
        Task buttons work with Tab and Enter. The graph follows recorded
        dependencies; task details remain available below.
      </p>
    </div>
  );
}
