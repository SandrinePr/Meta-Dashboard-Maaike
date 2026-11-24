import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function OverviewPage({ client, onOpenPosts, onOpenClients }) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [fetching, setFetching] = useState(false);

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/overview`);
    setOverview(payload);
  }

  useEffect(() => {
    setError("");
    setNotice("");
    reload().catch((exc) => setError(exc.message));
  }, [client.id]);

  if (!overview) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Laden…</p>;
  }

  return (
    <div className="stack">
      <p className="hint">Samenvatting voor de geselecteerde klant. Geen gegevens van andere klanten.</p>
      <p className="status">{overview.status_label}</p>
      <div className="stat-grid">
        <div className="stat-card">
          Berichten
          <strong>{overview.post_count}</strong>
        </div>
        <div className="stat-card">
          Instagram
          <strong>{overview.instagram_count}</strong>
        </div>
        <div className="stat-card">
          Facebook
          <strong>{overview.facebook_count}</strong>
        </div>
        <div className="stat-card">
          Laatste synchronisatie
          <strong style={{ fontSize: "1rem" }}>{overview.synced_at}</strong>
        </div>
      </div>
      <p>
        <strong>Periode:</strong> {overview.period_from} – {overview.period_until}
      </p>
      {overview.page_name ? (
        <p>
          <strong>Facebookpagina:</strong> {overview.page_name}
          {overview.ig_username ? ` · @${overview.ig_username}` : ""}
        </p>
      ) : null}
      <p className="hint">{overview.fetch_message}</p>
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      <div className="row-actions">
        <button className="primary" type="button" onClick={onOpenPosts}>
          Naar Berichten
        </button>
        <button
          className="secondary"
          type="button"
          disabled={!overview.fetch_available || fetching}
          onClick={() => {
            setFetching(true);
            setError("");
            api(`/api/clients/${client.id}/posts/fetch`, { method: "POST", body: {} })
              .then((payload) => {
                setNotice(payload.fetch_message || "Ophalen afgerond.");
                return reload();
              })
              .catch((exc) => setError(exc.message))
              .finally(() => setFetching(false));
          }}
        >
          {fetching ? "Bezig met ophalen…" : "Berichten ophalen"}
        </button>
        {!overview.connected ? (
          <button className="secondary" type="button" onClick={onOpenClients}>
            Meta koppelen
          </button>
        ) : null}
      </div>
    </div>
  );
}
