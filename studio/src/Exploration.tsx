import { LABELS, type Data } from "./types";
import {
  DISCARD_REASONS,
  explorations,
  graphText as text,
  graphTone,
  type ContextManifest,
} from "./run-inspection";

function StatusPill({ value }: { value: string }) {
  return (
    <span className={`status ${graphTone(value)}`}>
      <i />
      {value.replaceAll("_", " ")}
    </span>
  );
}

const chars = (count: number) => count.toLocaleString();

/** What an agent's packet contained, by section and size. Contents are never recorded. */
export function ContextDetails({ manifest, label = "Context packet" }: { manifest: ContextManifest; label?: string }) {
  const trimmed = manifest.sections.filter((section) => section.truncated).length;
  return (
    <details className="context-manifest">
      <summary>
        {label} · {chars(manifest.chars)} chars in {manifest.sections.length}{" "}
        {manifest.sections.length === 1 ? "section" : "sections"}
        {trimmed ? ` · ${trimmed} trimmed` : ""}
      </summary>
      <p className="context-manifest-note">
        Compiled from saved run state for this call only. Section sizes are recorded; their contents are not.
      </p>
      <ul>
        {manifest.sections.map((section) => (
          <li key={section.name}>
            <span>{section.name}</span>
            <span>
              {chars(section.chars)}
              {section.truncated ? ` · ${chars(section.truncated)} trimmed` : ""}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** An explored task: its variants by round and the one that was kept. */
export function ExplorationDetail({
  task,
  tasks,
  onSelect,
}: {
  task: Data;
  tasks: Data[];
  onSelect: (id: string) => void;
}) {
  const exploration = explorations(tasks).get(text(task.id));
  if (!exploration) return null;
  const rounds = [...new Set(exploration.variants.map((variant) => text(variant.variant_round, "1")))];
  return (
    <div className="task-exploration">
      <span className="eyebrow">EXPLORATION</span>
      <p>
        {exploration.variants.length} variants across {exploration.rounds}{" "}
        {exploration.rounds === 1 ? "round" : "rounds"}, each in its own checkout, reviewed without knowing which
        variant it was, and checked independently.{" "}
        {exploration.selected ? "One was selected and integrated." : "None has been selected yet."}
      </p>
      {rounds.map((round) => (
        <div className="exploration-round" key={round}>
          <h4>Round {round}</h4>
          {exploration.variants
            .filter((variant) => text(variant.variant_round, "1") === round)
            .map((variant) => (
              <button className="work-assignment" key={text(variant.id)} onClick={() => onSelect(text(variant.id))}>
                <span>
                  {text(variant.id)}
                  <small>
                    {LABELS[text(variant.provider)] || text(variant.provider)}
                    {exploration.selected === text(variant.id) ? " · selected" : ""}
                  </small>
                </span>
                <StatusPill value={text(variant.status, "pending")} />
              </button>
            ))}
        </div>
      ))}
    </div>
  );
}

/** One variant: the approach it was asked to take and what became of it. */
export function VariantDetail({
  task,
  tasks,
  onSelect,
}: {
  task: Data;
  tasks: Data[];
  onSelect: (id: string) => void;
}) {
  const parent = tasks.find((item) => text(item.id) === text(task.variant_of));
  const reason = DISCARD_REASONS[text(task.discarded_reason)];
  return (
    <div className="task-exploration">
      <span className="eyebrow">VARIANT · ROUND {text(task.variant_round, "1")}</span>
      {text(task.directive) && <p className="variant-directive">{text(task.directive)}</p>}
      {text(task.status) === "discarded" && reason && <p>Set aside: {reason.toLowerCase()}.</p>}
      {parent && (
        <button className="work-assignment" onClick={() => onSelect(text(parent.id))}>
          <span>
            Variant of {text(parent.title, text(parent.id))}
            <small>Every variant of a task shares its requirements</small>
          </span>
          <StatusPill value={text(parent.status, "exploring")} />
        </button>
      )}
    </div>
  );
}
