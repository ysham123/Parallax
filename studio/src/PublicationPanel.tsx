import { useEffect, useRef, useState } from "react";
import { api, relayApi, messageOf, viaMachine } from "./api";
import type { Workflow } from "./Workflows";
import "./pilot.css";
type Publication = {
  url: string;
  pr: number;
  branch: string;
  commit: string;
  repository: string;
};
type PendingPublication = Publication & {
  state: string;
  can_retry: boolean;
  request: {
    workflow: string;
    binding: string;
    candidate_digest: string;
    title: string;
    description: string;
    request_id: string;
  };
};
const safeLink = (url: string | undefined) =>
  url && /^https?:\/\//i.test(url) ? url : undefined;
type Feedback = {
  url: string;
  external_change: boolean;
  refreshed_at?: number;
  incomplete?: boolean;
  feedback_errors?: Record<string, string>;
  page_counts?: Record<string, number>;
  checks: {
    id: number;
    name: string;
    status: string;
    conclusion: string;
    html_url: string;
  }[];
  comments: {
    id: number;
    path: string;
    line?: number;
    body: string;
    html_url: string;
  }[];
  reviews: { id: number; state: string; body: string; html_url: string }[];
  statuses: {
    id: number;
    context: string;
    state: string;
    target_url: string;
  }[];
};
export function PublicationPanel({
  workflow,
  canDeliver,
  onChanged,
  onFeedback,
}: {
  workflow: Workflow;
  canDeliver: boolean;
  onChanged: () => void;
  onFeedback: (message: string) => void;
}) {
  const [preview, setPreview] = useState<{
    repository: string;
    base: string;
    branch: string;
  } | null>(null);
  const [title, setTitle] = useState(workflow.title);
  const [description, setDescription] = useState(
    workflow.original_goal || workflow.prompt || "",
  );
  const [result, setResult] = useState<Publication | null>(
    workflow.publication || null,
  );
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState<PendingPublication | null>(null);
  const [recovering, setRecovering] = useState(
    !!workflow.github_target && viaMachine(),
  );
  const [recoveryChecked, setRecoveryChecked] = useState(
    !workflow.github_target || !viaMachine(),
  );
  const [recoveryVersion, setRecoveryVersion] = useState(0);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  useEffect(() => {
    setResult(workflow.publication || null);
  }, [workflow.publication]);
  useEffect(() => {
    if (!workflow.github_target || !viaMachine()) return;
    let active = true;
    setRecovering(true);
    setRecoveryChecked(false);
    setRecovery(null);
    void relayApi<PendingPublication | null>(
      `/github/publication/${workflow.id}`,
    )
      .then((value) => {
        if (!active) return;
        setRecoveryChecked(true);
        if (!value) return;
        setRecovery(value);
        if (value.state === "published" && workflow.publication)
          setResult(value);
        if (!workflow.publication) {
          setTitle(value.request.title);
          setDescription(value.request.description);
        }
      })
      .catch((e) => {
        if (active) setError(messageOf(e));
      })
      .finally(() => {
        if (active) setRecovering(false);
      });
    return () => {
      active = false;
    };
  }, [
    workflow.id,
    workflow.github_target?.id,
    workflow.publication?.commit,
    workflow.publication_operation,
    recoveryVersion,
  ]);
  if (
    !workflow.github_target ||
    !["approved", "published"].includes(workflow.status)
  )
    return null;
  async function inspect() {
    if (!workflow.candidate) return;
    setBusy(true);
    setError("");
    try {
      setPreview(
        await api(`/workflows/${workflow.id}/publication-preview`, {
          method: "POST",
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            candidate_digest: workflow.candidate.digest,
          }),
        }),
      );
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (
      !workflow.candidate ||
      busy ||
      recovering ||
      !recoveryChecked ||
      (recovery && !recovery.can_retry)
    )
      return;
    const body = {
      workflow: workflow.id,
      binding: workflow.github_target!.id,
      candidate_digest: workflow.candidate!.digest,
      title,
      description,
    };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature)
      pending.current = {
        signature,
        id: workflow.publication_operation || crypto.randomUUID(),
      };
    setBusy(true);
    setError("");
    try {
      const value = await relayApi<Publication>("/github/publish", {
        method: "POST",
        body: JSON.stringify(
          recovery?.can_retry
            ? recovery.request
            : { ...body, request_id: pending.current.id },
        ),
      });
      setResult(value);
      setRecovery(null);
      pending.current = null;
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setFeedback(await relayApi(`/github/feedback/${workflow.id}`));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="publication-panel" aria-label="GitHub delivery">
      <h3>Draft pull request</h3>
      {error && <p role="alert">{error}</p>}
      {recovering && <p role="status">Checking saved publication…</p>}
      {!recovering && !recoveryChecked && (
        <button
          className="secondary-button"
          onClick={() => setRecoveryVersion((v) => v + 1)}
        >
          Retry publication recovery check
        </button>
      )}
      {recovery && !workflow.publication && (
        <>
          <p>
            A saved publication needs reconciliation. Retrying uses its recorded
            title, description and approved candidate.
          </p>
          <dl>
            <dt>Saved PR title</dt>
            <dd>{recovery.request.title}</dd>
            <dt>Saved PR description</dt>
            <dd>{recovery.request.description || "No description"}</dd>
          </dl>
          {!recovery.can_retry && (
            <p>
              The developer who started publication must retry this saved
              operation.
            </p>
          )}
          <button
            className="primary-button"
            disabled={!canDeliver || busy || recovering || !recovery.can_retry}
            onClick={() => void publish()}
          >
            Retry saved publication
          </button>
        </>
      )}
      {result ? (
        <>
          <a href={safeLink(result.url)} target="_blank" rel="noreferrer">
            {result.repository} · PR #{result.pr}
          </a>
          <p>
            Branch {result.branch} · commit {result.commit.slice(0, 12)}
          </p>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void refresh()}
          >
            Refresh CI and review feedback
          </button>
        </>
      ) : (
        !recovery && (
          <button
            className="secondary-button"
            disabled={
              !canDeliver ||
              busy ||
              recovering ||
              !recoveryChecked ||
              !viaMachine()
            }
            onClick={() => void inspect()}
          >
            Review publication details
          </button>
        )
      )}
      {preview && !result && !recovery && !recovering && (
        <>
          <dl>
            <dt>Repository</dt>
            <dd>{preview.repository}</dd>
            <dt>Base</dt>
            <dd>{preview.base}</dd>
            <dt>Branch</dt>
            <dd>{preview.branch}</dd>
          </dl>
          <label>
            PR title
            <input
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            PR description
            <textarea
              value={description}
              maxLength={20000}
              rows={4}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <p>
            Publish the approved candidate as a draft PR. CI and GitHub reviews
            remain visible here.
          </p>
          <button
            className="primary-button"
            disabled={!canDeliver || busy || !title.trim()}
            onClick={() => void publish()}
          >
            {busy ? "Publishing…" : "Publish draft PR"}
          </button>
        </>
      )}
      {feedback && (
        <>
          <p className="feedback-freshness">
            {feedback.refreshed_at ? (
              <>
                Checked{" "}
                <time
                  dateTime={new Date(
                    feedback.refreshed_at * 1000,
                  ).toISOString()}
                >
                  {new Date(feedback.refreshed_at * 1000).toLocaleString()}
                </time>
              </>
            ) : (
              "Feedback freshness was not recorded by this server."
            )}
          </p>
          {feedback.incomplete && (
            <div className="feedback-partial" role="status">
              <strong>GitHub feedback is incomplete</strong>
              <p>
                Some CI or review entries could not be loaded. Inspect the full
                pull request on GitHub before deciding on a revision.
              </p>
              {Object.entries(feedback.feedback_errors || {}).map(
                ([collection, guidance]) => (
                  <p key={collection}>
                    {collection.replaceAll("_", " ")}: {guidance}
                  </p>
                ),
              )}
              {safeLink(feedback.url) && (
                <a
                  href={safeLink(feedback.url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open full pull request on GitHub
                </a>
              )}
            </div>
          )}
          {feedback.external_change && (
            <p role="alert">
              The PR head changed outside Parallax. Inspect it before requesting
              another revision.
            </p>
          )}
          {feedback.checks.map((c) => (
            <p key={c.id}>
              <a href={safeLink(c.html_url)} target="_blank" rel="noreferrer">
                {c.name}
              </a>
              : {c.conclusion || c.status}
            </p>
          ))}
          {feedback.statuses.map((c) => (
            <p key={c.id}>
              {safeLink(c.target_url) ? (
                <a
                  href={safeLink(c.target_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {c.context}
                </a>
              ) : (
                c.context
              )}
              : {c.state}
            </p>
          ))}
          {feedback.comments.map((c) => (
            <article key={c.id}>
              <a href={safeLink(c.html_url)} target="_blank" rel="noreferrer">
                {c.path}:{c.line || ""}
              </a>
              <p>{c.body}</p>
              <button
                className="secondary-button"
                onClick={() =>
                  onFeedback(
                    `GitHub review at ${c.path}:${c.line || ""}: ${c.body}`,
                  )
                }
              >
                Add to revision request
              </button>
            </article>
          ))}
          {feedback.reviews.map((r) => (
            <article key={r.id}>
              <a href={safeLink(r.html_url)} target="_blank" rel="noreferrer">
                {r.state}
              </a>
              <p>{r.body}</p>
              {r.body && (
                <button
                  className="secondary-button"
                  onClick={() => onFeedback(`GitHub review: ${r.body}`)}
                >
                  Add to revision request
                </button>
              )}
            </article>
          ))}
        </>
      )}
    </section>
  );
}
