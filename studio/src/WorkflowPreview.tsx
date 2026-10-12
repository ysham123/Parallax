import { useState, type ReactNode } from "react";
import "./workflow-preview.css";

const STEPS = [
  {
    label: "Request",
    title: "Describe an outcome worth checking.",
    text: "Capture the project baseline, acceptance criteria and the commands that will tell you whether the change works.",
    state: "Request captured",
  },
  {
    label: "Changes",
    title: "Inspect the candidate beside its checks.",
    text: "The first patch stays in an isolated candidate. Command output makes a failed acceptance criterion visible before anything reaches the project.",
    state: "Needs correction",
  },
  {
    label: "Review",
    title: "A finding comes with a place to start.",
    text: "Independent review identifies the file, location and concern. Select the finding when you request a correction so the next run keeps that context.",
    state: "Finding recorded",
  },
  {
    label: "Revise",
    title: "Correct the saved patch. Verify again.",
    text: "A revision starts from the saved candidate and original baseline. It preserves the acceptance criteria and settings, and produces new checks, review and a new digest.",
    state: "New candidate ready",
  },
  {
    label: "Approve",
    title: "Make a human decision on an exact candidate.",
    text: "Inspect the revised patch and fresh evidence before approval. A team candidate requires someone other than the current requester; an Owner has the same rule.",
    state: "Approval recorded",
  },
  {
    label: "Deliver",
    title: "Choose where the approved change goes.",
    text: "Apply locally as an explicit operation. With configured pilot GitHub delivery, inspect the destination and publish a draft PR. Keep delivery distinct from approval.",
    state: "Delivery selected",
  },
] as const;

function CheckRow({
  failed = false,
  children,
}: {
  failed?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`workflow-check-row ${failed ? "failed" : ""}`}>
      <span aria-hidden="true">{failed ? "×" : "✓"}</span>
      <span>{children}</span>
      <small>{failed ? "failed" : "passed"}</small>
    </div>
  );
}

