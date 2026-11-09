import { useEffect, useState } from "react";
import { api } from "../api.js";
import ResultCard from "../components/ResultCard.jsx";

export default function PerformancePage({
  client,
  onOpenLogs,
  onOpenFeed,
  onOpenPost,
  onSynced,
  selection: controlledSelection,
  onSelectionChange,
}) {
  const [instagram, setInstagram] = useState(true);
  const [facebook, setFacebook] = useState(true);
  const [internalSelection, setInternalSelection] = useState("");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const selection =
    controlledSelection !== undefined && controlledSelection !== null
      ? controlledSelection
      : internalSelection;

  function setSelection(next) {
    if (onSelectionChange) onSelectionChange(next);
    else setInternalSelection(next);
  }

  const openPost = onOpenPost || onOpenLogs || onOpenFeed;

  const platforms = [
    ...(instagram ? ["instagram"] : []),
    ...(facebook ? ["facebook"] : []),
  ];

  useEffect(() => {
    if (controlledSelection === undefined) setInternalSelection("");
  }, [client.id]);

  useEffect(() => {
    setError("");
    setPayload(null);
    if (!platforms.length) {
      setPayload({
        months: [],
        sections: [],
        empty_message: "Select at least one platform.",
        post_count: 0,
      });
      return;
    }
    const params = new URLSearchParams();
    params.set("platforms", platforms.join(","));
    if (selection) {
      params.set("year", selection.split("-")[0]);
      params.set("month", selection.split("-")[1]);
    }
    api(`/api/clients/${client.id}/performance?${params}`)
      .then((data) => {
        setPayload(data);
        if (!selection && data.selected) {
          const next = `${data.selected.year}-${String(data.selected.month).padStart(2, "0")}`;
          setSelection(next);
        }
      })
      .catch((exc) => setError(exc.message));
  }, [client.id, selection, platforms.join(",")]);

  async function refreshFigures() {
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/clients/${client.id}/posts/fetch`, { method: "POST", body: {} });
      setNotice("Figures refreshed from Meta. Rankings below are totals to date.");
      onSynced?.();
      const params = new URLSearchParams({ platforms: platforms.join(",") });
      if (selection) {
        params.set("year", selection.split("-")[0]);
        params.set("month", selection.split("-")[1]);
      }
      setPayload(await api(`/api/clients/${client.id}/performance?${params}`));
    } catch (exc) {
      setError(exc.message);
    } finally {
      setRefreshing(false);
    }
  }

  if (error) return <p className="banner error">{error}</p>;
  if (!payload) return <p className="muted">Loading…</p>;
  if (payload.empty_message && !payload.months?.length) {
    return <p className="banner">{payload.empty_message}</p>;
  }

  return (
    <div className="stack">
      <p className="banner">
        Rankings include Instagram and Facebook only. LinkedIn is not included.
      </p>
      <div className="filters">
        <label>
          Month
          <select value={selection} onChange={(event) => setSelection(event.target.value)}>
            {(payload.months || []).map((item) => (
              <option key={`${item.year}-${item.month}`} value={`${item.year}-${String(item.month).padStart(2, "0")}`}>
                {item.select_label || `${item.label} (${item.count})`}
              </option>
            ))}
          </select>
        </label>
        <div>
          <span className="sidebar-title">Platforms</span>
          <div className="filter-chips">
            <button type="button" className={instagram ? "chip is-on" : "chip"} onClick={() => setInstagram((v) => !v)}>
              Instagram
            </button>
            <button type="button" className={facebook ? "chip is-on" : "chip"} onClick={() => setFacebook((v) => !v)}>
              Facebook
            </button>
          </div>
        </div>
        <div className="row-actions" style={{ alignItems: "end" }}>
          <button
            className="secondary"
            type="button"
            disabled={!payload.refresh_available || refreshing}
            onClick={refreshFigures}
          >
            {refreshing ? "Refreshing figures…" : "Refresh figures"}
          </button>
        </div>
      </div>

      {payload.post_count === 0 ? (
        <p className="banner">
          No posts in <strong>{payload.selected?.label}</strong>.
          {payload.latest_month_label ? ` Latest available month: ${payload.latest_month_label}.` : ""}{" "}
          Click Sync Meta in the sidebar to fetch recent posts.
        </p>
      ) : null}

      {notice ? <p className="banner">{notice}</p> : null}
      {payload.caption ? <p className="hint">{payload.caption}</p> : null}

      {(payload.sections || []).map((section, index) => (
        <section key={section.metric} className="stack">
          {index > 0 ? <hr className="rro-perf-section-divider" /> : null}
          <h3 className="rro-perf-section-header">{section.header || `${section.label} · top 3 · to date`}</h3>
          {!section.posts.length ? (
            <div className="banner">No posts with this metric in the selected month.</div>
          ) : (
            <div className="results-list">
              {section.posts.map((post) => (
                <ResultCard
                  key={`${section.metric}-${post.id}`}
                  post={post}
                  highlightMetric={section.metric}
                  rankBanner={
                    <div className="rro-perf-rank-banner">
                      <span className="rro-perf-rank-badge">#{post.rank}</span>
                      {` · ${section.label}: `}
                      <strong>{post.metric_value_label ?? post.metric_value}</strong>
                    </div>
                  }
                  onOpenPost={openPost}
                />
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
