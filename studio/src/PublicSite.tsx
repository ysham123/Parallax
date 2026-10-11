import { useEffect, useState } from "react";
import PublicEntry from "./PublicEntry";
import { applyStoredTheme } from "./PublicChrome";
import type { AuthConfig } from "./session";

const LOCAL_CONFIG: AuthConfig = { github: false, providers: [], signup: "closed" };

/** The website is useful before a relay is configured, connected, or available. */
export default function PublicSite({ hosted = false }: { hosted?: boolean }) {
  const [config, setConfig] = useState<AuthConfig>(LOCAL_CONFIG);
  useEffect(() => {
    applyStoredTheme();
    if (!hosted) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    void fetch("/api/auth/config", {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) return;
        const value: AuthConfig = await response.json();
        if (!controller.signal.aborted && typeof value.github === "boolean" &&
            ["open", "allowlist", "closed"].includes(value.signup)) setConfig(value);
      })
      .catch(() => {})
      .finally(() => window.clearTimeout(timeout));
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [hosted]);
  return <PublicEntry config={config} error={null} />;
}
