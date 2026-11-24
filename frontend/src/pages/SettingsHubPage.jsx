import { useEffect, useState } from "react";
import AiSettingsPage from "./AiSettingsPage.jsx";
import AiTrialPage from "./AiTrialPage.jsx";
import DataTransferPage from "./DataTransferPage.jsx";
import LegendPage from "./LegendPage.jsx";
import PromptsPage from "./PromptsPage.jsx";
import ReportPlanningPage from "./ReportPlanningPage.jsx";

const TABS = [
  ["ai", "AI-koppelingen & techniek"],
  ["prompts", "Prompts"],
  ["planning", "Rapportplanning"],
  ["legend", "Legenda (formats & pijlers)"],
  ["backup", "Back-up & herstel"],
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
        {tab === "planning" ? (
          <>
            <strong>Rapportplanning geldt voor alle klanten</strong> — inclusief het automatische
            algemeen trendrapport op de 1e van iedere maand (Europe/Amsterdam).
          </>
        ) : tab === "prompts" ? (
          <>
            <strong>Prompts gelden voor alle klanten</strong>. De geselecteerde klant links (
            {client ? client.name : "geen"}) verandert de prompttekst niet; klantgegevens blijven apart.
          </>
        ) : (
          <>
            Beheerinstellingen voor klant: <strong>{client ? client.name : "geen geselecteerd"}</strong>
            {tab === "legend" ? " — formats, pijlers en hooks worden per klant bewaard." : null}
            {tab === "backup"
              ? " — volledige JSON-back-up en herstel van het dashboard."
              : null}
            {tab === "ai"
              ? " — API-status, technische werking van rapporten en interne AI-proefrun."
              : null}
          </>
        )}
      </p>

      <div className="subnav-tabs" role="tablist" aria-label="Beheerinstellingen">
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
                <em>M</em> rekent HAMSTER automatisch met de <strong>21e van maand M−1 t/m de 20e van maand M</strong>{" "}
                en vergelijkt dit met de <strong>21e van maand M−2 t/m de 20e van maand M−1</strong>{" "}
                (inclusief jaarwisseling). Voor formats en terugkerende patronen leest HAMSTER alle
                beschikbare eigen berichten vanaf 1 januari t/m de einddatum van het rapport.
              </li>
              <li>
                <strong>Zelfstandig algemeen trendrapport:</strong> beslaat trends per
                socialmediakanaal voor één kalendermaand (zonder klantperiode, terugblik of X+2-maand)
                en wordt op de 1e van iedere maand automatisch aangemaakt in tijdzone{" "}
                <code>Europe/Amsterdam</code>.
              </li>
              <li>
                <strong>Beeldanalyse per bericht &amp; kostenraming:</strong> losse berichtcontroles
                staan bij <em>Socialmediaberichten</em>. Kostenbedragen vóór het starten zijn schattingen
                en geen harde afbreeklimiet tijdens een AI-aanroep; openen of verversen van een rapport
                start nooit opnieuw een betaalde AI-run.
              </li>
            </ul>
          </section>

          <AiSettingsPage onOpenPrompts={() => selectTab("prompts")} />

          <section className="card stack">
            <h3 style={{ marginTop: 0 }}>Interne AI-proefrun (losse posttest)</h3>
            <p className="hint">
              Kleine technische proef op losse berichten (afbeelding / carrousel / reel). Dit staat los
              van het maandelijkse klantrapport. Openen start geen betaalde aanroep.
            </p>
            {client ? (
              <AiTrialPage key={`ai-trial-settings-${client.id}`} client={client} />
            ) : (
              <p className="banner">Kies eerst links een klant om de AI-proefrun te bekijken.</p>
            )}
          </section>
        </div>
      ) : null}

      {tab === "prompts" ? <PromptsPage onNotice={onNotice} onError={onError} /> : null}
      {tab === "planning" ? <ReportPlanningPage /> : null}
      {tab === "legend" && client ? (
        <LegendPage key={`legend-${client.id}`} client={client} onNotice={onNotice} onError={onError} />
      ) : null}
      {tab === "legend" && !client ? (
        <p className="banner">Kies links een klant om de legenda te bewerken.</p>
      ) : null}
      {tab === "backup" ? <DataTransferPage /> : null}
    </div>
  );
}
