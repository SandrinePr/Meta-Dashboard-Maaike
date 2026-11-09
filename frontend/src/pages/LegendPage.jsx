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
      setLoadError(exc.message || "Failed to load legend.");
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
        <h3>Legend</h3>
      </div>
      <p className="hint">
        Legend for <strong>{client.name}</strong>: formats, content pillars and hooks with explanations. Only
        this client. Linking to posts happens in Logs.
      </p>
      {loadError ? (
        <p className="banner error">
          Could not load the legend: {loadError}.{" "}
          <button className="secondary" type="button" onClick={() => reload().catch(() => {})}>
            Reload
          </button>
        </p>
      ) : null}
      {loading && !loadError ? <p className="muted">Loading legend…</p> : null}
      <Catalog
        title="Content formats"
        intro="Name + explanation = the format legend. Choose these later per post in Logs."
        empty={`No content formats for ${client.name} yet. Add the first one below — this does not affect other clients.`}
        addLabel="New content format"
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
        title="Content pillars"
        intro="Pillars apply only to this client."
        empty={`No content pillars for ${client.name} yet. Add one to categorise posts.`}
        addLabel="New content pillar"
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
        intro="Hooks as reusable legend items. On a post you can pick a hook or type freely."
        empty={`No hooks in the legend for ${client.name} yet. Optional: add fixed hooks.`}
        addLabel="New hook"
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

  async function addItem(event) {
    event.preventDefault();
    onError("");
    try {
      await onCreate({ name, explanation });
      setName("");
      setExplanation("");
      await onSaved("Saved.");
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
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Explanation
          <textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} />
        </label>
        <button className="primary" type="submit">
          Add
        </button>
      </form>
    </section>
  );
}

function ItemForm({ item, onUpdate, onSaved, onError }) {
  const [name, setName] = useState(item.name);
  const [explanation, setExplanation] = useState(item.explanation || "");

  useEffect(() => {
    setName(item.name);
    setExplanation(item.explanation || "");
  }, [item.id, item.name, item.explanation]);

  async function save(event) {
    event.preventDefault();
    onError("");
    try {
      await onUpdate(item, { name, explanation });
      await onSaved("Saved.");
    } catch (exc) {
      onError(exc.message);
    }
  }

  return (
    <form className="catalog-form" onSubmit={save}>
      <label>
        Name
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label>
        Explanation
        <textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} />
      </label>
      <button className="secondary" type="submit">
        Save
      </button>
    </form>
  );
}
