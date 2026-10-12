import type { DiffFile } from "./diff-model";

export type ActorDirectory = {
  account: string;
  name?: string;
  login?: string;
}[];

/** Names come only from the current, authenticated workspace directory. */
export function actorLabel(
  actor: string | null | undefined,
  directory: ActorDirectory = [],
  viewer?: string,
): string {
  if (!actor) return "Unrecorded human";
  const member = directory.find((row) => row.account === actor);
  return (
    member?.name?.trim() ||
    member?.login?.trim() ||
    (viewer && actor === viewer ? "You" : "Recorded member")
  );
}

/** A readable task title: the first meaningful line of the request, without Markdown markers. */
export function taskTitle(title?: string | null, limit = 120): string {
  const line =
    (title || "")
      .split(/\r?\n/)
      .map((row) =>
        row
          .replace(/^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)/, "")
          .replace(/^(\*\*|__|`)(.*)\1$/, "$2")
          .replace(/\s+/g, " ")
          .trim(),
      )
      .find(Boolean) || "";
  if (!line) return "Untitled task";
  return line.length > limit ? `${line.slice(0, limit - 1).trimEnd()}…` : line;
}

export function requestLabel(requester?: string, viewer?: string): string {
  return requester && viewer && requester === viewer
    ? "Your request"
    : "Task request";
}

export function recordedTime(at?: string | null): string {
  if (!at || !Number.isFinite(Date.parse(at))) return "Time unrecorded";
  return new Date(at).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function relationKind(workflow: {
  schema_version?: string;
  parent_workflow_id?: string | null;
  revision?: { parent?: string } | null;
}): "revision" | "fresh" | "unknown" {
  if (!workflow.parent_workflow_id) return "unknown";
  if (workflow.revision?.parent === workflow.parent_workflow_id)
    return "revision";
  if (workflow.schema_version === "2.0" && !workflow.revision) return "fresh";
  return "unknown";
}

const prose = (value: unknown): string =>
  typeof value === "string" || typeof value === "number" ? String(value) : "";
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const positiveLine = (value: unknown): number | undefined => {
  if (typeof value !== "number" && typeof value !== "string") return undefined;
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : undefined;
};

export type ReviewFinding = {
  title: string;
  body: string;
  severity: string;
  severityClass: "urgent" | "warning" | "info";
  file: string;
  line?: number;
  endLine?: number;
};

/** Provider findings are display data; never treat them as HTML or filesystem paths. */
export function normalizeFinding(value: unknown, index = 0): ReviewFinding {
  const finding = record(value);
  const location = record(finding.location || finding.code_location);
  const range = record(finding.line_range || location.line_range);
  const severity = prose(finding.priority || finding.severity) || "Finding";
  const line = positiveLine(
    finding.line ||
      finding.start_line ||
      location.line ||
      location.start_line ||
      range.start,
  );
  const endLine = positiveLine(
    finding.end_line || location.end_line || range.end,
  );
  return {
    title: prose(finding.title) || `Finding ${index + 1}`,
    body:
      prose(
        finding.body ||
          finding.description ||
          finding.explanation ||
          finding.message,
      ) ||
      prose(value) ||
      "No explanation recorded.",
    severity,
    severityClass: /^(p0|p1|critical|high|error|blocking)$/i.test(severity)
      ? "urgent"
      : /^(p2|medium|warning)$/i.test(severity)
        ? "warning"
        : "info",
    file: prose(
      finding.file ||
        finding.path ||
        location.file ||
        location.path ||
        location.absolute_file_path,
    ),
    line,
    endLine: endLine && line && endLine >= line ? endLine : undefined,
  };
}

export type FindingDestination = {
  path?: string;
  page: number;
  row?: number;
  notice: string;
};

/** Resolve only against files already present in the authorized saved diff. */
export function locateFinding(
  files: DiffFile[],
  finding: Pick<ReviewFinding, "file" | "line">,
  workspace = "",
  pageSize = 400,
): FindingDestination {
  const missing = {
    page: 0,
    notice:
      "This file is not in the recorded candidate diff. It may be unchanged, missing or outside the recorded patch.",
  };
  if (!finding.file)
    return {
      page: 0,
      notice: "No file location was recorded for this finding.",
    };
  const normalized = finding.file.replaceAll("\\", "/").replace(/^\.\//, "");
  const root = workspace.replaceAll("\\", "/").replace(/\/$/, "");
  const path =
    root && normalized.startsWith(root + "/")
      ? normalized.slice(root.length + 1)
      : normalized;
  const exact = files.filter(
    (file) => file.path === path || file.previousPath === path,
  );
  const matches = exact.length
    ? exact
    : files.filter(
        (file) =>
          file.path === path.replace(/^[ab]\//, "") ||
          file.previousPath === path.replace(/^[ab]\//, ""),
      );
  if (matches.length !== 1) return missing;
  const file = matches[0];
  const deleted = file.lines.some((line) => line.text === "+++ /dev/null");
  const priorPath =
    file.previousPath !== file.path &&
    [path, path.replace(/^[ab]\//, "")].includes(file.previousPath || "");
  const oldSide = deleted || priorPath;
  if (!finding.line)
    return {
      path: file.path,
      page: 0,
      notice: "No line location was recorded. Showing the file's patch.",
    };
  const row = file.lines.findIndex((line) =>
    oldSide ? line.old === finding.line : line.next === finding.line,
  );
  if (row === -1)
    return {
      path: file.path,
      page: 0,
      notice: file.lines.some((line) =>
        /^(Binary files |GIT binary patch)/.test(line.text),
      )
        ? "This is a binary change; source line navigation is unavailable."
        : "This line is outside the recorded diff hunks or the patch is incomplete. Showing the file's patch.",
    };
  return {
    path: file.path,
    page: Math.floor(row / Math.max(1, pageSize)),
    row,
    notice: deleted
      ? "This file was deleted; showing its original line."
      : priorPath
        ? "This file was renamed; showing the line at its original path."
        : "",
  };
}
