import { useEffect, useState } from "react";
import { api } from "../api.js";
import AiSettingsPage from "./AiSettingsPage.jsx";
import AiTrialPage from "./AiTrialPage.jsx";
import DataTransferPage from "./DataTransferPage.jsx";
import PromptsPage from "./PromptsPage.jsx";
import ReportPlanningPage from "./ReportPlanningPage.jsx";

const TABS = [
  ["status", "API & koppelingen"],
  ["prompts", "Prompts"],
  ["planning", "Rapportplanning"],
  ["backup", "Back-up & herstel"],
  ["trial", "AI-proefrun"],
];

const TAB_HINTS = {
  status: "Bekijk of AI, Meta en back-up goed staan en lees hoe rapporten technisch werken.",
  prompts: "Centrale AI-prompts voor alle klanten. Klantprompts horen bij Klant inrichten.",
  planning: "Plan klantrapporten en het maandelijkse trendrapport voor alle klanten.",
  backup: "Exporteer of herstel een volledige JSON-back-up van het dashboard.",
  trial: "Draai een technische proef op losse berichten. Openen start geen betaalde aanroep.",
};

export default function TechAdminPage({
  client,
  initialTab = "status",
  onNotice,
  onError,
  onTabChange,
  onOpenClientSetup,
}) {
  const [tab, setTab] = useState(initialTab);
  const [canvaSteps, setCanvaSteps] = useState("");

  useEffect(() => {
    api("/api/canva/status")
      .then((payload) => setCanvaSteps(payload?.admin_steps_nl || ""))
      .catch(() => setCanvaSteps(""));
  }, []);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab, client?.id]);

  function selectTab(next) {
    setTab(next);
    onTabChange?.(next);
  }

  return (
    <div className="stack">
      <p className="banner">
        <strong>Technisch beheer</strong> staat apart van de dagelijkse schermen. Hier staan
        API-instellingen, planning, back-ups en diagnose. Klantgegevens blijven in{" "}
        <strong>Klant inrichten</strong>.
      </p>
      <p className="hint">
        Facebook en Instagram koppelen blijft in <strong>Klant inrichten</strong>
        {client ? ` (${client.name})` : ""}.{" "}
        {onOpenClientSetup ? (
          <button className="secondary" type="button" onClick={() => onOpenClientSetup()}>
            Open Klant inrichten
          </button>
        ) : null}
      </p>
      <p className="hint">{TAB_HINTS[tab]}</p>

      <div className="subnav-tabs" role="tablist" aria-label="Technisch beheer">
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

      {tab === "status" ? (
        <div className="stack">
          {canvaSteps ? (
            <section className="card stack">
              <h3 style={{ marginTop: 0 }}>Canva-koppeling (alleen beheer)</h3>
              <p className="hint">{canvaSteps}</p>
            </section>
          ) : null}
          <section className="card stack">
            <h3 style={{ marginTop: 0 }}>Technische werking van Rapporten</h3>
            <ul className="plain-list" style={{ lineHeight: 1.6 }}>
              <li>
                <strong>Opgeslagen gegevens i.p.v. live Meta-sync:</strong> het maken van een rapport
                rekent in Python met de berichten, strategie en inzichten die al in HAMSTER staan. Een
                rapport starten haalt niet tussentijds nieuwe berichten op bij Meta.
              </li>
              <li>
                <strong>Vaste perioden klantrapport:</strong> bij een klantrapport voor maand{" "}
                <em>M</em> rekent HAMSTER automatisch met de <strong>21e van maand M−1 t/m de 20e van
                maand M</strong>{" "}
                en vergelijkt dit met de <strong>21e van maand M−2 t/m de 20e van maand M−1</strong>{" "}
                (inclusief jaarwisseling).
              </li>
              <li>
                <strong>Zelfstandig algemeen trendrapport:</strong> beslaat trends per
                socialmediakanaal voor één kalendermaand en wordt op de 1e van iedere maand
                automatisch aangemaakt in tijdzone <code>Europe/Amsterdam</code>.
              </li>
              <li>
                <strong>Beeldanalyse per bericht &amp; kostenraming:</strong> losse berichtcontroles
                staan bij <em>Socialmediaberichten</em>. Openen of verversen van een rapport start
                nooit opnieuw een betaalde AI-run.
              </li>
            </ul>
          </section>
          <AiSettingsPage onOpenPrompts={() => selectTab("prompts")} />
        </div>
      ) : null}

      {tab === "prompts" ? <PromptsPage onNotice={onNotice} onError={onError} /> : null}
      {tab === "planning" ? <ReportPlanningPage /> : null}
      {tab === "backup" ? <DataTransferPage /> : null}
      {tab === "trial" ? (
        <section className="card stack">
          <h3 style={{ marginTop: 0 }}>Interne AI-proefrun (losse posttest)</h3>
          <p className="hint">{TAB_HINTS.trial}</p>
          {client ? (
            <AiTrialPage key={`ai-trial-tech-${client.id}`} client={client} />
          ) : (
            <p className="banner">Kies links een klant om de AI-proefrun te bekijken.</p>
          )}
        </section>
      ) : null}
    </div>
  );
}
