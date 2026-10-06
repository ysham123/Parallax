import React from "react";
import ReactDOM from "react-dom/client";
import HostedApp from "./HostedApp";
import LocalApp from "./App";
import CloudApp from "./CloudApp";
import "./style.css";
import "./workspace.css";

const App =
  import.meta.env.MODE === "hosted"
    ? HostedApp
    : import.meta.env.MODE === "cloud"
      ? CloudApp
      : LocalApp;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
