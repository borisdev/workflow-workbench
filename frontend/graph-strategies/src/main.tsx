/**
 * Island bootstrap. It claims one <div> and nothing else.
 *
 *   <div id="graph-strategies-root" data-report-url="/r/<sha>/data?token=…"></div>
 *
 * No router, no global state, no takeover of the page. If the div is not there, nothing happens.
 * Same contract as the webapp's causal-graph island, deliberately.
 */
import "@xyflow/react/dist/style.css";
import "./styles.css";
import "./panel.css";

import { createRoot } from "react-dom/client";

import { App } from "./App";

const MOUNT_ID = "graph-strategies-root";

function boot() {
  const el = document.getElementById(MOUNT_ID);
  if (!el) return;
  const reportUrl = el.dataset.reportUrl;
  if (!reportUrl) {
    el.textContent = "graph-strategies island: missing data-report-url";
    return;
  }
  createRoot(el).render(<App reportUrl={reportUrl} />);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
