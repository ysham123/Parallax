import { useEffect, useState } from "react";
import { api, messageOf } from "./api";
import {
  connectionProvider,
  type CheckSpec,
  type Connection,
  type Provider,
  type RunSpec,
} from "./types";

type Assessment = {
  status: string;
  git: boolean;
  execution: { enforced: boolean; backend: string | null };
  packages: { root: string; kind: string; setup: string; manager: string }[];
  instructions: string[];
  proposed_checks: CheckSpec[];
  issues: { category?: string; severity: string; message: string }[];
};
type ProjectProfile = {
  name: string;
  profile: { workspace: string; package_roots: string[]; checks: CheckSpec[] };
};
export function ProjectReadiness({
  spec,
  onChange,
  providers,
  connections,
}: {
  spec: RunSpec;
  onChange: (spec: RunSpec) => void;
  providers: Provider[];
  connections: Connection[];
}) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [profiles, setProfiles] = useState<ProjectProfile[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [rootsDraft, setRootsDraft] = useState(
    (spec.package_roots || []).join(", "),
  );
  useEffect(
    () => setRootsDraft((spec.package_roots || []).join(", ")),
    [spec.package_roots],
  );
  const request = JSON.stringify({
    workspace: spec.workspace,
    package_roots: spec.package_roots || [],
    checks: spec.checks,
    participants: [spec.coordinator, ...spec.team],
  });
  useEffect(() => {
    const abort = new AbortController();
    setAssessment(null);
    setError("");
    if (!spec.workspace.trim()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      void api<Assessment>("/project/assess", {
        method: "POST",
        body: request,
        signal: abort.signal,
      })
        .then(setAssessment)
        .catch((e) => {
          if (!abort.signal.aborted) setError(messageOf(e));
        })
        .finally(() => {
          if (!abort.signal.aborted) setLoading(false);
        });
    }, 450);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [request, revision, spec.workspace]);
  useEffect(() => {
    const abort = new AbortController();
    void api<ProjectProfile[]>("/project-profiles", { signal: abort.signal })
      .then(setProfiles)
      .catch((e) => {
        if (!abort.signal.aborted) setError(messageOf(e));
      });
    return () => abort.abort();
  }, []);
  const unavailable = spec.team.filter(
    (p) =>
      !["ready", "configured"].includes(
        connectionProvider(p, providers, connections)?.status || "",
      ),
  );
  const visibleIssues =
    assessment?.issues.filter(
      (issue) =>
        spec.mode !== "review" ||
        issue.category === "provider_permission" ||
        issue.severity === "warning",
    ) || [];
  const ready =
    assessment && !visibleIssues.some((issue) => issue.severity === "blocker");
  async function save() {
    if (!name.trim()) {
      setError("Give the project profile a name.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api(`/project-profiles/${encodeURIComponent(name.trim())}`, {
        method: "PUT",
        body: JSON.stringify({
          workspace: spec.workspace,
          package_roots: spec.package_roots || [],
          checks: spec.checks.length
            ? spec.checks
            : assessment?.proposed_checks || [],
        }),
      });
      setProfiles(await api<ProjectProfile[]>("/project-profiles"));
      setName("");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section
      className="project-readiness"
      aria-labelledby="readiness-title"
      aria-busy={loading}
    >
      <div className="readiness-heading">
        <div>
          <span className="eyebrow">PROJECT PREFLIGHT</span>
          <h2 id="readiness-title">Ready for real work</h2>
          <p>Confirm the environment and checks before agents start.</p>
        </div>
        <button
          className="secondary-button small"
          onClick={() => setRevision((v) => v + 1)}
          disabled={loading || !spec.workspace}
        >
          Refresh
        </button>
      </div>
      {loading ? (
        <p role="status">
          Inspecting packages, checks and selected connections…
        </p>
      ) : error ? (
        <p role="alert" className="readiness-error">
          {error}
        </p>
      ) : assessment ? (
        <>
          <div className="readiness-facts">
            <span className={ready ? "ready" : "blocked"}>
              {ready ? "Ready to start" : "Setup needs attention"}
            </span>
            <span>{assessment.git ? "Git snapshot" : "Consultation only"}</span>
            <span>
              {assessment.execution.enforced
                ? `${assessment.execution.backend} isolation`
                : "Sandbox unavailable"}
            </span>
            <span>
              {assessment.packages.length} package
              {assessment.packages.length === 1 ? "" : "s"}
            </span>
            <span>
              {spec.checks.length || assessment.proposed_checks.length}{" "}
              {spec.mode === "review" ? "suggested" : "required"} checks
            </span>
          </div>
          {visibleIssues.length > 0 && (
            <ul className="readiness-issues">
              {visibleIssues.map((issue, i) => (
                <li key={i} className={issue.severity}>
                  {issue.message}
                </li>
              ))}
            </ul>
          )}
          {unavailable.length > 0 && (
            <button
              className="secondary-button small"
              onClick={() =>
                onChange({
                  ...spec,
                  team: spec.team.filter((p) => !unavailable.includes(p)),
                })
              }
            >
              Remove {unavailable.length} unavailable participant
              {unavailable.length === 1 ? "" : "s"}
            </button>
          )}
          <p className="readiness-note">
            Start with one implementer and an independent reviewer. Your
            coordinator can review when it did not implement the candidate.
          </p>
          <details>
            <summary>Packages, project instructions & check plan</summary>
            <div className="readiness-package-list">
              {assessment.packages.map((p) => (
                <article key={p.root}>
                  <code>{p.root}</code>
                  <span>
                    {p.kind} · {p.manager || "manual"}
                  </span>
                  <small>{p.setup}</small>
                </article>
              ))}
            </div>
            {assessment.instructions.length > 0 && (
              <p className="readiness-note">
                Instructions: {assessment.instructions.join(", ")}
              </p>
            )}
            <ul className="readiness-checks">
              {(spec.checks.length
                ? spec.checks
                : assessment.proposed_checks
              ).map((c, i) => (
                <li key={i}>
                  <strong>{c.name}</strong>
                  <code>
                    {c.cwd || "."} → {c.argv.join(" ")}
                  </code>
                </li>
              ))}
            </ul>
            {!spec.checks.length && assessment.proposed_checks.length > 0 && (
              <button
                className="secondary-button small"
                onClick={() =>
                  onChange({ ...spec, checks: assessment.proposed_checks })
                }
              >
                Use detected checks
              </button>
            )}
          </details>
        </>
      ) : (
        <p className="readiness-note">
          Link a project to inspect its readiness. Review can run without Git.
        </p>
      )}
      <details className="project-profile-settings">
        <summary>Reusable project setup</summary>
        <div className="project-profile-grid">
          <label>
            Package roots{" "}
            <small>Comma separated; empty discovers packages</small>
            <input
              aria-label="Package roots"
              placeholder="api, web"
              value={rootsDraft}
              onChange={(e) => setRootsDraft(e.target.value)}
              onBlur={() =>
                onChange({
                  ...spec,
                  package_roots: rootsDraft
                    .split(",")
                    .map((v) => v.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            Saved project profile
            <select
              aria-label="Saved project profile"
              defaultValue=""
              onChange={(e) => {
                const p = profiles.find((p) => p.name === e.target.value);
                if (p)
                  onChange({
                    ...spec,
                    workspace: p.profile.workspace,
                    package_roots: p.profile.package_roots,
                    checks: p.profile.checks,
                  });
                e.target.value = "";
              }}
            >
              <option value="">Choose project setup</option>
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Project profile name
            <input
              aria-label="Project profile name"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button
            className="secondary-button small"
            disabled={saving || loading || !spec.workspace}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save project setup"}
          </button>
        </div>
      </details>
    </section>
  );
}
