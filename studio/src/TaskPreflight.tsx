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
    provider?: string;
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
  showIssues = true,
}: {
  assessment: TaskAssessment;
  configuredChecks?: CheckSpec[];
  onUseChecks: (checks: CheckSpec[]) => void;
  disabled: boolean;
  /** The composer can render all issues beside its setup summary instead. */
  showIssues?: boolean;
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
  const checksReported = assessment.proposed_checks !== undefined;
  const checkSummary = configured
    ? `${checks.length} configured check${checks.length === 1 ? "" : "s"} for this task`
    : checks.length
      ? `${checks.length} detected check${checks.length === 1 ? "" : "s"} proposed`
      : checksReported
        ? "No checks detected"
        : "Check discovery not reported";
  const assessedAt = assessment.assessed_at
    ? new Date(assessment.assessed_at)
    : null;

  return (
    <section className="task-preflight" aria-labelledby={titleId}>
      <header className="preflight-heading">
        <h2 id={titleId}>
          <WorkIcon name="review" size={16} /> Project setup
        </h2>
        <span
          className={`preflight-status ${ready ? "inspected" : setupNeeded ? "blocked" : ""}`}
          role="status"
        >
          {ready
            ? "Setup inspected"
            : setupNeeded
              ? "Setup needs attention"
              : "Inspection status unknown"}
        </span>
      </header>

      <p className="preflight-scope">
        This inspection does not run project checks or model inference and does
        not verify provider quota.
      </p>

      {showIssues && issues.length > 0 && (
        <ul className="preflight-issues" aria-label="Setup issues">
          {issues.map((issue, index) => (
            <li
              key={index}
              className={issue.severity === "blocker" ? "blocker" : ""}
            >
              <WorkIcon name="warning" size={14} />
              <div>
                <strong>
                  {issue.severity === "blocker"
                    ? "Blocker"
                    : issue.severity === "warning"
                      ? "Warning"
                      : "Attention"}
                </strong>
                {issue.root && <code>{issue.root}</code>}
                {issue.provider && (
                  <span className="preflight-issue-provider">
                    Provider: {issue.provider}
                  </span>
                )}
                <p>{issue.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!issues.length && (
        <p className="preflight-note">
          {assessment.issues === undefined
            ? "Setup issues were not reported by this worker."
            : setupNeeded
              ? "This report needs setup attention but did not provide issue details."
              : "No setup issues reported."}
        </p>
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
          <dt>Command isolation</dt>
          <dd>
            {assessment.execution?.enforced === true
              ? `Available${assessment.execution.backend ? ` (${assessment.execution.backend})` : ""}`
              : assessment.execution?.enforced === false
                ? "Unavailable"
                : "Not reported"}
          </dd>
        </div>
      </dl>

      <div className="preflight-check-plan">
        <h3>Check plan</h3>
        <p className="preflight-check-summary">
          {checkSummary}. <span>Not run by this inspection.</span>
        </p>
        {checks.length > 0 ? (
          <>
            <details className="preflight-command-details">
              <summary>Inspect commands, directories and time limits</summary>
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
            </details>
            {!configured && (
              <div className="preflight-check-action">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={disabled}
                  aria-describedby={checksNoteId}
                  onClick={() => {
                    if (!disabled) onUseChecks(structuredClone(checks));
                  }}
                >
                  Use detected checks
                </button>
                <p id={checksNoteId} className="preflight-note">
                  Uses these checks for this task. Your saved recipe stays
                  unchanged.
                </p>
              </div>
            )}
          </>
        ) : (
          <p className="preflight-note">
            {!checksReported
              ? "This worker did not report detected checks."
              : "No checks detected. Add explicit check commands in task settings."}
          </p>
        )}
      </div>

      <details className="preflight-discovery">
        <summary>
          Packages and instruction files
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
                  {item.manager ? ` (${item.manager})` : ""}
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

      <p className="preflight-footnote">
        {assessedAt && !Number.isNaN(assessedAt.getTime()) ? (
          <>
            Report time:{" "}
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
        ) : (
          "Inspection time not reported."
        )}
      </p>
    </section>
  );
}
