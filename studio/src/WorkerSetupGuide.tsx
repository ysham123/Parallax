import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { PREVIEW_GUIDES, PUBLIC_RELEASE } from "./public-release";
import "./worker-setup.css";

type Platform = "macos" | "linux" | "wsl2" | "windows";
type Stage = "prepare" | "connect";

const platforms: { id: Platform; label: string }[] = [
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
  { id: "wsl2", label: "WSL2" },
  { id: "windows", label: "Windows" },
];
const windowsGuide = new URL("WINDOWS.md", PREVIEW_GUIDES.setup).href;

export function WorkerSetupGuide({
  command,
  pairing,
  access,
  headingLevel = 2,
}: {
  command: ReactNode;
  pairing: ReactNode;
  access?: string;
  headingLevel?: 2 | 3;
}) {
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [stage, setStage] = useState<Stage>("prepare");
  const group = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const choices = useRef<Partial<Record<Platform, HTMLInputElement>>>({});
  const previousStage = useRef(stage);
  const supported = platform === "macos" || platform === "linux";
  const Heading = headingLevel === 3 ? "h3" : "h2";

  useEffect(() => {
    if (previousStage.current === stage) return;
    previousStage.current = stage;
    if (stage === "connect") heading.current?.focus();
    else if (platform) choices.current[platform]?.focus();
  }, [stage, platform]);

  return (
    <section className="worker-setup" aria-label="Connect a preview worker">
      <ol className="worker-setup-steps" aria-label="Machine setup steps">
        <li aria-current={stage === "prepare" ? "step" : undefined}>
          <span aria-hidden="true">1</span> Prepare your machine
        </li>
        <li aria-current={stage === "connect" ? "step" : undefined}>
          <span aria-hidden="true">2</span> Connect it
        </li>
      </ol>

      {stage === "prepare" ? (
        <div className="worker-setup-content">
          <Heading ref={heading} tabIndex={-1}>
            Prepare your machine
          </Heading>
          <fieldset className="worker-platforms">
            <legend>Where will the worker run?</legend>
            <div className="worker-platform-options">
              {platforms.map((choice) => (
                <label key={choice.id}>
                  <input
                    ref={(node) => {
                      if (node) choices.current[choice.id] = node;
                      else delete choices.current[choice.id];
                    }}
                    type="radio"
                    name={`worker-platform-${group}`}
                    value={choice.id}
                    checked={platform === choice.id}
                    onChange={() => setPlatform(choice.id)}
                  />
                  {choice.label}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="worker-preview-note">
            <strong>Use your supplied preview</strong>
            <p>
              Verify the operator's archive digest, extract it into a new
              folder, and run the worker there. Public {PUBLIC_RELEASE.version}{" "}
              local tools do not install this worker. If you have not received
              the preview, ask your pilot operator for it.
            </p>
            <a href={PREVIEW_GUIDES.setup}>Read the preview setup guide</a>
          </div>

          {supported && (
            <details className="worker-setup-details">
              <summary>
                Requirements for {platform === "macos" ? "macOS" : "Linux"}
              </summary>
              <p>
                Python 3.10 or newer, Git 2.38 or newer, and two usable
                independent providers for Build: one to implement and another to
                review. Use supported signed-in CLIs or machine-owned API
                connections. A detected sign-in does not establish remaining
                quota.
              </p>
              {platform === "linux" && (
                <p>
                  Linux also needs working bubblewrap and user namespaces. A
                  complete Linux project workflow remains a separate live
                  acceptance gate.
                </p>
              )}
              <p>
                Native Grok is unavailable in this preview. Claude Code and
                Antigravity use restricted file tools, with shell and
                content-search tools disabled. Follow the guide's manual
                diagnostics before starting a task.
              </p>
            </details>
          )}

          {platform === "windows" && (
            <div className="worker-platform-limit" role="status">
              <strong>Native Windows execution is unsupported</strong>
              <p>
                The Mac app and DMG do not install on Windows. WSL2 is a
                separate experimental route with an unverified complete
                workflow. You can use browser Studio from Windows with a
                separately paired, supported Mac or Linux machine.
              </p>
              <a href={windowsGuide}>Read the Windows and WSL2 guide</a>
            </div>
          )}
          {platform === "wsl2" && (
            <div className="worker-platform-limit" role="status">
              <strong>WSL2 is experimental</strong>
              <p>
                A complete task on a real Windows/WSL2 machine remains
                unverified. Follow the capability guide with Linux-side tools
                and a project in the distribution's Linux filesystem.
              </p>
              <a href={windowsGuide}>Read the Windows and WSL2 guide</a>
            </div>
          )}

          {(supported || !platform) && (
            <div className="worker-setup-actions">
              <button
                type="button"
                className="pub-primary"
                disabled={!supported}
                onClick={() => {
                  if (supported) setStage("connect");
                }}
              >
                Continue to connect
              </button>
              {!platform && <span>Choose the platform on the machine.</span>}
            </div>
          )}
          <p className="worker-public-tools">
            Looking for the public local tools?{" "}
            <a href="/#install">
              View the separate {PUBLIC_RELEASE.version} install
            </a>
            .
          </p>
        </div>
      ) : supported ? (
        <div className="worker-setup-content">
          <Heading ref={heading} tabIndex={-1}>
            Connect it
          </Heading>
          {command}
          <p>
            Use an existing Git folder you approve. Replace{" "}
            <code>/absolute/path/to/project</code> with its path and{" "}
            <code>"My Mac"</code> with your machine's label; keep the{" "}
            <code>--workspace</code> and <code>--name</code> flags. Keep this
            terminal running and the machine awake. The worker connects outward
            over HTTPS.
          </p>
          <p>
            Provider credentials, private checkouts and complete session files
            stay on the machine. Task prompts and mirrored results may contain
            source code and are stored in this workspace. {access}
          </p>
          <details className="worker-setup-details">
            <summary>Project access and data sharing</summary>
            <p>
              Repeat <code>--workspace</code> to approve more existing projects.
              Team project permissions additionally control which members can
              access each project. The first start prepares a private Python
              environment and asks for a pairing code without echoing it. No
              inbound port is opened.
            </p>
            <p>
              Mirrored task settings, diffs, check output, review findings,
              agent output and session metadata can contain project content.
              Relevant prompts and project context reach your chosen model
              providers when a task runs. The worker never uploads your provider
              credentials. Disconnecting revokes future commands; an offline
              machine receives the revocation when it reconnects.
            </p>
          </details>
          <p className="worker-pair-instruction">
            Generate a code and paste it at the worker's prompt.
          </p>
          {pairing}
          <div className="worker-setup-actions">
            <button
              type="button"
              className="pub-secondary"
              onClick={() => setStage("prepare")}
            >
              Back to preparation
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
