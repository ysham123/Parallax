import { useEffect, useState, type FormEvent } from "react";
import { api, messageOf, viaMachine } from "./api";
import { planSummary, type PlanStatus } from "./plan";

/** Local plan and usage. Hidden when this build has no licensing configured. */
export function PlanSettings() {
  const [status, setStatus] = useState<PlanStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (viaMachine()) return;
    let alive = true;
    api<PlanStatus>("/license")
      .then((value) => alive && setStatus(value))
      .catch(() => alive && setStatus(null));
    return () => {
      alive = false;
    };
  }, []);
  if (!status?.licensing) return null;
  const summary = planSummary(status);
  const activate = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setStatus(
        await api<PlanStatus>("/license/activate", {
          method: "POST",
          body: JSON.stringify({ key: key.trim() }),
        }),
      );
      setKey("");
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      setStatus(await api<PlanStatus>("/license", { method: "DELETE" }));
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="studio-setting-row" aria-labelledby="plan-title">
      <div>
        <h2 id="plan-title">{summary.title}</h2>
        <p>{summary.detail}</p>
        {error && (
          <p className="plan-error" role="alert">
            {error}
          </p>
        )}
      </div>
      {status.plan === "pro" ? (
        <button className="secondary-button" disabled={busy} onClick={remove}>
          Remove license key
        </button>
      ) : (
        <form className="plan-activate" onSubmit={activate}>
          <label htmlFor="plan-key">License key</label>
          <input
            id="plan-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
          <button
            className="secondary-button"
            type="submit"
            disabled={busy || key.trim().length < 8}
          >
            Activate
          </button>
          {status.upgrade_url && (
            <a
              className="primary-button"
              href={status.upgrade_url}
              target="_blank"
              rel="noreferrer"
            >
              Upgrade to Pro
            </a>
          )}
        </form>
      )}
    </section>
  );
}
