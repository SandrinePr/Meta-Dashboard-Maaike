import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import PostAnalysisPanel from "../components/PostAnalysisPanel.jsx";
import ResultCard, { metricLabel } from "../components/ResultCard.jsx";

const SORTS = [
  ["published_desc", "Newest first"],
  ["published_asc", "Oldest first"],
  ["likes_desc", "Most likes"],
  ["views_desc", "Most views"],
  ["comments_desc", "Most comments"],
  ["reach_desc", "Most reach"],
];

export default function FeedPage({ client, focusPostId, onOpenLogs, onClearFocus }) {
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [instagram, setInstagram] = useState(true);
  const [facebook, setFacebook] = useState(true);
  const [matchCaptions, setMatchCaptions] = useState(true);
  const [matchHashtags, setMatchHashtags] = useState(true);
  const [matchTags, setMatchTags] = useState(true);
  const [kind, setKind] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sort, setSort] = useState("published_desc");
  const [payload, setPayload] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const platform = useMemo(() => {
    if (instagram && facebook) return "";
    if (instagram) return "instagram";
    if (facebook) return "facebook";
    return "__none__";
  }, [instagram, facebook]);

  const params = useMemo(() => {
    const search = new URLSearchParams();
    if (query.trim()) search.set("q", query.trim());
    if (platform && platform !== "__none__") search.set("platform", platform);
    if (kind) search.set("kind", kind);
    if (dateFrom) search.set("date_from", dateFrom);
    if (dateTo) search.set("date_to", dateTo);
    search.set("sort", sort);
    search.set("offset", "0");
    return search;
  }, [query, platform, kind, dateFrom, dateTo, sort]);

  async function load(reset = true) {
    setError("");
    if (platform === "__none__") {
      setPayload({
        posts: [],
        total: 0,
        has_more: false,
        empty_message: "Select at least one platform.",
        min_query_length: 3,
        available_kinds: payload?.available_kinds || [],
        kind_labels: payload?.kind_labels || {},
      });
      return;
    }
    if (reset) setLoading(true);
    else setLoadingMore(true);
    try {
      const search = new URLSearchParams(params);
      if (!reset && payload) search.set("offset", String(payload.posts.length));
      const next = await api(`/api/clients/${client.id}/feed?${search.toString()}`);
      const filtered = {
        ...next,
        posts: filterByMatchTypes(next.posts || [], query, {
          captions: matchCaptions,
          hashtags: matchHashtags,
          tags: matchTags,
        }),
      };
      if (next.query_too_short) {
        setPayload({ ...filtered, posts: [] });
      } else if (reset) {
        setPayload(filtered);
      } else {
        setPayload({
          ...filtered,
          posts: [...(payload?.posts || []), ...filtered.posts],
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
  }, [client.id, params.toString(), matchCaptions, matchHashtags, matchTags]);

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

  const totals = useMemo(() => sumMetrics(payload?.posts || []), [payload]);

  return (
    <div className="stack">
      <p className="hint">
        Search locally in synchronised Instagram and Facebook posts for this client. Logs remains the
        strategy table for the same posts.
      </p>

      <form className="stack" onSubmit={runSearch}>
        <div className="search-form-header">
          <h3>Search</h3>
        </div>
        <label>
          Search term
          <input
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="Type at least 3 characters..."
          />
        </label>
        <div className="filters">
          <div>
            <span className="sidebar-title">Platforms</span>
            <div className="filter-chips">
              <Chip label="Instagram" on={instagram} onToggle={() => setInstagram((v) => !v)} />
              <Chip label="Facebook" on={facebook} onToggle={() => setFacebook((v) => !v)} />
            </div>
          </div>
          <div>
            <span className="sidebar-title">Type</span>
            <div className="filter-chips">
              <Chip label="Captions" on={matchCaptions} onToggle={() => setMatchCaptions((v) => !v)} />
              <Chip label="Hashtags" on={matchHashtags} onToggle={() => setMatchHashtags((v) => !v)} />
              <Chip label="Tags" on={matchTags} onToggle={() => setMatchTags((v) => !v)} />
            </div>
          </div>
          <label>
            Dates
            <div className="row-actions">
              <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
              <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </div>
          </label>
        </div>
        <div className="filters filters-wide">
          <label>
            Media type
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="">All</option>
              {(payload?.available_kinds || []).map((item) => (
                <option key={item} value={item}>
                  {payload.kind_labels?.[item] || item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sort
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              {SORTS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="row-actions" style={{ alignItems: "end" }}>
            <button className="primary" type="submit">
              Search
            </button>
          </div>
        </div>
      </form>

      {error ? <p className="banner error">{error}</p> : null}
      {payload?.query_too_short ? (
        <p className="banner">Type at least {payload.min_query_length || 3} characters to search.</p>
      ) : null}
      {loading && !payload ? <p className="muted">Loading…</p> : null}

      {detail ? (
        <PostDetail
          clientId={client.id}
          post={detail}
          onClose={() => setDetail(null)}
          onOpenLogs={onOpenLogs}
        />
      ) : null}

      {payload && !payload.query_too_short ? (
        <>
          <div className="rro-results-header">
            <h2>
              {query
                ? `Results (${payload.posts.length}${payload.total ? ` of ${payload.total}` : ""})`
                : `Latest posts (${payload.posts.length})`}
            </h2>
          </div>
          {totals ? (
            <div className="rro-results-totals">
              Total engagement: {totals}
              <div className="hint">
                <strong>n/a</strong> = not yet fetched from Meta (not the same as 0).
              </div>
            </div>
          ) : null}
          {!payload.posts.length ? <p className="banner">{payload.empty_message || "No results found in the local database."}</p> : null}
          <div className="results-list">
            {payload.posts.map((post) => (
              <ResultCard
                key={post.id}
                post={post}
                query={query}
                focused={detail?.id === post.id}
                onOpenDetails={setDetail}
                onOpenLogs={onOpenLogs}
              />
            ))}
          </div>
          {payload.has_more ? (
            <button className="secondary" type="button" disabled={loadingMore} onClick={() => load(false)}>
              {loadingMore ? "Loading…" : `Load more (${payload.posts.length} of ${payload.total})`}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
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

function filterByMatchTypes(posts, query, flags) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return posts;
  const wantAny = flags.captions || flags.hashtags || flags.tags;
  if (!wantAny) return [];
  return posts.filter((post) => {
    const text = (post.caption || "").toLowerCase();
    const captionHit = flags.captions && text.includes(q);
    const hashtagHit =
      flags.hashtags && (text.includes(`#${q.replace(/^#/, "")}`) || (q.startsWith("#") && text.includes(q)));
    const tagHit =
      flags.tags && (text.includes(`@${q.replace(/^@/, "")}`) || (q.startsWith("@") && text.includes(q)));
    return captionHit || hashtagHit || tagHit;
  });
}

function sumMetrics(posts) {
  const keys = ["views", "likes", "comments", "saves", "shares"];
  const totals = {};
  for (const post of posts) {
    for (const key of keys) {
      const metric = post.metrics?.[key];
      if (!metric || metric.available === false) continue;
      const raw = Number(metric.value ?? metric.label);
      if (!Number.isFinite(raw)) continue;
      totals[key] = (totals[key] || 0) + raw;
    }
  }
  const parts = Object.entries(totals).map(([key, value]) => `${metricLabel(key)} ${value}`);
  return parts.length ? parts.join(" · ") : "";
}

function PostDetail({ clientId, post, onClose, onOpenLogs }) {
  const [error, setError] = useState("");
  return (
    <section className="card feed-detail">
      <div className="carousel-track">
        {(post.media || []).length ? (
          post.media.map((item) =>
            item.kind === "video" ? (
              <video key={item.url} src={item.url} controls preload="metadata" referrerPolicy="no-referrer" />
            ) : (
              <img key={item.url} src={item.url} alt="" loading="lazy" referrerPolicy="no-referrer" />
            ),
          )
        ) : (
          <div className="feed-media-empty">No media available</div>
        )}
      </div>
      <div className="stack">
        <div className="rro-card-badges">
          <span className={`badge badge-${post.platform}`}>{post.platform_label}</span>
          <span className="badge badge-content">{post.content_kind_label}</span>
          <span className="badge">{post.published_label}</span>
        </div>
        <p className="muted">{post.account}</p>
        <p className="rro-card-text">{post.caption || "No caption available."}</p>
        <p>
          <strong>Format:</strong> {post.format_name}
        </p>
        <p>
          <strong>Pillar:</strong> {post.pillar_name}
        </p>
        <p>
          <strong>Hook:</strong> {post.hook || "—"}
        </p>
        <div className="metric-list">
          {Object.entries(post.metrics || {}).map(([name, metric]) => (
            <div key={name} className="card">
              <span className="muted">{metricLabel(name)}</span>
              <strong>{metric.label}</strong>
            </div>
          ))}
        </div>
        <div className="row-actions">
          <button className="secondary" type="button" onClick={onClose}>
            Close
          </button>
          <button className="primary" type="button" onClick={() => onOpenLogs(post.id)}>
            Open in Logs
          </button>
          {post.permalink ? (
            <a className="rro-btn-link" href={post.permalink} target="_blank" rel="noreferrer">
              View original
            </a>
          ) : null}
        </div>
        {error ? <p className="banner error">{error}</p> : null}
        <PostAnalysisPanel clientId={clientId} postId={post.id} onError={setError} />
      </div>
    </section>
  );
}
