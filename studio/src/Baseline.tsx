import type { Data, RunResult } from "./types";
const label = (value: unknown) => (typeof value === "string" ? value : "");
export function Baseline({ run }: { run: RunResult }) {
  const baseline = Array.isArray(run.artifacts.baseline_checks)
    ? (run.artifacts.baseline_checks as Data[])
    : [];
  if (!baseline.length)
    return (
      <p className="readiness-note">
        Baseline evidence was not recorded for this run.
      </p>
    );
  return (
    <section className="baseline-panel" aria-labelledby="baseline-title">
      <div className="readiness-heading">
        <div>
          <span className="eyebrow">BEFORE & AFTER</span>
          <h2 id="baseline-title">Project check comparison</h2>
          <p>Every required check must pass on the combined candidate.</p>
        </div>
      </div>
      <div className="baseline-table">
        <table>
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Baseline</th>
              <th scope="col">Final candidate</th>
            </tr>
          </thead>
          <tbody>
            {baseline.map((b, i) => {
              const final = run.checks.find(
                (c) =>
                  JSON.stringify(c.argv) === JSON.stringify(b.argv) &&
                  (c.cwd || ".") === (b.cwd || "."),
              );
              return (
                <tr key={i}>
                  <th scope="row">
                    {label(b.name)}
                    <small>{label(b.cwd) || "."}</small>
                  </th>
                  <td className={b.ok ? "passed" : "failed"}>
                    {b.ok ? "Passed" : "Failed"}
                    {typeof b.elapsed_seconds === "number" && (
                      <small>{b.elapsed_seconds}s</small>
                    )}
                  </td>
                  <td className={final ? (final.ok ? "passed" : "failed") : ""}>
                    {final ? (final.ok ? "Passed" : "Failed") : "Pending"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <details>
        <summary>Baseline command output & environment</summary>
        {baseline.map((b, i) => (
          <article key={i}>
            <strong>{label(b.name)}</strong>
            <pre>{label(b.output) || "No output reported."}</pre>
            <code>{JSON.stringify(b.environment || {})}</code>
          </article>
        ))}
      </details>
    </section>
  );
}
