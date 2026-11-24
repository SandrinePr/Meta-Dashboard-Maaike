import { useEffect, useState } from "react";
import LegendPage from "./LegendPage.jsx";

/**
 * Daily-work settings for editors (Jet/Mo). Technical tooling lives under
 * Technisch beheer (admin only).
 */
export default function SettingsHubPage({
  client,
  session,
  initialTab = "home",
  onNotice,
  onError,
  onTabChange,
  onOpenClientSetup,
  onOpenTechAdmin,
  onOpenClients,
}) {
  const role = session?.role || "admin";
  const isAdmin = role === "admin";
  const isEditor = role === "editor" || isAdmin;
  const isViewer = role === "viewer";
  const [tab, setTab] = useState(initialTab === "legend" ? "legend" : "home");

  useEffect(() => {
    setTab(initialTab === "legend" ? "legend" : "home");
  }, [initialTab, client?.id]);

  function selectTab(next) {
    setTab(next);
    onTabChange?.(next);
  }

  if (isViewer) {
    return (
      <div className="stack">
        <p className="banner">
          Als gewone gebruiker bekijk je vooral rapporten en berichten. Instellingen wijzigen mag
          alleen een editor (Jet/Mo) of beheerder.
        </p>
        {!session?.role_enforced ? (
          <p className="hint">{session?.note_nl}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="stack">
      <p className="banner">
        <strong>Wie hoort hier?</strong> Jet en Mo (editors) openen{" "}
        <strong>Klant inrichten</strong> voor doelen, strategie, links, concurrenten en
        klantprompts, en beheren hier de legenda. Dagelijks werk staat links: Socialmediaberichten,
        Resultaten en Rapporten. Technisch beheer (algemene prompts, API’s, back-up) blijft voor
        beheerders.
      </p>
      {!session?.role_enforced ? <p className="hint">{session?.note_nl}</p> : null}

      <div className="subnav-tabs" role="tablist" aria-label="Instellingen">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "home"}
          className={tab === "home" ? "subnav-tab is-active" : "subnav-tab"}
          onClick={() => selectTab("home")}
        >
          Overzicht
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "legend"}
          className={tab === "legend" ? "subnav-tab is-active" : "subnav-tab"}
          onClick={() => selectTab("legend")}
        >
          Legenda (formats &amp; pijlers)
        </button>
      </div>

      {tab === "home" ? (
        <div className="stack">
          <section className="card stack">
            <h3 style={{ marginTop: 0 }}>Voor editors (Jet &amp; Mo)</h3>
            <p className="hint">
              Wat je hier doet: klantgegevens bijwerken, Meta koppelen, en de legenda per klant
              beheren voor het dagelijkse berichtenwerk.
            </p>
            <div className="row-actions wrap">
              <button
                className="primary"
                type="button"
                disabled={!isEditor}
                onClick={() => onOpenClientSetup?.(client || null)}
              >
                {client ? `Klant inrichten · ${client.name}` : "Klant inrichten"}
              </button>
              <button className="secondary" type="button" onClick={() => onOpenClients?.()}>
                Alle klanten
              </button>
              <button className="secondary" type="button" onClick={() => selectTab("legend")}>
                Open legenda
              </button>
            </div>
            {!client ? (
              <p className="banner">
                Kies links een klant, of open Alle klanten, voordat je de inrichting start.
              </p>
            ) : null}
          </section>

          <section className="card stack">
            <h3 style={{ marginTop: 0 }}>Wat je op elk scherm doet</h3>
            <ul className="plain-list" style={{ lineHeight: 1.55 }}>
              <li>
                <strong>Klant inrichten</strong> — één plek voor naam, Meta-koppeling, doelen,
                strategie, links, concurrenten en de prompts die bij die klant horen.
              </li>
              <li>
                <strong>Legenda</strong> — formats, pijlers en hooks die je bij Socialmediaberichten
                invult.
              </li>
              <li>
                <strong>Socialmediaberichten / Resultaten / Rapporten</strong> — dagelijks werk in
                het menu links (niet hier).
              </li>
              {isAdmin ? (
                <li>
                  <strong>Technisch beheer</strong> — API-status, prompts, planning, back-up en
                  diagnose (alleen beheerder).
                </li>
              ) : (
                <li>
                  <strong>Technisch beheer</strong> — niet zichtbaar voor editors; vraag een
                  beheerder bij API- of serverproblemen.
                </li>
              )}
            </ul>
            {isAdmin && onOpenTechAdmin ? (
              <div className="row-actions">
                <button className="secondary" type="button" onClick={() => onOpenTechAdmin()}>
                  Ga naar Technisch beheer
                </button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {tab === "legend" && client ? (
        <>
          <p className="hint">
            Legenda voor <strong>{client.name}</strong> — formats, pijlers en hooks voor het
            nakijken van berichten.
          </p>
          <LegendPage
            key={`legend-${client.id}`}
            client={client}
            onNotice={onNotice}
            onError={onError}
          />
        </>
      ) : null}
      {tab === "legend" && !client ? (
        <p className="banner">Kies links een klant om de legenda te bewerken.</p>
      ) : null}
    </div>
  );
}
