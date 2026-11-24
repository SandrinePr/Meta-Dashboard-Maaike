import { useState } from "react";
import { api, API_URL } from "../api.js";

export default function DataTransferPage() {
  const [preview, setPreview] = useState(null);
  const [file, setFile] = useState(null);
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [scopeClient, setScopeClient] = useState("");

  async function runPreview(selected) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const body = new FormData();
      body.append("file", selected);
      const payload = await api("/api/import/preview", { method: "POST", body, raw: true });
      setPreview(payload);
      setFile(selected);
      setNotice("Controle geslaagd. Bekijk de voorvertoning voordat je importeert.");
    } catch (exc) {
      setPreview(null);
      setFile(null);
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  async function runApply() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const q = overwrite ? "?overwrite=true" : "?overwrite=false";
      const payload = await api(`/api/import/apply${q}`, { method: "POST", body, raw: true });
      setNotice(
        `Import afgerond. Back-up: ${payload.backup}. Samenvatting: ${JSON.stringify(payload.result?.stats || {})}`
      );
      setPreview(null);
      setFile(null);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  const exportUrl = scopeClient
    ? `${API_URL}/api/export/package.json?client_id=${encodeURIComponent(scopeClient)}`
    : `${API_URL}/api/export/package.json`;

  return (
    <div className="stack">
      <p className="hint">
        Volledige dashboard-export en -import als JSON (zonder API-sleutels of Meta-tokens).
        Excel/CSV voor berichten staat bij Socialmediaberichten → Alle berichten → Importeren &amp;
        exporteren. Voor import maakt HAMSTER automatisch een databaseback-up; bij fouten wordt die
        teruggezet.
      </p>

      <section className="card stack">
        <h3>Exporteren</h3>
        <label>
          Optioneel: alleen één klant-ID
          <input
            value={scopeClient}
            onChange={(e) => setScopeClient(e.target.value)}
            placeholder="leeg = alle klanten"
          />
        </label>
        <div className="row-actions wrap">
          <a className="primary" href={exportUrl}>
            JSON-back-up downloaden
          </a>
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/export/posts.csv`}>
              Berichten-CSV downloaden (klant)
            </a>
          ) : null}
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/logs/export.csv`}>
              Contentlogboek-CSV downloaden
            </a>
          ) : null}
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/activity/export.csv`}>
              Activiteiten-CSV downloaden
            </a>
          ) : null}
        </div>
        <p className="hint">
          Inbegrepen: klantinstellingen (zonder tokens), strategie, doelen, formats/legenda,
          contentpijlers, hooks, berichtkoppelingen, rapporten, activiteit/logboeken. Nooit:
          client_meta_secrets of API-sleutels.
        </p>
      </section>

      <section className="card stack">
        <h3>Importeren</h3>
        <label className="secondary file-btn">
          JSON kiezen (voorvertoning)
          <input
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const selected = e.target.files?.[0];
              if (selected) runPreview(selected);
              e.target.value = "";
            }}
          />
        </label>
        <label className="row-actions">
          <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
          Bestaande gegevens overschrijven (bewuste keuze)
        </label>
        {preview ? (
          <>
            <p className="banner">
              Controle ok · versie {preview.validation?.version} · geëxporteerd{" "}
              {preview.validation?.exported_at || "—"}
            </p>
            <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(preview.summary, null, 2)}
            </pre>
            <p className="hint">{preview.note}</p>
            <h4>Voorbeeldacties</h4>
            <pre className="hint" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
              {JSON.stringify(preview.sample_actions, null, 2)}
            </pre>
            <div className="row-actions">
              <button className="primary" type="button" disabled={busy} onClick={runApply}>
                {busy ? "Bezig…" : "Import uitvoeren (na back-up)"}
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  setPreview(null);
                  setFile(null);
                }}
              >
                Annuleren
              </button>
            </div>
          </>
        ) : null}
      </section>

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
    </div>
  );
}
