import { useEffect, useState } from "react";
import ClientPromptsPanel from "../components/ClientPromptsPanel.jsx";
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
  const role = session?.role || "viewer";
  const isAdmin = role === "admin";
  const isEditor = role === "editor" || isAdmin;
  const isViewer = role === "viewer";
  const allowedTabs = new Set(["home", "legend", "prompts"]);
  const [tab, setTab] = useState(allowedTabs.has(initialTab) ? initialTab : "home");

  useEffect(() => {
    setTab(allowedTabs.has(initialTab) ? initialTab : "home");
  }, [initialTab, client?.id]);

  function selectTab(next) {
    setTab(next);
    onTabChange?.(next);
  }

  if (isViewer) {
    return (
      <div className="stack">
        <p className="banner">
          Als gewone gebruiker bekijk je vooral rapporten en berichten. Instellingen en klantprompts
          wijzigen mag alleen een editor (Jet/Mo) of beheerder.
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
        <strong>Prompts</strong> voor de klantprompts van de geselecteerde klant, en{" "}
        <strong>Klant inrichten</strong> voor doelen, strategie, links en concurrenten. Algemene
        AI-prompts blijven bij <strong>Technisch beheer → Prompts</strong> (alleen beheerder).
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
          aria-selected={tab === "prompts"}
          className={tab === "prompts" ? "subnav-tab is-active" : "subnav-tab"}
          onClick={() => selectTab("prompts")}
        >
          Prompts
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
              Wat je hier doet: klantprompts bekijken en aanpassen, klantgegevens bijwerken, Meta
              koppelen, en de legenda per klant beheren.
            </p>
            <div className="row-actions wrap">
              <button
                className="primary"
                type="button"
                disabled={!isEditor || !client}
                onClick={() => selectTab("prompts")}
              >
                {client ? `Prompts · ${client.name}` : "Prompts"}
              </button>
              <button
                className="secondary"
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
                Kies links een klant, of open Alle klanten, voordat je prompts of inrichting opent.
              </p>
            ) : (
              <p className="hint">
                Actieve klant voor prompts en inrichting: <strong>{client.name}</strong>.
              </p>
            )}
          </section>

          <section className="card stack">
            <h3 style={{ marginTop: 0 }}>Wat je op elk scherm doet</h3>
            <ul className="plain-list" style={{ lineHeight: 1.55 }}>
              <li>
                <strong>Prompts</strong> — klantprompts van de geselecteerde klant (zelfde velden
                als Klant inrichten → Klantprompts).
              </li>
              <li>
                <strong>Klant inrichten</strong> — naam, Meta-koppeling, doelen, strategie, links,
                concurrenten en klantprompts.
              </li>
              <li>
                <strong>Legenda</strong> — formats, pijlers en hooks voor Socialmediaberichten.
              </li>
              <li>
                <strong>Socialmediaberichten / Resultaten / Rapporten</strong> — dagelijks werk in
                het menu links.
              </li>
              {isAdmin ? (
                <li>
                  <strong>Technisch beheer → Prompts</strong> — algemene AI-prompts voor alle
                  klanten (alleen beheerder).
                </li>
              ) : (
                <li>
                  <strong>Technisch beheer</strong> — niet zichtbaar voor editors; algemene prompts
                  vraagt u aan een beheerder.
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

      {tab === "prompts" ? (
        <div className="stack">
          <p className="banner" style={{ marginBottom: 0 }}>
            Prompts voor{" "}
            <strong>{client ? client.name : "geen klant geselecteerd"}</strong>
            {client ? ". Wissel links van klant om BBQube of een andere klant te openen." : "."}
          </p>
          <ClientPromptsPanel
            key={`settings-prompts-${client?.id || "none"}`}
            client={client}
            canEdit={isEditor}
            onNotice={onNotice}
            onError={onError}
          />
          {client ? (
            <div className="row-actions">
              <button
                className="secondary"
                type="button"
                onClick={() => onOpenClientSetup?.(client)}
              >
                Open volledige Klant inrichten
              </button>
            </div>
          ) : null}
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
