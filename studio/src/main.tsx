import "./system.css";
import "./style.css";
import "./workspace.css";
import React, { Component, lazy, Suspense, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import PublicSite from "./PublicSite";
import { publicWebsite } from "./entry-routing";
import { applyStoredTheme, Mark } from "./PublicChrome";

const HostedApp = lazy(() => import("./HostedApp"));
const LocalApp = lazy(() => import("./App"));
const CloudApp = lazy(() => import("./CloudApp"));
const mode = import.meta.env.MODE;
const connectedMode = ["hosted", "cloud"].includes(mode);
const publicEntry =
  connectedMode && publicWebsite(location.pathname, location.search);
const App =
  mode === "hosted" ? HostedApp : mode === "cloud" ? CloudApp : LocalApp;

function EntryStatus({ failed = false }: { failed?: boolean }) {
  return (
    <main className="entry-status">
      <Mark size={36} />
      <h1>{failed ? "Studio could not open." : "Opening Studio."}</h1>
      {failed ? (
        <>
          <p>
            The interface could not be displayed. Refresh this page to try
            again. Your worker may still be running a task.
          </p>
          <button className="pub-primary" onClick={() => location.reload()}>
            Refresh Studio
          </button>
        </>
      ) : (
        <p role="status">Loading the interface…</p>
      )}
      {connectedMode ? (
        <a href="/">Return to the website</a>
      ) : (
        <a href="https://github.com/ysham123/Parallax#install">
          Open setup guide
        </a>
      )}
    </main>
  );
}

class StudioBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <EntryStatus failed /> : this.props.children;
  }
}

applyStoredTheme();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {publicEntry ? (
      <PublicSite hosted={mode === "cloud"} />
    ) : (
      <StudioBoundary>
        <Suspense fallback={<EntryStatus />}>
          <App />
        </Suspense>
      </StudioBoundary>
    )}
  </React.StrictMode>,
);
