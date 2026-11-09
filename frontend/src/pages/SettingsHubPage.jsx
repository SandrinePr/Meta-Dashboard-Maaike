import { useEffect, useState } from "react";
import AiSettingsPage from "./AiSettingsPage.jsx";
import AiTrialPage from "./AiTrialPage.jsx";
import DataTransferPage from "./DataTransferPage.jsx";
import LegendPage from "./LegendPage.jsx";

const TABS = [
  ["ai", "AI Connections"],
  ["legend", "Legend"],
  ["backup", "Backup & restore"],
];

export default function SettingsHubPage({ client, initialTab = "ai", onNotice, onError, onTabChange }) {
  const [tab, setTab] = useState(initialTab);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab, client?.id]);

  function selectTab(next) {
    setTab(next);
    onTabChange?.(next);
  }

  return (
    <div className="stack">
      <p className="hint">
        Settings for client: <strong>{client ? client.name : "none selected"}</strong>
        {tab === "legend" ? " — legend items are stored per client." : null}
        {tab === "backup"
          ? " — full dashboard JSON backup/restore (separate from post Excel import)."
          : null}
        {tab === "ai"
          ? " — API status plus internal AI Trial (post analysis probe; not the monthly client report)."
          : null}
      </p>
      <div className="subnav-tabs" role="tablist" aria-label="Settings">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "subnav-tab is-active" : "subnav-tab"}
            onClick={() => selectTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "ai" ? (
        <div className="stack">
          <AiSettingsPage />
          <section className="card stack">
            <h3>AI Trial (internal)</h3>
            <p className="hint">
              Small Gemini post-analysis probe (image / carousel / reel). Not the client monthly
              report. Opening this section does not start a paid call.
            </p>
            {client ? (
              <AiTrialPage key={`ai-trial-settings-${client.id}`} client={client} />
            ) : (
              <p className="banner">Select a client in the sidebar to run AI Trial.</p>
            )}
          </section>
        </div>
      ) : null}
      {tab === "legend" && client ? (
        <LegendPage key={`legend-${client.id}`} client={client} onNotice={onNotice} onError={onError} />
      ) : null}
      {tab === "legend" && !client ? (
        <p className="banner">Select a client in the sidebar to edit the legend.</p>
      ) : null}
      {tab === "backup" ? <DataTransferPage /> : null}
    </div>
  );
}
