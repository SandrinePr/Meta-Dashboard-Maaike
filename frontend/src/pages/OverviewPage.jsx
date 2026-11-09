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
    return error ? <p className="banner error">{error}</p> : <p className="muted">Loading…</p>;
  }

  return (
    <div className="stack">
      <p className="hint">Summary for the selected client. No data from other clients.</p>
      <p className="status">{overview.status_label}</p>
      <div className="stat-grid">
        <div className="stat-card">
          Posts
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
          Last sync
          <strong style={{ fontSize: "1rem" }}>{overview.synced_at}</strong>
        </div>
      </div>
      <p>
        <strong>Period:</strong> {overview.period_from} – {overview.period_until}
      </p>
      {overview.page_name ? (
        <p>
          <strong>Facebook page:</strong> {overview.page_name}
          {overview.ig_username ? ` · @${overview.ig_username}` : ""}
        </p>
      ) : null}
      <p className="hint">{overview.fetch_message}</p>
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      <div className="row-actions">
        <button className="primary" type="button" onClick={onOpenPosts}>
          Go to Posts
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
                setNotice(payload.fetch_message || "Fetch completed.");
                return reload();
              })
              .catch((exc) => setError(exc.message))
              .finally(() => setFetching(false));
          }}
        >
          {fetching ? "Fetching…" : "Fetch posts"}
        </button>
        {!overview.connected ? (
          <button className="secondary" type="button" onClick={onOpenClients}>
            Connect Meta
          </button>
        ) : null}
      </div>
    </div>
  );
}
