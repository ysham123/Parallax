import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, messageOf } from "./api";
import type { Workflow } from "./Workflows";
import type { Data, RunResult } from "./types";
import { nullableNumber, observationOf } from "./evidence-presentation";

const OUTCOMES = [
  "accepted",
  "rejected",
  "failed",
  "timed_out",
  "cancelled",
  "blocked",
] as const;
const APPROACHES = [
  ["parallax", "Parallax"],
  ["single_agent", "One native agent"],
  ["fresh_same_provider", "Writer + fresh reviewer, same provider"],
  ["fresh_cross_provider", "Writer + fresh reviewer, another provider"],
  ["worktree_script", "Worktree and review script"],
  ["close_product", "Another coding product"],
] as const;
type ProviderEntry = {
  provider: string;
  model: string;
  effort: string;
  transport: string;
};
type Measurements = {
  duration: string;
  human: string;
  setup: string;
  review: string;
  interventions: string;
  cost: string;
  minutes: string;
  workers: string;
  repairs: string;
};
type ReportObservation = Data & {
  workflow_id: string;
  kind: "check" | "review";
  name?: string | null;
  provider?: string | null;
  phase?: string;
  outcome?: string;
  summary?: string | null;
  legacy?: boolean;
};
const EMPTY: Measurements = {
  duration: "",
  human: "",
  setup: "",
  review: "",
  interventions: "",
  cost: "",
  minutes: "",
  workers: "",
  repairs: "",
};