export default function WorkflowPreview() {
  const [selected, setSelected] = useState(0);
  const step = STEPS[selected];
  return (
    <div className="workflow-preview">
      <div className="workflow-preview-bar">
        <span>
          <i aria-hidden="true" /> Example workflow
        </span>
        <span>Unreleased workflow · simulated evidence</span>
      </div>
      <ol
        className="workflow-preview-steps"
        aria-label="Explore the example workflow"
      >
        {STEPS.map((item, index) => (
          <li key={item.label}>
            <button
              type="button"
              aria-current={selected === index ? "step" : undefined}
              aria-controls="workflow-example-panel"
              onClick={() => setSelected(index)}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              {item.label}
            </button>
          </li>
        ))}
      </ol>
      <div className="workflow-preview-body">
        <div className="workflow-preview-story">
          <p className="workflow-stage">
            Step {selected + 1} of {STEPS.length}
          </p>
          <h3>{step.title}</h3>
          <p>{step.text}</p>
          <div
            className={`workflow-state ${selected === 1 ? "attention" : ""}`}
          >
            <span aria-hidden="true" />
            {step.state}
          </div>
          <p className="workflow-example-note">
            Example: reject empty input in an average helper. This is an
            unreleased Studio workflow preview with simulated evidence. The
            public download contains the existing local tools.
          </p>
          <span className="sr-only" role="status">
            Showing {step.label}: {step.state}
          </span>
        </div>
        <div
          className="workflow-example-panel"
          id="workflow-example-panel"
          role="region"
          aria-label={`Illustrated ${step.label.toLowerCase()} evidence`}
        >
          <div className="workflow-panel-top">
            <span>
              average-helper / {selected >= 3 ? "candidate-02" : "candidate-01"}
            </span>
            <span className="workflow-panel-label">Illustration</span>
          </div>
          {selected === 0 && (
            <div className="workflow-request">
              <span className="workflow-small-label">Request</span>
              <h4>Handle an empty average explicitly.</h4>
              <p>
                Update <code>average(values)</code> to raise{" "}
                <code>ValueError</code> for empty input. Preserve the existing
                result for nonempty input.
              </p>
              <div className="workflow-divider" />
              <span className="workflow-small-label">Acceptance criteria</span>
              <ul>
                <li>Empty input raises a clear error.</li>
                <li>Existing numeric cases pass.</li>
                <li>Developer files stay untouched during preparation.</li>
              </ul>
              <div className="workflow-command">
                <span>$</span>
                <code>python -m unittest tests.test_maths</code>
              </div>
              <p className="workflow-muted">
                Project baseline and required checks captured.
              </p>
            </div>
          )}
          {selected === 1 && (
            <>
              <div className="workflow-diff-header">
                maths.py <span>Proposed patch</span>
              </div>
              <pre
                className="workflow-diff"
                aria-label="Initial candidate diff"
              >
                <code>
                  <span>{" def average(values):"}</span>
                  <span className="addition">{"+    if not values:"}</span>
                  <span className="addition">{"+        return 0"}</span>
                  <span>{"     return sum(values) / len(values)"}</span>
                </code>
              </pre>
              <div className="workflow-checks">
                <span className="workflow-small-label">Project checks</span>
                <CheckRow>Existing numeric cases</CheckRow>
                <CheckRow failed>Empty input must raise ValueError</CheckRow>
                <p className="workflow-muted">
                  Failed acceptance checks block approval.
                </p>
              </div>
            </>
          )}
          {selected === 2 && (
            <div className="workflow-review">
              <div className="workflow-review-heading">
                <span className="workflow-review-priority">P1</span>
                <span>Independent review</span>
              </div>
              <p className="workflow-review-location">maths.py:2–3</p>
              <h4>Zero hides an invalid input.</h4>
              <p>
                Returning <code>0</code> makes an empty sequence
                indistinguishable from valid input whose average is zero. The
                acceptance criteria require an explicit error.
              </p>
              <div className="workflow-review-quote">
                “Raise ValueError for an empty sequence and retain the existing
                calculation otherwise.”
              </div>
              <div className="workflow-finding-selected">
                <span aria-hidden="true">✓</span> Finding included in correction
                request
              </div>
            </div>
          )}
          {selected === 3 && (
            <>
              <div className="workflow-diff-header">
                maths.py <span>Revised candidate</span>
              </div>
              <pre className="workflow-diff" aria-label="Revision diff">
                <code>
                  <span>{"     if not values:"}</span>
                  <span className="deletion">{"-        return 0"}</span>
                  <span className="addition">
                    {'+        raise ValueError("empty input")'}
                  </span>
                  <span>{"     return sum(values) / len(values)"}</span>
                </code>
              </pre>
              <div className="workflow-checks">
                <span className="workflow-small-label">Fresh evidence</span>
                <CheckRow>Required project checks</CheckRow>
                <CheckRow>Independent candidate review</CheckRow>
                <p className="workflow-muted">
                  Original baseline preserved · new candidate digest
                </p>
              </div>
            </>
          )}
          {selected === 4 && (
            <div className="workflow-approval">
              <div className="workflow-approval-icon" aria-hidden="true">
                ✓
              </div>
              <span className="workflow-small-label">Human decision</span>
              <h4>Candidate approved.</h4>
              <p>
                Revised changes and fresh evidence reviewed by a human with
                project access.
              </p>
              <dl>
                <div>
                  <dt>Candidate</dt>
                  <dd>candidate-02</dd>
                </div>
                <div>
                  <dt>Decision</dt>
                  <dd>Approve</dd>
                </div>
                <div>
                  <dt>Local files</dt>
                  <dd>Awaiting explicit application</dd>
                </div>
                <div>
                  <dt>GitHub</dt>
                  <dd>Awaiting explicit publication</dd>
                </div>
              </dl>
            </div>
          )}
          {selected === 5 && (
            <div className="workflow-delivery">
              <span className="workflow-small-label">Choose delivery</span>
              <div className="workflow-delivery-option">
                <div>
                  <strong>Apply locally</strong>
                  <span>Approved patch → developer project</span>
                </div>
                <span aria-hidden="true">↗</span>
              </div>
              <div className="workflow-delivery-option">
                <div>
                  <strong>Publish draft PR</strong>
                  <span>Configured GitHub App · invited pilot</span>
                </div>
                <span aria-hidden="true">↗</span>
              </div>
              <dl>
                <div>
                  <dt>Repository</dt>
                  <dd>example/average-helper</dd>
                </div>
                <div>
                  <dt>Branch</dt>
                  <dd>parallax/&lt;workflow-id&gt;</dd>
                </div>
                <div>
                  <dt>Content</dt>
                  <dd>Approved candidate tree</dd>
                </div>
              </dl>
              <p className="workflow-muted">
                Inspect repository, base, branch, title and description before
                publishing. CI and review feedback can inform an explicit new
                revision.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
