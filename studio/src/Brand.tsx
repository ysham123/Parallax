import openaiBlack from "./assets/openai-black.svg";
import openaiWhite from "./assets/openai-white.svg";
import claude from "./assets/claude.png";
import grok from "./assets/grok.svg";
import antigravity from "./assets/antigravity.svg";

/** Original vendor assets. Sources and trademark notices: studio/ASSETS.md. */
export function ProviderMark({
  provider,
  size = 30,
}: {
  provider: string;
  size?: number;
}) {
  const source =
    provider === "claude"
      ? claude
      : provider === "grok"
        ? grok
        : provider === "antigravity"
          ? antigravity
          : undefined;
  return (
    <span
      className={`provider-mark ${["codex", "claude", "grok", "antigravity"].includes(provider) ? provider : "custom"}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {provider === "codex" ? (
        <>
          <img src={openaiWhite} alt="" className="brand-dark" />
          <img src={openaiBlack} alt="" className="brand-light" />
        </>
      ) : source ? (
        <img src={source} alt="" />
      ) : (
        <svg
          width={size * 0.6}
          height={size * 0.6}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="12" cy="12" r="8" />
          <path d="M4 12h16M12 4c4 4 4 12 0 16-4-4-4-12 0-16Z" />
        </svg>
      )}
    </span>
  );
}
