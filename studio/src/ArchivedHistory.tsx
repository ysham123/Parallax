import { useEffect, useState } from "react";
import { messageOf, relayApi } from "./api";

type Archive = {
  id?: string;
  kind: "task" | "run" | "operation";
  worker: string;
  worker_name: string;
  project: string;
  archived_at: number;
  read_only: true;
  title?: string;
  requester?: string;
  actor?: string;
  status?: string;
  state?: string;
  candidate_digest?: string;
  diff_sha256?: string;
  checks_passed?: number;
  checks_total?: number;
  reviews_total?: number;
};
type Page = { items: Archive[]; next_cursor: number | null; has_more: boolean };

/** Revocation receipts are metadata only. They never become live task cards. */
export function ArchivedHistory() {
  const [rows, setRows] = useState<Archive[]>([]);
  const [cursor, setCursor] = useState<number | null>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [request, setRequest] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    void relayApi<Page>(`/executors/archives?cursor=${cursor || 0}&limit=50`, {
      signal: abort.signal,
    })
      .then((page) => {
        if (abort.signal.aborted) return;
        setRows((prior) => (cursor ? [...prior, ...page.items] : page.items));
        setCursor(page.has_more ? page.next_cursor : null);
      })
      .catch((failure) => {
        if (abort.signal.aborted) return;
        // A permission failure must not leave earlier project receipts visible.
        setRows([]);
        setCursor(0);
        setError(messageOf(failure));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
    // Pagination is explicit; changing the returned cursor does not fetch automatically.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);
  return (
    <section className="archived-history" aria-label="Archived records">
      <h1>Archived records</h1>
      <p>
        Read-only receipts from disconnected machines. Project code and full
        evidence remain on the machine. These records cannot be approved,
        resumed, applied or published.
      </p>
      {error && <p role="alert">Archived records are unavailable: {error}</p>}
      {loading && <p role="status">Loading archived records…</p>}
      {!loading && !error && !rows.length && (
        <p>
          No archived records are available for your current project
          permissions.
        </p>
      )}
      <ul>
        {rows.map((row, index) => (
          <li key={`${row.worker}:${row.kind}:${row.id || index}`}>
            <h2>
              {row.title ||
                `${row.kind[0].toUpperCase()}${row.kind.slice(1)} receipt`}
            </h2>
            <p>
              {row.worker_name} · {row.project}
            </p>
            <dl>
              <div>
                <dt>Recorded status</dt>
                <dd>{row.state || row.status || "Unrecorded"}</dd>
              </div>
              <div>
                <dt>Recorded actor</dt>
                <dd>{row.actor || row.requester || "Unrecorded"}</dd>
              </div>
              <div>
                <dt>Archived</dt>
                <dd>
                  <time
                    dateTime={new Date(row.archived_at * 1000).toISOString()}
                  >
                    {new Date(row.archived_at * 1000).toLocaleString()}
                  </time>
                </dd>
              </div>
              {row.checks_total !== undefined && (
                <div>
                  <dt>Recorded checks</dt>
                  <dd>
                    {row.checks_passed || 0} passed of {row.checks_total} ·{" "}
                    {row.reviews_total || 0} reviews
                  </dd>
                </div>
              )}
              {(row.candidate_digest || row.diff_sha256) && (
                <div>
                  <dt>Recorded digest</dt>
                  <dd>
                    <code>{row.candidate_digest || row.diff_sha256}</code>
                  </dd>
                </div>
              )}
            </dl>
            <small>
              Read-only · {row.kind} · {row.id || "Identity unrecorded"}
            </small>
          </li>
        ))}
      </ul>
      {!loading && (cursor !== null || error) && (
        <button
          className="secondary-button"
          onClick={() => setRequest((value) => value + 1)}
        >
          {error ? "Retry archived records" : "Load more archived records"}
        </button>
      )}
    </section>
  );
}
