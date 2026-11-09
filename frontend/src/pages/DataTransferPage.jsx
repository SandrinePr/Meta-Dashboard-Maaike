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
      setNotice("Validation succeeded. Review the preview before import.");
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
        `Import completed. Backup: ${payload.backup}. Stats: ${JSON.stringify(payload.result?.stats || {})}`
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
        Full dashboard export/import as versionable JSON (without API keys or Meta tokens). Post
        Excel/CSV import and export live under Social posts → All posts → Import &amp; Export. Before
        import a database backup is created automatically; on errors it is rolled back.
      </p>

      <section className="card stack">
        <h3>Export</h3>
        <label>
          Optional: one client ID only
          <input
            value={scopeClient}
            onChange={(e) => setScopeClient(e.target.value)}
            placeholder="empty = all clients"
          />
        </label>
        <div className="row-actions wrap">
          <a className="primary" href={exportUrl}>
            Download JSON backup
          </a>
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/export/posts.csv`}>
              Download posts CSV (client)
            </a>
          ) : null}
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/logs/export.csv`}>
              Download content-logs CSV
            </a>
          ) : null}
          {scopeClient ? (
            <a className="secondary" href={`${API_URL}/api/clients/${scopeClient}/activity/export.csv`}>
              Download activity CSV
            </a>
          ) : null}
        </div>
        <p className="hint">
          Included: client settings (without tokens), strategy, targets, formats/legends, content pillars, hooks,
          post links, reports, activity/logs. Never: client_meta_secrets or API keys.
        </p>
      </section>

      <section className="card stack">
        <h3>Import</h3>
        <label className="secondary file-btn">
          Choose JSON (preview)
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
          Overwrite existing data (explicit choice)
        </label>
        {preview ? (
          <>
            <p className="banner">
              Validation OK · version {preview.validation?.version} · exported {preview.validation?.exported_at || "—"}
            </p>
            <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(preview.summary, null, 2)}
            </pre>
            <p className="hint">{preview.note}</p>
            <h4>Sample actions</h4>
            <pre className="hint" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
              {JSON.stringify(preview.sample_actions, null, 2)}
            </pre>
            <div className="row-actions">
              <button className="primary" type="button" disabled={busy} onClick={runApply}>
                {busy ? "Working…" : "Run import (after backup)"}
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  setPreview(null);
                  setFile(null);
                }}
              >
                Cancel
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
