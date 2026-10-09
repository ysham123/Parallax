import { useId } from "react";
import type { CheckSpec } from "./types";
import { WorkIcon } from "./WorkIcon";
import "./task-preflight.css";

/** Older workers may report only status and issues. Missing evidence stays unknown. */
export type TaskAssessment = {
  status?: string;
  assessed_at?: string;
  git?: boolean;
  execution?: { enforced?: boolean; backend?: string | null };
  packages?: {
    root?: string;
    kind?: string;
    setup?: string;
    manager?: string | null;
  }[];
  instructions?: string[];
  proposed_checks?: CheckSpec[];
  issues?: {
    severity?: string;
    category?: string;
    root?: string;
    message: string;
  }[];
};

// Shell-style quoting is for readable display only; checks execute as argv arrays.
const argument = (value: string) =>
  /^[a-zA-Z0-9_./:=+@%-]+$/.test(value)
    ? value
    : `'${value.replaceAll("'", "'\\''")}'`;

export function TaskPreflight({
  assessment,
  configuredChecks,
  onUseChecks,
  disabled,
}: {
  assessment: TaskAssessment;
  configuredChecks?: CheckSpec[];
  onUseChecks: (checks: CheckSpec[]) => void;
  disabled: boolean;
}) {
  const titleId = useId();
  const checksNoteId = useId();
  const issues = assessment.issues ?? [];
  const packages = assessment.packages ?? [];
  const instructions = assessment.instructions ?? [];
  const configured = !!configuredChecks?.length;
  const checks = configured
    ? configuredChecks!
    : (assessment.proposed_checks ?? []);
  const blocked =
    assessment.status === "blocked" ||
    issues.some((issue) => issue.severity === "blocker");
  const ready = assessment.status === "ready" && !blocked;
  const setupNeeded = blocked || assessment.status === "needs_configuration";
  const assessedAt = assessment.assessed_at
    ? new Date(assessment.assessed_at)
    : null;

  return (
    <section className="task-preflight" aria-labelledby={titleId}>
      <header className="preflight-heading">
        <h2 id={titleId}>
          <WorkIcon name="review" size={15} /> Project preflight
        </h2>
        <span
          className={`preflight-status ${ready ? "ready" : setupNeeded ? "blocked" : ""}`}
          role="status"
        >
          {ready
            ? "Ready to start"
            : setupNeeded
              ? "Setup needs attention"
              : "Assessment received"}
        </span>
      </header>

      {issues.length > 0 && (
        <ul className="preflight-issues" aria-label="Setup issues">
          {issues.map((issue, index) => (
            <li
              key={index}
              className={issue.severity === "blocker" ? "blocker" : ""}
            >
              <WorkIcon name="warning" size={14} />
              <div>
                <strong>
                  {issue.severity === "blocker" ? "Blocked" : "Attention"}
                </strong>
                {issue.root && <code>{issue.root}</code>}
                <p>{issue.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <dl className="preflight-facts">
        <div>
          <dt>Git repository</dt>
          <dd>
            {assessment.git === true
              ? "Root detected"
              : assessment.git === false
                ? "Root not detected"
                : "Not reported"}
          </dd>
        </div>
        <div>
          <dt>Project command isolation</dt>
          <dd>
            {assessment.execution?.enforced === true
              ? `Available${assessment.execution.backend ? ` · ${assessment.execution.backend}` : ""}`
              : assessment.execution?.enforced === false
                ? "Unavailable"
                : "Not reported"}
          </dd>
        </div>
      </dl>

      <details className="preflight-discovery">
        <summary>
          Packages & instruction files
          <small>
            {assessment.packages === undefined
              ? "Not reported"
              : `${packages.length} package${packages.length === 1 ? "" : "s"}`}
          </small>
        </summary>
        {packages.length > 0 ? (
          <ul className="preflight-packages">
            {packages.map((item, index) => (
              <li key={`${item.root}-${index}`}>
                <code>{item.root || "."}</code>
                <span>
                  {item.kind || "Type not reported"}
                  {item.manager ? ` · ${item.manager}` : ""}
                </span>
                <small>Setup: {item.setup || "not reported"}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="preflight-note">
            {assessment.packages === undefined
              ? "This worker did not report package discovery."
              : "No supported packages detected."}
          </p>
        )}
        <h3>Instruction files</h3>
        {instructions.length > 0 ? (
          <ul className="preflight-instructions">
            {instructions.map((path, index) => (
              <li key={`${path}-${index}`}>
                <code>{path}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="preflight-note">
            {assessment.instructions === undefined
              ? "This worker did not report instruction files."
              : "No AGENTS.md or CLAUDE.md files found in the discovery scope."}
          </p>
        )}
      </details>

      <div className="preflight-check-plan">
        <h3>
          {configured ? "Configured checks" : "Detected checks"}{" "}
          <span>{checks.length}</span>
        </h3>
        {checks.length > 0 ? (
          <>
            <ul className="preflight-checks">
              {checks.map((check, index) => (
                <li key={`${check.name}-${index}`}>
                  <div className="preflight-check-heading">
                    <strong>{check.name}</strong>
                    <span>{check.timeout}s limit</span>
                  </div>
                  <code className="preflight-command">
                    {check.argv.map(argument).join(" ")}
                  </code>
                  <small>
                    Working directory: <code>{check.cwd || "."}</code>
                  </small>
                </li>
              ))}
            </ul>
            {!configured && (
              <div className="preflight-check-action">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={disabled}
                  aria-describedby={checksNoteId}
                  onClick={() => onUseChecks(structuredClone(checks))}
                >
                  Use detected checks
                </button>
                <p id={checksNoteId} className="preflight-note">
                  Replaces the checks in the recipe editor. Save the recipe
                  before starting.
                </p>
              </div>
            )}
          </>
        ) : (
          <p className="preflight-note">
            {assessment.proposed_checks === undefined
              ? "This worker did not report detected checks."
              : "No checks detected. Add explicit check commands in the recipe editor."}
          </p>
        )}
      </div>

      <p className="preflight-footnote">
        Discovery does not run these checks.
        {assessedAt && !Number.isNaN(assessedAt.getTime()) && (
          <>
            {" "}
            Assessed{" "}
            <time dateTime={assessment.assessed_at}>
              {assessedAt.toLocaleString([], {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
            </time>
            .
          </>
        )}
      </p>
    </section>
  );
}