export function PilotMetrics({ workflow }: { workflow: Workflow | null }) {
  const [values, setValues] = useState<Measurements>({ ...EMPTY });
  const [approach, setApproach] = useState("parallax");
  const [outcome, setOutcome] = useState("blocked");
  const [comparison, setComparison] = useState("");
  const [order, setOrder] = useState("first");
  const [baseline, setBaseline] = useState("");
  const [baselineScheme, setBaselineScheme] = useState("");
  const [assessmentMethod, setAssessmentMethod] =
    useState("participant_report");
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [features, setFeatures] = useState<string[] | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [reportedObservations, setReportedObservations] = useState<
    ReportObservation[] | null
  >(null);
  const [observationWarning, setObservationWarning] = useState("");
  const [selectedObservation, setSelectedObservation] = useState("");
  const [classification, setClassification] = useState("unresolved");
  const [findingIndex, setFindingIndex] = useState("");
  const [comment, setComment] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const pendingLabel = useRef<{ signature: string; id: string } | null>(null);
  useEffect(() => {
    setValues({ ...EMPTY });
    setComparison(crypto.randomUUID());
    setOrder("first");
    setBaseline("");
    setBaselineScheme("");
    setAssessmentMethod("participant_report");
    setOutcome("blocked");
    setApproach("parallax");
    setRun(null);
    setSelectedObservation("");
    setFindingIndex("");
    setClassification("unresolved");
    setComment("");
    setNotice("");
    setProviders(
      (workflow?.spec
        ? [workflow.spec.coordinator, ...workflow.spec.team]
        : []
      ).map((p) => ({
        provider: p.provider,
        model: p.model || "",
        effort: p.effort || "",
        transport: p.transport || "cli",
      })),
    );
    pending.current = null;
    pendingLabel.current = null;
  }, [workflow?.id]);
  useEffect(() => {
    const abort = new AbortController();
    setFeatures(null);
    setRun(null);
    setReportedObservations(null);
    setObservationWarning("");
    void api<{ pilot_features?: string[] }>("/context", {
      signal: abort.signal,
    })
      .then(async (value) => {
        if (abort.signal.aborted) return;
        const supported = Array.isArray(value?.pilot_features)
          ? value.pilot_features
          : [];
        setFeatures(supported);
        if (supported.includes("pilot-observations-v1") && workflow) {
          try {
            const report = await api<{
              evidence_observations?: ReportObservation[];
              evidence_observations_truncated?: boolean;
              evidence_warnings?: { workflow_id: string; code: string }[];
            }>("/pilot/report", { signal: abort.signal });
            if (abort.signal.aborted) return;
            if (Array.isArray(report.evidence_observations))
              setReportedObservations(
                report.evidence_observations.filter(
                  (row) => row.workflow_id === workflow.id,
                ),
              );
            if (report.evidence_observations_truncated)
              setObservationWarning(
                "The report observation list is capped. Some historical observations are not shown.",
              );
            if (
              report.evidence_warnings?.some(
                (warning) => warning.workflow_id === workflow.id,
              )
            )
              setObservationWarning(
                "The observation journal could not be validated. Unsafe historical evidence is unavailable.",
              );
          } catch (error) {
            if (!abort.signal.aborted)
              setObservationWarning(
                `Historical observation list unavailable: ${messageOf(error)}. Only observations in the current saved result are shown.`,
              );
          }
        }
      })
      .catch((error) => {
        if (!abort.signal.aborted) {
          setFeatures([]);
          setNotice(messageOf(error));
        }
      });
    if (workflow?.run_id)
      void api<RunResult>(`/runs/${encodeURIComponent(workflow.run_id)}`, {
        signal: abort.signal,
      })
        .then((value) => {
          if (!abort.signal.aborted) setRun(value);
        })
        .catch((error) => {
          if (!abort.signal.aborted)
            setNotice(`Observation evidence unavailable: ${messageOf(error)}`);
        });
    return () => abort.abort();
  }, [workflow?.id, workflow?.run_id, retry]);
  const canMeasure = features?.includes("pilot-evaluation-v1") === true;
  const canLabel = features?.includes("pilot-observations-v1") === true;
  const evidence = (
    reportedObservations ?? [
      ...(run?.checks || []),
      ...(run?.reviews || []),
      ...(Array.isArray(run?.artifacts?.baseline_checks)
        ? (run.artifacts.baseline_checks as Data[])
        : []),
    ]
  )
    .map((row) => ({ row, observation: observationOf(row) }))
    .filter((value) => value.observation);
  const observations = [
    ...new Map(
      evidence.map((value) => [value.observation!.id, value]),
    ).values(),
  ];
  const selectedEvidence = observations.find(
    (value) => value.observation!.id === selectedObservation,
  );
  const findings = Array.isArray(selectedEvidence?.row.findings)
    ? selectedEvidence.row.findings.slice(0, 50).map((value, index) => {
        const finding =
          value && typeof value === "object"
            ? (value as Data)
            : { title: String(value), summary: String(value) };
        return {
          index:
            selectedEvidence?.row.kind === "review" &&
            typeof finding.index === "number"
              ? finding.index
              : index,
          title: String(finding.title || `Finding ${index + 1}`),
          summary: String(
            finding.summary || finding.body || finding.explanation || "",
          ),
        };
      })
    : [];
  const numberField = (
    key: keyof Measurements,
    label: string,
    max: number,
    integer = false,
    min = 0,
  ) => (
    <label>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={integer ? "1" : "any"}
        value={values[key]}
        onChange={(e) =>
          setValues((previous) => ({ ...previous, [key]: e.target.value }))
        }
        placeholder="Unknown"
      />
    </label>
  );
  async function download() {
    setBusy(true);
    setNotice("");
    try {
      const report = await api("/pilot/report");
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "parallax-pilot-report.json";
      link.click();
      URL.revokeObjectURL(url);
      setNotice(
        "Report downloaded. Participant-reported measurements are separate from recorded runtime evidence; missing cost remains unknown.",
      );
    } catch (error) {
      setNotice(messageOf(error));
    } finally {
      setBusy(false);
    }
  }
  async function measure(event: FormEvent) {
    event.preventDefault();
    if (!workflow || busy || !canMeasure) return;
    if (
      !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(comparison) ||
      (baseline && !/^[a-f0-9]{64}$/.test(baseline))
    ) {
      setNotice(
        "Use a valid comparison ID and a recorded baseline SHA-256, or leave the baseline unknown.",
      );
      return;
    }
    if (
      Object.values(values).some(
        (value) => value.trim() && nullableNumber(value) === null,
      )
    ) {
      setNotice(
        "Measurements must be non-negative numbers or blank for unknown.",
      );
      return;
    }
    const body = {
      workflow_id: workflow.id,
      approach,
      accepted: outcome === "accepted",
      duration_seconds: nullableNumber(values.duration),
      interventions: nullableNumber(values.interventions),
      provider_cost_usd: nullableNumber(values.cost),
      evaluation: {
        schema_version: "1.0",
        comparison_id: comparison,
        order,
        outcome,
        active_human_seconds: nullableNumber(values.human),
        setup_seconds: nullableNumber(values.setup),
        review_seconds: nullableNumber(values.review),
        observed_baseline_sha256: baseline || null,
        observed_baseline_scheme: baselineScheme || null,
        assessment_method: assessmentMethod,
        providers: providers
          .filter((p) => p.provider.trim())
          .map((p) => ({
            provider: p.provider.trim(),
            model: p.model || null,
            effort: p.effort || null,
            transport: p.transport || null,
          })),
        budget: {
          minutes: nullableNumber(values.minutes),
          workers: nullableNumber(values.workers),
          repairs: nullableNumber(values.repairs),
        },
        provider_usage: [],
      },
    };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature)
      pending.current = { signature, id: crypto.randomUUID() };
    setBusy(true);
    setNotice("");
    try {
      const result = await api<{ comparability?: { baseline?: string } }>(
        "/pilot/benchmark",
        {
          method: "POST",
          body: JSON.stringify({ ...body, request_id: pending.current.id }),
        },
      );
      pending.current = null;
      setNotice(
        `Participant-reported comparison recorded. Baseline: ${result.comparability?.baseline || "unverified"}. Actual execution and equal budgets are not independently verified.`,
      );
    } catch (error) {
      setNotice(messageOf(error));
    } finally {
      setBusy(false);
    }
  }
  async function labelObservation(event: FormEvent) {
    event.preventDefault();
    const selected = observations.find(
      (value) => value.observation!.id === selectedObservation,
    )?.observation;
    if (!workflow || !selected || busy || !canLabel) return;
    const body = {
      workflow_id: workflow.id,
      observation_id: selected.id,
      content_sha256: selected.content_sha256,
      finding_index: findingIndex === "" ? null : Number(findingIndex),
      classification,
      comment,
    };
    const signature = JSON.stringify(body);
    if (pendingLabel.current?.signature !== signature)
      pendingLabel.current = { signature, id: crypto.randomUUID() };
    setBusy(true);
    setNotice("");
    try {
      await api("/pilot/observations", {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: pendingLabel.current.id }),
      });
      pendingLabel.current = null;
      setNotice(
        "Human assessment recorded against this observation. It does not change runtime checks, approval or delivery.",
      );
    } catch (error) {
      setNotice(messageOf(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="pilot-metrics">
      <summary>Pilot measurements &amp; human assessments</summary>
      <p>
        Runtime evidence and participant-reported measurements are recorded
        separately. Blank fields mean unknown, including provider cost. Count
        failed and interrupted attempts as well as accepted work.
      </p>
      <button
        className="secondary-button"
        disabled={busy}
        onClick={() => void download()}
      >
        Download pilot report
      </button>
      {features === null ? (
        <p role="status">Checking worker measurement capabilities…</p>
      ) : (
        (!canMeasure || !canLabel) && (
          <p className="pilot-update-notice">
            This worker does not support all versioned measurements and
            observation labels. Update the pilot worker, then{" "}
            <button
              className="text-button"
              onClick={() => setRetry((value) => value + 1)}
            >
              recheck capabilities
            </button>
            . Existing evidence remains available.
          </p>
        )
      )}
      {workflow && canMeasure && (
        <form
          onSubmit={(event) => void measure(event)}
          aria-label="Participant-reported comparison"
        >
          <h3>Record a comparison attempt</h3>
          <p>
            Use the same task contract and recorded starting state for both
            attempts. Reuse the comparison ID for the paired attempt. A matching
            reported baseline is a participant claim, not independently verified
            execution.
          </p>
          <div className="pilot-fields">
            <label>
              Approach
              <select
                value={approach}
                onChange={(e) => setApproach(e.target.value)}
              >
                {APPROACHES.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Outcome
              <select
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
              >
                {OUTCOMES.map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Paired comparison ID
              <input
                value={comparison}
                onChange={(e) => setComparison(e.target.value)}
                required
              />
            </label>
            <label>
              Attempt order
              <select value={order} onChange={(e) => setOrder(e.target.value)}>
                <option value="first">First</option>
                <option value="second">Second</option>
              </select>
            </label>
            <label>
              Observed baseline fingerprint
              <input
                value={baseline}
                onChange={(e) => setBaseline(e.target.value)}
                placeholder="Unknown; workspace SHA-256, not Git commit"
                pattern="[a-f0-9]{64}"
              />
            </label>
            <label>
              Baseline fingerprint scheme
              <select
                value={baselineScheme}
                onChange={(e) => setBaselineScheme(e.target.value)}
              >
                <option value="">Unknown</option>
                <option value="managed-workspace-state-v1">
                  Captured project snapshot
                </option>
                <option value="readonly-workspace-state-v1">
                  Read-only observation workspace
                </option>
                <option value="git-tree-v1">Git tree</option>
              </select>
            </label>
            <label>
              Outcome assessment
              <select
                value={assessmentMethod}
                onChange={(e) => setAssessmentMethod(e.target.value)}
              >
                <option value="participant_report">Participant report</option>
                <option value="independent_assessment">
                  Independent assessment
                </option>
                <option value="behavioral_holdout">
                  Behavioral holdout checks
                </option>
              </select>
            </label>
            {numberField("duration", "Elapsed attempt time, seconds", 86400)}
            {numberField(
              "human",
              "Total active developer time, seconds",
              86400,
            )}
            {numberField(
              "setup",
              "Setup time within that total, seconds",
              86400,
            )}
            {numberField(
              "review",
              "Human review time within that total, seconds",
              86400,
            )}
            {numberField("interventions", "Human interventions", 10000, true)}
            {numberField("cost", "Observed provider cost, USD", 10000)}
          </div>
          <p>
            Elapsed attempt time uses the agreed end-to-end boundary and
            includes waiting, corrections and review. Total active developer
            time measures your attention separately.
          </p>
          <details>
            <summary>Actual providers &amp; configured budget</summary>
            <p>
              Defaults show this task’s saved settings. Correct them to the
              configuration actually used for this comparison attempt. Leave
              unmeasured values blank.
            </p>
            {providers.map((provider, index) => (
              <div className="pilot-provider" key={index}>
                {(["provider", "model", "effort"] as const).map((key) => (
                  <label key={key}>
                    {key}
                    <input
                      value={provider[key]}
                      onChange={(e) =>
                        setProviders((previous) =>
                          previous.map((value, i) =>
                            i === index
                              ? { ...value, [key]: e.target.value }
                              : value,
                          ),
                        )
                      }
                    />
                  </label>
                ))}
                <label>
                  Transport
                  <select
                    value={provider.transport}
                    onChange={(e) =>
                      setProviders((previous) =>
                        previous.map((value, i) =>
                          i === index
                            ? { ...value, transport: e.target.value }
                            : value,
                        ),
                      )
                    }
                  >
                    <option value="">Unknown</option>
                    <option value="cli">CLI</option>
                    <option value="api">API</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    setProviders((previous) =>
                      previous.filter((_, i) => i !== index),
                    )
                  }
                >
                  Remove provider
                </button>
              </div>
            ))}
            <button
              type="button"
              className="secondary-button"
              disabled={providers.length >= 9}
              onClick={() =>
                setProviders((previous) => [
                  ...previous,
                  { provider: "", model: "", effort: "", transport: "" },
                ])
              }
            >
              Add provider
            </button>
            <div className="pilot-fields">
              {numberField(
                "minutes",
                "Execution budget, minutes",
                240,
                true,
                1,
              )}
              {numberField("workers", "Worker limit", 8, true, 1)}
              {numberField("repairs", "Repair limit", 5, true)}
            </div>
          </details>
          <button className="secondary-button" disabled={busy}>
            Record participant-reported comparison
          </button>
        </form>
      )}
      {workflow && canLabel && (
        <form
          onSubmit={(event) => void labelObservation(event)}
          aria-label="Human observation assessment"
        >
          <h3>Assess a recorded observation</h3>
          <p>
            Labels are a human assessment. They do not establish review quality
            or override acceptance gates. Historical failed observations may
            remain outside the current result.
          </p>
          {observationWarning && <p role="status">{observationWarning}</p>}
          {observations.length ? (
            <>
              <label>
                Observation
                <select
                  value={selectedObservation}
                  onChange={(e) => {
                    setSelectedObservation(e.target.value);
                    setFindingIndex("");
                  }}
                  required
                >
                  <option value="">Choose an observation</option>
                  {observations.map(({ row, observation }, index) => (
                    <option key={observation!.id} value={observation!.id}>
                      {index + 1}. {observation!.phase} ·{" "}
                      {String(row.name || row.provider || "observation")} ·{" "}
                      {String(row.outcome || "recorded outcome")}
                      {row.legacy ? " · legacy binding unrecorded" : ""}
                    </option>
                  ))}
                </select>
              </label>
              {!!findings.length && (
                <label>
                  Finding to assess
                  <select
                    value={findingIndex}
                    onChange={(e) => setFindingIndex(e.target.value)}
                  >
                    <option value="">Whole observation</option>
                    {findings.map((finding) => (
                      <option key={finding.index} value={finding.index}>
                        {finding.index + 1}. {finding.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {findingIndex !== "" && (
                <p>
                  {findings.find(
                    (finding) => finding.index === Number(findingIndex),
                  )?.summary ||
                    "No additional finding explanation was recorded."}
                </p>
              )}
              {selectedObservation && (
                <details>
                  <summary>Selected observation record</summary>
                  {observations
                    .filter(
                      (value) => value.observation!.id === selectedObservation,
                    )
                    .map(({ row, observation }) => (
                      <div key={observation!.id}>
                        {!!row.summary && <p>{String(row.summary)}</p>}
                        <code>{observation!.id}</code>
                        <br />
                        <code>{observation!.content_sha256}</code>
                      </div>
                    ))}
                </details>
              )}
              <label>
                Human assessment
                <select
                  value={classification}
                  onChange={(e) => setClassification(e.target.value)}
                >
                  <option value="confirmed_defect">Confirmed defect</option>
                  <option value="false_alarm">False alarm</option>
                  <option value="unresolved">Unresolved</option>
                  <option value="escape">Escaped defect</option>
                </select>
              </label>
              <label>
                Evidence or explanation
                <textarea
                  value={comment}
                  maxLength={4000}
                  onChange={(e) => setComment(e.target.value)}
                />
              </label>
              <button
                className="secondary-button"
                disabled={busy || !selectedObservation}
              >
                Record human assessment
              </button>
            </>
          ) : (
            <p>
              No labelable observation identities are present in this saved
              result. Legacy rows cannot be relabelled as bound evidence.
            </p>
          )}
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
    </details>
  );
}
