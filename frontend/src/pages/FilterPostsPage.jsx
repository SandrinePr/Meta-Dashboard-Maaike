import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import ResultCard, { metricLabel } from "../components/ResultCard.jsx";

export default function FilterPostsPage({ client, focusPostId, onOpenLogs, onClearFocus }) {
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [instagram, setInstagram] = useState(true);
  const [facebook, setFacebook] = useState(true);
  const [types, setTypes] = useState({
    comment: true,
    tag: true,
    hashtag: true,
    caption: true,
  });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [payload, setPayload] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const platforms = useMemo(() => {
    const list = [];
    if (instagram) list.push("instagram");
    if (facebook) list.push("facebook");
    return list;
  }, [instagram, facebook]);

  const typeList = useMemo(
    () => Object.entries(types).filter(([, on]) => on).map(([key]) => key),
    [types],
  );

  async function load(reset = true) {
    setError("");
    if (!platforms.length) {
      setPayload({
        results: [],
        total: 0,
        has_more: false,
        empty_message: "Select at least one platform.",
      });
      return;
    }
    if (!typeList.length) {
      setPayload({
        results: [],
        total: 0,
        has_more: false,
        empty_message: "Select at least one type (Comments, Tags, Hashtags or Captions).",
      });
      return;
    }
    if (reset) setLoading(true);
    else setLoadingMore(true);
    try {
      const search = new URLSearchParams();
      if (query.trim()) search.set("q", query.trim());
      search.set("platforms", platforms.join(","));
      search.set("types", typeList.join(","));
      if (dateFrom) search.set("date_from", dateFrom);
      if (dateTo) search.set("date_to", dateTo);
      search.set("offset", reset ? "0" : String(payload?.results?.length || 0));
      const next = await api(`/api/clients/${client.id}/filter-posts?${search}`);
      if (reset) setPayload(next);
      else {
        setPayload({
          ...next,
          results: [...(payload?.results || []), ...(next.results || [])],
        });
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    setDetail(null);
    load(true);
  }, [client.id, query, platforms.join(","), typeList.join(","), dateFrom, dateTo]);

  useEffect(() => {
    if (!focusPostId) return;
    api(`/api/clients/${client.id}/posts/${focusPostId}`)
      .then((item) => {
        setDetail(item);
        onClearFocus?.();
      })
      .catch((exc) => setError(exc.message));
  }, [client.id, focusPostId]);

  function runSearch(event) {
    event?.preventDefault?.();
    setQuery(draftQuery.trim());
  }

  function toggleType(key) {
    setTypes((current) => ({ ...current, [key]: !current[key] }));
  }

  return (
    <div className="stack">
      <p className="hint">
        Zoek lokaal in de opgehaalde content van deze klant (berichten en reacties).
      </p>
      <p className="banner">
        Platformen hier: alleen Instagram en Facebook (filters hieronder). LinkedIn en andere platformen
        staan niet op dit scherm — ze kunnen wel meetellen in Rapporten.
      </p>
      <form className="stack" onSubmit={runSearch}>
        <div className="search-form-header">
          <h3>Zoeken</h3>
        </div>
        <label>
          Zoekterm
          <input
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="Typ minimaal 3 tekens…"
          />
        </label>
        <div className="filters">
          <div>
            <span className="sidebar-title">Platformen</span>
            <div className="filter-chips">
              <Chip label="Instagram" on={instagram} onToggle={() => setInstagram((v) => !v)} />
              <Chip label="Facebook" on={facebook} onToggle={() => setFacebook((v) => !v)} />
            </div>
          </div>
          <div>
            <span className="sidebar-title">Type</span>
            <div className="filter-chips">
              <Chip label="Reacties" on={types.comment} onToggle={() => toggleType("comment")} />
              <Chip label="Tags" on={types.tag} onToggle={() => toggleType("tag")} />
              <Chip label="Hashtags" on={types.hashtag} onToggle={() => toggleType("hashtag")} />
              <Chip label="Bijschriften" on={types.caption} onToggle={() => toggleType("caption")} />
            </div>
          </div>
          <label>
            Datums
            <div className="row-actions">
              <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
              <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </div>
          </label>
        </div>
        <button className="primary" type="submit">
          Zoeken
        </button>
      </form>

      {error ? <p className="banner error">{error}</p> : null}
      {payload?.comments_note ? <p className="banner">{payload.comments_note}</p> : null}
      {payload?.query_too_short ? (
        <p className="banner">Typ minimaal {payload.min_query_length || 3} tekens om te zoeken.</p>
      ) : null}
      {loading && !payload ? <p className="muted">Laden…</p> : null}

      {detail ? (
        <ResultCard post={detail} query={query} onOpenLogs={onOpenLogs} onOpenDetails={() => setDetail(null)} />
      ) : null}

      {payload && !payload.query_too_short ? (
        <>
          <div className="rro-results-header">
            <h2>
              {query
                ? `Resultaten (${payload.results.length}${payload.total ? ` van ${payload.total}` : ""})`
                : `Laatste berichten (${payload.results.length})`}
            </h2>
            <p className="hint">
              Platformen: {[instagram && "Instagram", facebook && "Facebook"].filter(Boolean).join(" · ") || "geen"}
              . LinkedIn staat niet op dit scherm.
            </p>
          </div>
          {payload.totals ? (
            <div className="rro-results-totals">
              Totale engagement:{" "}
              {Object.entries(payload.totals)
                .map(([key, value]) => `${metricLabel(key)} ${value}`)
                .join(" · ")}
              <div className="hint">
                <strong>n/a</strong> = nog niet opgehaald bij Meta (niet hetzelfde als 0).
              </div>
            </div>
          ) : null}
          {!payload.results.length ? (
            <p className="banner">{payload.empty_message || "Geen resultaten in de lokale database."}</p>
          ) : null}
          <div className="results-list">
            {payload.results.map((item) =>
              item.entity_type === "comment" ? (
                <CommentCard key={item.id} item={item} query={query} onOpenLogs={onOpenLogs} />
              ) : (
                <ResultCard
                  key={item.id}
                  post={item}
                  query={query}
                  onOpenDetails={setDetail}
                  onOpenLogs={onOpenLogs}
                />
              ),
            )}
          </div>
          {payload.has_more ? (
            <button className="secondary" type="button" disabled={loadingMore} onClick={() => load(false)}>
              {loadingMore ? "Laden…" : `Meer laden (${payload.results.length} van ${payload.total})`}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function CommentCard({ item, query, onOpenLogs }) {
  return (
    <article className="rro-comment-card">
      <div className="rro-card-badges">
        <span className={`badge badge-${item.platform}`}>{item.platform_label}</span>
        <span className="badge badge-comment">Comment</span>
        {(item.match_badges || []).map((badge) => (
          <span key={badge} className={`badge badge-${badge}`}>
            {badge}
          </span>
        ))}
      </div>
      <div className="rro-card-date">{item.published_label}</div>
      <p className="muted">Reactie op {item.platform_label}-post · {item.author_name}</p>
      <div className="rro-card-text">{item.text || "No text."}</div>
      <div className="row-actions">
        {item.post_id ? (
          <button className="secondary" type="button" onClick={() => onOpenLogs?.(item.post_id)}>
            Open post in Logs
          </button>
        ) : null}
        {item.permalink ? (
          <a className="rro-btn-link" href={item.permalink} target="_blank" rel="noreferrer">
            Bekijk post
          </a>
        ) : null}
      </div>
    </article>
  );
}

function Chip({ label, on, onToggle }) {
  return (
    <button type="button" className={on ? "chip is-on" : "chip"} onClick={onToggle}>
      <input type="checkbox" checked={on} readOnly tabIndex={-1} />
      {label}
    </button>
  );
}
