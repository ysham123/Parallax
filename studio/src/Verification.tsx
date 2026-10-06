import { useEffect, useState } from "react";
import { api, messageOf } from "./api";
import type { RunResult } from "./types";

export type VerificationGate = {
  id: string;
  label: string;
  status: "passed" | "failed" | "unknown" | "not_requested";
  detail?: string;
};
type Receipt = {
  contract_version?: string;
  run_id: string;
  record_state?: "final" | "snapshot";
  outcome?: "applied" | "verified" | "partial";
  generated_at?: string;
  gates: VerificationGate[];
  artifacts?: Record<string, unknown>;
  limitations?: string[];
};
const display = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value);

export function Verification({ run }: { run: RunResult }) {
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    setReceipt(null);
    void api<Receipt>(`/runs/${encodeURIComponent(run.run_id)}/receipt`, {
      signal: abort.signal,
    })
      .then((value) => {
        if (!Array.isArray(value.gates))
          throw new Error("The verification record has no gate evidence.");
        setReceipt(value);
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setError(messageOf(failure));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [run.run_id, run.status, run.checks.length, run.reviews.length, revision]);
  const hashes = receipt?.artifacts
    ? Object.entries(receipt.artifacts).filter(
        ([key, value]) =>
          /sha256|hash|fingerprint/.test(key) &&
          typeof value === "string" &&
          value,
      )
    : [];
  return (
    <section
      className="verification-panel"
      aria-labelledby="verification-title"
      aria-busy={loading}
    >
      <div className="verification-heading">
        <div>
          <span className="eyebrow">RECORDED EVIDENCE</span>
          <h2 id="verification-title">Verification record</h2>
          <p>The runtime’s gate outcomes for this run.</p>
          {receipt && (
            <div className="verification-record-meta">
              <span className="verification-record-state">
                {receipt.record_state === "final"
                  ? "Final record"
                  : "Evidence snapshot"}
              </span>
              <span>
                {receipt.outcome === "applied"
                  ? "Integration applied"
                  : receipt.outcome === "verified"
                    ? "Verification recorded"
                    : "Partial evidence"}
              </span>
              {receipt.generated_at && (
                <time dateTime={receipt.generated_at}>
                  Generated{" "}
                  {new Date(receipt.generated_at).toLocaleString([], {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </time>
              )}
            </div>
          )}
        </div>
        {receipt && (
          <div className="verification-downloads">
            <a
              className="secondary-button"
              href={`/api/runs/${encodeURIComponent(run.run_id)}/receipt`}
              download={`parallax-${run.run_id}-verification.json`}
            >
              Download JSON <span aria-hidden="true">↓</span>
            </a>
            <a
              className="secondary-button"
              href={`/api/runs/${encodeURIComponent(run.run_id)}/patch`}
              download={`parallax-${run.run_id}.patch`}
            >
              Download patch <span aria-hidden="true">↓</span>
            </a>
          </div>
        )}
      </div>
      {loading ? (
        <p className="verification-loading" role="status">
          Loading the recorded verification gates…
        </p>
      ) : error ? (
        <div className="verification-unavailable">
          <p>Verification record unavailable.</p>
          <span>{error}</span>
          <button
            className="secondary-button"
            onClick={() => setRevision((v) => v + 1)}
          >
            Try again
          </button>
        </div>
      ) : (
        receipt && (
          <>
            <div className="verification-gates">
              {receipt.gates.map((gate) => (
                <article
                  key={gate.id}
                  className={`verification-gate ${gate.status}`}
                >
                  <span className="verification-gate-icon" aria-hidden="true">
                    {gate.status === "passed"
                      ? "✓"
                      : gate.status === "failed"
                        ? "×"
                        : gate.status === "not_requested"
                          ? "−"
                          : "?"}
                  </span>
                  <div>
                    <h3>{gate.label}</h3>
                    <span className="verification-gate-status">
                      {gate.status.replaceAll("_", " ")}
                    </span>
                    {gate.detail && <p>{gate.detail}</p>}
                  </div>
                </article>
              ))}
            </div>
            {hashes.length > 0 && (
              <details className="verification-hashes">
                <summary>
                  Artifact fingerprints <span>SHA-256 evidence</span>
                </summary>
                <dl>
                  {hashes.map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll("_", " ")}</dt>
                      <dd>
                        <code>{display(value)}</code>
                      </dd>
                    </div>
                  ))}
                </dl>
              </details>
            )}
            <p className="verification-footnote">
              Evidence is scoped to this run and the recorded project checks.
            </p>
            {Array.isArray(receipt.limitations) &&
              receipt.limitations.length > 0 && (
                <div className="verification-limitations">
                  <span className="eyebrow">RECORD COVERAGE</span>
                  <ul>
                    {receipt.limitations.map((limitation, index) => (
                      <li key={index}>{limitation}</li>
                    ))}
                  </ul>
                </div>
              )}
          </>
        )
      )}
    </section>
  );
}
