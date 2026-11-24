import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function LegendPage({ client, onNotice, onError }) {
  const [legend, setLegend] = useState({ formats: [], pillars: [], hooks: [] });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  async function reload() {
    setLoading(true);
    setLoadError("");
    try {
      const payload = await api(`/api/clients/${client.id}/legend`);
      setLegend({
        formats: payload.formats || [],
        pillars: payload.pillars || [],
        hooks: payload.hooks || [],
      });
    } catch (exc) {
      setLoadError(exc.message || "De legenda kon niet worden geladen.");
      onError(exc.message);
      throw exc;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload().catch(() => {});
  }, [client.id]);

  return (
    <div className="stack">
      <div className="search-form-header">
        <h3>Legenda</h3>
      </div>
      <p className="hint">
        Legenda voor <strong>{client.name}</strong>: contentformats, contentpijlers en hooks met
        uitleg. Alleen voor deze klant. Optioneel: een voorbeeld-URL per item. Koppelen aan
        berichten gebeurt bij Socialmediaberichten.
      </p>
      {loadError ? (
        <p className="banner error">
          De legenda kon niet worden geladen: {loadError}.{" "}
          <button className="secondary" type="button" onClick={() => reload().catch(() => {})}>
            Opnieuw laden
          </button>
        </p>
      ) : null}
      {loading && !loadError ? <p className="muted">Legenda laden…</p> : null}
      <Catalog
        title="Contentformats"
        intro="Naam + uitleg = de formatlegenda. Optioneel een voorbeeld-URL. Kies deze later per bericht."
        empty={`Nog geen contentformats voor ${client.name}. Voeg hieronder de eerste toe — dit raakt andere klanten niet.`}
        addLabel="Nieuw contentformat"
        items={legend.formats || []}
        onCreate={(body) => api(`/api/clients/${client.id}/formats`, { method: "POST", body })}
        onUpdate={(item, body) => api(`/api/clients/${client.id}/formats/${item.id}`, { method: "PATCH", body })}
        onSaved={async (message) => {
          await reload();
          onNotice(message);
        }}
        onError={onError}
      />
      <Catalog
        title="Contentpijlers"
        intro="Pijlers gelden alleen voor deze klant."
        empty={`Nog geen contentpijlers voor ${client.name}. Voeg er een toe om berichten te categoriseren.`}
        addLabel="Nieuwe contentpijler"
        items={legend.pillars || []}
        onCreate={(body) => api(`/api/clients/${client.id}/pillars`, { method: "POST", body })}
        onUpdate={(item, body) => api(`/api/clients/${client.id}/pillars/${item.id}`, { method: "PATCH", body })}
        onSaved={async (message) => {
          await reload();
          onNotice(message);
        }}
        onError={onError}
      />
      <Catalog
        title="Hooks"
        intro="Hooks als vaste legenda-items. Bij een bericht kies je een hook of typ je vrij."
        empty={`Nog geen hooks in de legenda voor ${client.name}. Optioneel: voeg vaste hooks toe.`}
        addLabel="Nieuwe hook"
        items={legend.hooks || []}
        onCreate={(body) => api(`/api/clients/${client.id}/hooks`, { method: "POST", body })}
        onUpdate={(item, body) => api(`/api/clients/${client.id}/hooks/${item.id}`, { method: "PATCH", body })}
        onSaved={async (message) => {
          await reload();
          onNotice(message);
        }}
        onError={onError}
      />
    </div>
  );
}

function Catalog({ title, intro, empty, addLabel, items, onCreate, onUpdate, onSaved, onError }) {
  const [name, setName] = useState("");
  const [explanation, setExplanation] = useState("");
  const [exampleUrl, setExampleUrl] = useState("");

  async function addItem(event) {
    event.preventDefault();
    onError("");
    try {
      await onCreate({ name, explanation, example_url: exampleUrl });
      setName("");
      setExplanation("");
      setExampleUrl("");
      await onSaved("Opgeslagen.");
    } catch (exc) {
      onError(exc.message);
    }
  }

  return (
    <section className="card stack">
      <div className="search-form-header">
        <h3>{title}</h3>
      </div>
      {intro ? <p className="hint">{intro}</p> : null}
      {items.length ? null : <p className="banner">{empty}</p>}
      {items.map((item) => (
        <ItemForm key={item.id} item={item} onUpdate={onUpdate} onSaved={onSaved} onError={onError} />
      ))}
      <form className="catalog-form" onSubmit={addItem}>
        <strong>{addLabel}</strong>
        <label>
          Naam
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Uitleg
          <textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} />
        </label>
        <label>
          Voorbeeld-URL (optioneel)
          <input
            value={exampleUrl}
            onChange={(event) => setExampleUrl(event.target.value)}
            placeholder="https://…"
          />
        </label>
        <button className="primary" type="submit">
          Toevoegen
        </button>
      </form>
    </section>
  );
}

function ItemForm({ item, onUpdate, onSaved, onError }) {
  const [name, setName] = useState(item.name);
  const [explanation, setExplanation] = useState(item.explanation || "");
  const [exampleUrl, setExampleUrl] = useState(item.example_url || "");

  useEffect(() => {
    setName(item.name);
    setExplanation(item.explanation || "");
    setExampleUrl(item.example_url || "");
  }, [item.id, item.name, item.explanation, item.example_url]);

  async function save(event) {
    event.preventDefault();
    onError("");
    try {
      await onUpdate(item, { name, explanation, example_url: exampleUrl });
      await onSaved("Opgeslagen.");
    } catch (exc) {
      onError(exc.message);
    }
  }

  return (
    <form className="catalog-form" onSubmit={save}>
      <label>
        Naam
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label>
        Uitleg
        <textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} />
      </label>
      <label>
        Voorbeeld-URL (optioneel)
        <input
          value={exampleUrl}
          onChange={(event) => setExampleUrl(event.target.value)}
          placeholder="https://…"
        />
      </label>
      {exampleUrl ? (
        <p className="hint">
          <a href={exampleUrl} target="_blank" rel="noreferrer">
            Open voorbeeld
          </a>
        </p>
      ) : null}
      <button className="secondary" type="submit">
        Opslaan
      </button>
    </form>
  );
}
