import { useEffect, useMemo, useState } from "react";
import { api, API_URL } from "../api.js";
import PostAnalysisPanel from "../components/PostAnalysisPanel.jsx";
import RatingBadge from "../components/RatingBadge.jsx";

const EDITABLE = new Set(["Contentformat", "Contentpijler", "Hook"]);

export default function PostsPage({
  client,
  focusPostId,
  onOpenFeed,
  onClearFocus,
  initialDateFrom = "",
  initialDateTo = "",
  periodHint = "",
  showImportExportButton = true,
}) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [fetching, setFetching] = useState(false);
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [importExportOpen, setImportExportOpen] = useState(false);
  const [draftQuery, setDraftQuery] = useState("");
  const [filters, setFilters] = useState({
    q: "",
    platform: "",
    content_soort: "",
    format: "",
    pillar: "",
    date_from: initialDateFrom || "",
    date_to: initialDateTo || "",
    missing: "",
  });
  const [sortKey, setSortKey] = useState("date_desc");
  const [contentMatchIds, setContentMatchIds] = useState(null);
  const [contentMatchNote, setContentMatchNote] = useState("");

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/posts`);
    setOverview(payload);
  }

  useEffect(() => {
    setNotice("");
    setError("");
    setImportExportOpen(false);
    setDraftQuery("");
    setContentMatchIds(null);
    setContentMatchNote("");
    setFilters({
      q: "",
      platform: "",
      content_soort: "",
      format: "",
      pillar: "",
      date_from: initialDateFrom || "",
      date_to: initialDateTo || "",
      missing: "",
    });
    reload().catch((exc) => setError(exc.message));
  }, [client.id]);

  useEffect(() => {
    setFilters((current) => ({
      ...current,
      date_from: initialDateFrom || "",
      date_to: initialDateTo || "",
    }));
  }, [initialDateFrom, initialDateTo]);

  useEffect(() => {
    if (!focusPostId || !overview) return;
    const row = document.getElementById(`log-post-${focusPostId}`);
    if (row) {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("is-focused");
    }
    onClearFocus?.();
  }, [focusPostId, overview]);

  const totalPosts = overview?.posts?.length || 0;

  const platformAvailability = useMemo(() => {
    if (!overview?.posts?.length) return [];
    const counts = new Map();
    const seen = new Set();
    for (const post of overview.posts) {
      const id = post.id ?? post.post_id;
      if (id != null) {
        if (seen.has(id)) continue;
        seen.add(id);
      }
      const label =
        String(post.cells?.Platform || post.platform_label || post.platform || "Unknown").trim() ||
        "Unknown";
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    const preferred = ["Facebook", "Instagram", "LinkedIn", "LinkedIn - Zakelijk"];
    return [...counts.entries()].sort((a, b) => {
      const ia = preferred.indexOf(a[0]);
      const ib = preferred.indexOf(b[0]);
      if (ia !== -1 || ib !== -1) {
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
      }
      return a[0].localeCompare(b[0]);
    });
  }, [overview]);

  const filtersActive = Boolean(
    String(filters.q || "").trim() ||
      filters.platform ||
      filters.content_soort ||
      filters.format ||
      filters.pillar ||
      filters.missing ||
      filters.date_from ||
      filters.date_to ||
      contentMatchIds != null,
  );

  const filteredPosts = useMemo(() => {
    if (!overview) return [];
    const q = String(filters.q || "").trim().toLowerCase();
    const matchSet = contentMatchIds ? new Set(contentMatchIds) : null;
    const rows = overview.posts.filter((post) => {
      const cells = post.cells || {};
      if (matchSet && !matchSet.has(post.id) && !matchSet.has(post.post_id)) return false;
      if (q) {
        const hay = [
          JSON.stringify(cells),
          post.hook,
          post.insight,
          post.action,
          post.permalink,
          post.platform_label,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filters.platform && !String(cells.Platform || "").toLowerCase().includes(filters.platform.toLowerCase())) {
        return false;
      }
      if (
        filters.content_soort &&
        !String(cells.Contentsoort || "").toLowerCase().includes(filters.content_soort.toLowerCase())
      ) {
        return false;
      }
      if (filters.format && !String(cells.Contentformat || "").toLowerCase().includes(filters.format.toLowerCase())) {
        return false;
      }
      if (filters.pillar && !String(cells.Contentpijler || "").toLowerCase().includes(filters.pillar.toLowerCase())) {
        return false;
      }
      const missing = post.missing_classification || {
        format: post.format_id == null,
        pillar: post.pillar_id == null,
        hook: !String(post.hook || cells.Hook || "").trim(),
      };
      const hasMissing = Boolean(missing.any ?? (missing.format || missing.pillar || missing.hook));
      if (filters.missing === "any" && !hasMissing) return false;
      if (filters.missing === "format" && !missing.format) return false;
      if (filters.missing === "pillar" && !missing.pillar) return false;
      if (filters.missing === "hook" && !missing.hook) return false;
      const pub = String(cells.Publicatiedatum || "");
      const iso = pub.includes("-") ? pub.slice(0, 10) : "";
      if (filters.date_from && iso && iso < filters.date_from) return false;
      if (filters.date_to && iso && iso > filters.date_to) return false;
      return true;
    });
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const ca = a.cells || {};
      const cb = b.cells || {};
      const da = String(ca.Publicatiedatum || "").slice(0, 10);
      const db = String(cb.Publicatiedatum || "").slice(0, 10);
      if (sortKey === "date_asc") return da.localeCompare(db) || a.post_id - b.post_id;
      if (sortKey === "platform") {
        return String(ca.Platform || "").localeCompare(String(cb.Platform || "")) || db.localeCompare(da);
      }
      if (sortKey === "format") {
        return (
          String(ca.Contentformat || "").localeCompare(String(cb.Contentformat || "")) || db.localeCompare(da)
        );
      }
      // date_desc default
      return db.localeCompare(da) || b.post_id - a.post_id;
    });
    return sorted;
  }, [overview, filters, sortKey, contentMatchIds]);

  function exportUrl(ext) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const q = params.toString();
    return `${API_URL}/api/clients/${client.id}/logs/export.${ext}${q ? `?${q}` : ""}`;
  }

  async function runPreview(file) {
    setImporting(true);
    setError("");
    try {
      const body = new FormData();
      if (file) body.append("file", file);
      const payload = await api(`/api/clients/${client.id}/excel/preview`, {
        method: "POST",
        body,
        raw: true,
      });
      setPreview(payload);
      setNotice(
        `Import preview: ${payload.counts?.add || 0} new, ${payload.counts?.link || 0} to link, ${payload.counts?.conflict || 0} conflict, ${payload.counts?.skip || 0} skip.`
      );
    } catch (exc) {
      setError(exc.message);
    } finally {
      setImporting(false);
    }
  }

  async function runImport(file) {
    setImporting(true);
    setError("");
    try {
      const body = new FormData();
      if (file) body.append("file", file);
      const payload = await api(`/api/clients/${client.id}/excel/import`, {
        method: "POST",
        body,
        raw: true,
      });
      setPreview(null);
      await reload();
      setNotice(
        `Import complete: ${payload.applied?.added || 0} added, ${payload.applied?.linked || 0} linked, ${payload.applied?.conflicts || 0} conflict unchanged, ${payload.applied?.skipped || 0} skipped.`
      );
    } catch (exc) {
      setError(exc.message);
    } finally {
      setImporting(false);
    }
  }

  if (!overview) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Loading…</p>;
  }

  return (
    <div className="stack">
      <div className="search-form-header">
        <h3>All posts</h3>
      </div>
      <p className="hint">
        One post overview: search and filter, check figures, and edit format, content pillar, hook,
        insight and action. CSV/Excel export uses the same filtered selection. Empty, “n.v.t.” and 0
        stay distinct.
      </p>
      {periodHint ? <p className="hint">{periodHint}</p> : null}
      <p>
        <strong>Figures last updated:</strong> {overview.synced_at || "not fetched yet"}
      </p>
      <p className="banner">
        <strong>Total posts:</strong> {totalPosts}
        {platformAvailability.length ? (
          <>
            {" "}
            · <strong>By platform:</strong>{" "}
            {platformAvailability.map(([label, count]) => `${label} ${count}`).join(" · ")}
          </>
        ) : null}
        . Counts are unique post records for this client (comments and assessments are not posts).
        LinkedIn and other imported platforms stay visible here.
      </p>

      <RatingSettingsPanel
        client={client}
        summary={overview.rating_settings}
        onSaved={async () => {
          await reload();
          setNotice("Rating settings saved; scores recalculated.");
        }}
        onError={setError}
      />

      <ActivityPanel client={client} />

      <div className="row-actions wrap">
        {showImportExportButton ? (
          <button
            className={importExportOpen ? "primary" : "secondary"}
            type="button"
            onClick={() => setImportExportOpen((open) => !open)}
          >
            Import &amp; Export
          </button>
        ) : null}
        <button className="secondary" type="button" onClick={() => setShowAdd(true)}>
          Add post
        </button>
        <button
          className="secondary"
          type="button"
          disabled={!overview.fetch_available || fetching}
          title={
            overview.fetch_available
              ? "Fetch posts via the linked Meta accounts"
              : "Connect Meta first under client settings"
          }
          onClick={() => {
            setFetching(true);
            setError("");
            api(`/api/clients/${client.id}/posts/fetch`, { method: "POST", body: {} })
              .then((payload) => {
                setOverview(payload);
                setNotice(payload.fetch_message || "Fetch complete.");
              })
              .catch((exc) => setError(exc.message))
              .finally(() => setFetching(false));
          }}
        >
          {fetching ? "Fetching…" : "Fetch posts (Meta)"}
        </button>
      </div>

      {showImportExportButton && importExportOpen ? (
        <section className="card stack">
          <div className="search-form-header">
            <h3>Import &amp; Export</h3>
          </div>
          <p className="hint">
            Post/Excel import and filtered post exports for this client. Full dashboard JSON backup
            lives under Settings → Backup &amp; restore.
          </p>
          <div className="row-actions wrap">
            <label className="secondary file-btn">
              Import Excel
              <input
                type="file"
                accept=".xlsx,.xlsm"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0] || null;
                  runPreview(file);
                  event.target.value = "";
                }}
              />
            </label>
            <a className="secondary" href={exportUrl("xlsx")}>
              Download Excel
            </a>
            <a className="secondary" href={exportUrl("csv")}>
              Download CSV
            </a>
          </div>
        </section>
      ) : null}

      {!overview.fetch_available ? (
        <p className="banner warn-soft">
          Meta is not yet linked for this client. Go to <strong>client settings</strong> → connect
          Meta → choose Facebook/Instagram account → return here to fetch posts. Without a link
          you can still import Excel or edit existing rows.
        </p>
      ) : null}

      {preview ? (
        <div className="card stack">
          <p>
            Preview for <strong>{preview.file_name}</strong> / {preview.sheet}: {preview.row_count} rows.
          </p>
          <p className="hint">
            Conflicts and unclear matches stay unchanged until manual review. Re-import does not create
            unwanted duplicate posts.
          </p>
          <div className="row-actions">
            <button className="primary" type="button" disabled={importing} onClick={() => runImport(null)}>
              {importing ? "Importing…" : "Apply safe additions/updates"}
            </button>
            <button className="secondary" type="button" onClick={() => setPreview(null)}>
              Cancel preview
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Action</th>
                  <th>Platform</th>
                  <th>URL</th>
                  <th>Fields</th>
                  <th>Conflicts/issues</th>
                </tr>
              </thead>
              <tbody>
                {(preview.rows || []).slice(0, 40).map((row) => (
                  <tr key={row.excel_row}>
                    <td>{row.excel_row}</td>
                    <td>{row.action}</td>
                    <td>{row.platform_label}</td>
                    <td className="cell-clip">{row.permalink || "—"}</td>
                    <td>{(row.fields_to_fill || []).join(", ")}</td>
                    <td>{[...(row.conflicts || []), ...(row.issues || [])].join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(preview.rows || []).length > 40 ? (
            <p className="hint">Showing first 40 preview rows of {preview.rows.length}.</p>
          ) : null}
        </div>
      ) : null}

      <section className="card stack">
        <div className="search-form-header">
          <h3>Search, filters &amp; sorting</h3>
        </div>
        <form
          className="filters-row"
          onSubmit={(event) => {
            event.preventDefault();
            setFilters({ ...filters, q: draftQuery.trim() });
          }}
        >
          <label style={{ flex: "1 1 16rem" }}>
            Search
            <input
              value={draftQuery}
              onChange={(e) => setDraftQuery(e.target.value)}
              placeholder="Caption, hook, insight, platform, URL…"
            />
          </label>
          <div className="row-actions" style={{ alignItems: "end" }}>
            <button className="primary" type="submit">
              Search
            </button>
            <button
              className="secondary"
              type="button"
              onClick={() => {
                setDraftQuery("");
                setFilters({ ...filters, q: "" });
              }}
            >
              Clear search
            </button>
          </div>
        </form>
        <div className="filters-row">
          <label>
            Platform/account
            <input
              value={filters.platform}
              onChange={(e) => setFilters({ ...filters, platform: e.target.value })}
              placeholder="Instagram / LinkedIn…"
            />
          </label>
          <label>
            Content type
            <input
              value={filters.content_soort}
              onChange={(e) => setFilters({ ...filters, content_soort: e.target.value })}
            />
          </label>
          <label>
            Format
            <input value={filters.format} onChange={(e) => setFilters({ ...filters, format: e.target.value })} />
          </label>
          <label>
            Content pillar
            <input value={filters.pillar} onChange={(e) => setFilters({ ...filters, pillar: e.target.value })} />
          </label>
          <label>
            Missing classification
            <select value={filters.missing} onChange={(e) => setFilters({ ...filters, missing: e.target.value })}>
              <option value="">All posts</option>
              <option value="any">Format, pillar or hook missing</option>
              <option value="format">Format missing</option>
              <option value="pillar">Pillar missing</option>
              <option value="hook">Hook missing</option>
            </select>
          </label>
          <label>
            From
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
            />
          </label>
          <label>
            Sort
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
              <option value="date_desc">Newest publication first</option>
              <option value="date_asc">Oldest publication first</option>
              <option value="platform">Platform (A–Z)</option>
              <option value="format">Format (A–Z)</option>
            </select>
          </label>
        </div>
        <ContentMatchSearch
          client={client}
          onMatch={(ids, note) => {
            setContentMatchIds(ids);
            setContentMatchNote(note || "");
          }}
          onClear={() => {
            setContentMatchIds(null);
            setContentMatchNote("");
          }}
          active={contentMatchIds != null}
        />
        <p className="hint">
          {filtersActive ? (
            <>
              <strong>Found:</strong> {filteredPosts.length} posts (of {totalPosts} total for this
              client)
            </>
          ) : (
            <>
              Showing all <strong>{totalPosts}</strong> posts for this client
            </>
          )}
          {filters.q ? ` · search “${filters.q}”` : ""}
          {contentMatchNote ? ` · ${contentMatchNote}` : ""}. Download CSV/Excel uses the same filters
          (including search and “missing classification”). Sorting applies on screen; export follows
          publication date newest→oldest.
        </p>
      </section>

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      {!overview.posts.length ? (
        <p className="banner">
          No posts yet for this client. Link Meta under client settings and click “Fetch posts”, or import
          an Excel file above.
        </p>
      ) : null}

      {filteredPosts.length ? (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {overview.columns.map((column) => (
                    <th key={column}>{overview.column_labels?.[column] || column}</th>
                  ))}
                  <th>Save</th>
                </tr>
              </thead>
              <tbody>
                {filteredPosts.map((post) => (
                  <PostDesktop
                    key={post.id}
                    clientId={client.id}
                    post={post}
                    columns={overview.columns}
                    columnLabels={overview.column_labels}
                    formats={overview.formats}
                    pillars={overview.pillars}
                    hooks={overview.hooks || []}
                    unsetLabel={overview.unset_label}
                    onOpenFeed={onOpenFeed}
                    onSaved={async () => {
                      await reload();
                      setNotice("Saved.");
                    }}
                    onError={setError}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="cards">
            {filteredPosts.map((post) => (
              <PostCard
                key={`card-${post.id}`}
                clientId={client.id}
                post={post}
                columns={overview.columns}
                columnLabels={overview.column_labels}
                formats={overview.formats}
                pillars={overview.pillars}
                hooks={overview.hooks || []}
                unsetLabel={overview.unset_label}
                onOpenFeed={onOpenFeed}
                onSaved={async () => {
                  await reload();
                  setNotice("Saved.");
                }}
                onError={setError}
              />
            ))}
          </div>
        </>
      ) : (
        <p className="banner">{overview.empty_message}</p>
      )}

      {showAdd ? (
        <AddPostModal
          clientId={client.id}
          onClose={() => setShowAdd(false)}
          onCreated={async () => {
            setShowAdd(false);
            await reload();
            setNotice("Post added manually.");
          }}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

function ContentMatchSearch({ client, onMatch, onClear, active }) {
  const [query, setQuery] = useState("");
  const [instagram, setInstagram] = useState(true);
  const [facebook, setFacebook] = useState(true);
  const [types, setTypes] = useState({
    comment: true,
    tag: true,
    hashtag: true,
    caption: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function runSearch(event) {
    event?.preventDefault?.();
    const q = query.trim();
    if (q.length < 3) {
      setError("Type at least 3 characters for content search.");
      return;
    }
    const platforms = [
      ...(instagram ? ["instagram"] : []),
      ...(facebook ? ["facebook"] : []),
    ];
    const typeList = Object.entries(types)
      .filter(([, on]) => on)
      .map(([key]) => key);
    if (!platforms.length || !typeList.length) {
      setError("Select at least one platform and type.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const search = new URLSearchParams();
      search.set("q", q);
      search.set("platforms", platforms.join(","));
      search.set("types", typeList.join(","));
      search.set("offset", "0");
      const payload = await api(`/api/clients/${client.id}/filter-posts?${search}`);
      const ids = [];
      for (const item of payload.results || []) {
        const id = item.post_id || item.id;
        if (id != null && !ids.includes(id)) ids.push(id);
      }
      onMatch?.(
        ids,
        `content search “${q}”: ${ids.length} matching post(s) (Instagram/Facebook captions & comments; LinkedIn rows stay in the full list when this filter is cleared)`,
      );
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="hint">
        Optional: search captions, comments, tags and hashtags (Instagram/Facebook). Matches filter
        this same All posts table — no second post list. Clear to show LinkedIn/imported rows again.
      </p>
      <form className="filters-row" onSubmit={runSearch}>
        <label style={{ flex: "1 1 16rem" }}>
          Content search (comments / tags / hashtags / captions)
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="At least 3 characters…"
          />
        </label>
        <div className="filter-chips" style={{ alignSelf: "end" }}>
          <button
            type="button"
            className={instagram ? "chip is-on" : "chip"}
            onClick={() => setInstagram((v) => !v)}
          >
            Instagram
          </button>
          <button
            type="button"
            className={facebook ? "chip is-on" : "chip"}
            onClick={() => setFacebook((v) => !v)}
          >
            Facebook
          </button>
          {Object.entries(types).map(([key, on]) => (
            <button
              key={key}
              type="button"
              className={on ? "chip is-on" : "chip"}
              onClick={() => setTypes((current) => ({ ...current, [key]: !current[key] }))}
            >
              {key}
            </button>
          ))}
        </div>
        <div className="row-actions" style={{ alignItems: "end" }}>
          <button className="secondary" type="submit" disabled={busy}>
            {busy ? "Searching…" : "Filter table"}
          </button>
          {active ? (
            <button
              className="secondary"
              type="button"
              onClick={() => {
                setQuery("");
                setError("");
                onClear?.();
              }}
            >
              Clear content filter
            </button>
          ) : null}
        </div>
      </form>
      {error ? <p className="banner error">{error}</p> : null}
    </div>
  );
}

function ActivityPanel({ client }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({
    activity_type: "",
    status: "",
    errors_only: false,
  });

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.activity_type) params.set("activity_type", filters.activity_type);
    if (filters.status) params.set("status", filters.status);
    if (filters.errors_only) params.set("errors_only", "true");
    const q = params.toString();
    api(`/api/clients/${client.id}/activity${q ? `?${q}` : ""}`)
      .then(setData)
      .catch((exc) => setError(exc.message));
  }, [client.id, filters]);

  const exportHref = (() => {
    const params = new URLSearchParams();
    if (filters.activity_type) params.set("activity_type", filters.activity_type);
    if (filters.status) params.set("status", filters.status);
    if (filters.errors_only) params.set("errors_only", "true");
    const q = params.toString();
    return `${API_URL}/api/clients/${client.id}/activity/export.csv${q ? `?${q}` : ""}`;
  })();

  return (
    <section className="card stack">
      <h3>Activity overview</h3>
      <p className="hint">{data?.note || "Loading…"}</p>
      <div className="filters-row">
        <label>
          Type
          <select
            value={filters.activity_type}
            onChange={(e) => setFilters({ ...filters, activity_type: e.target.value })}
          >
            <option value="">(all)</option>
            {(data?.activity_types || ["meta_sync", "excel_import", "ai", "report", "data_import"]).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">(all)</option>
            <option value="ok">ok</option>
            <option value="pending">pending</option>
            <option value="error">error</option>
            <option value="info">info</option>
          </select>
        </label>
        <label className="row-actions">
          <input
            type="checkbox"
            checked={filters.errors_only}
            onChange={(e) => setFilters({ ...filters, errors_only: e.target.checked })}
          />
          Errors only
        </label>
        <a className="secondary" href={exportHref}>
          Activity CSV
        </a>
      </div>
      {error ? <p className="banner error">{error}</p> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date/time</th>
              <th>Client</th>
              <th>Activity type</th>
              <th>Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {(data?.events || []).map((ev) => (
              <ActivityEventRows key={ev.id} ev={ev} />
            ))}
          </tbody>
        </table>
      </div>
      {!data?.events?.length ? <p className="hint">No activity events for these filters yet.</p> : null}
    </section>
  );
}

function ActivityEventRows({ ev }) {
  const [open, setOpen] = useState(false);
  const label = ev.display_label || ev.status || "—";
  const bucket = ev.status_bucket || "info";
  const showErrorRow = ev.is_error || bucket === "error";
  const attempts = ev.attempts || [];
  const earlier = attempts.filter((a) => !a.is_latest);
  const summary = ev.plain_summary || (showErrorRow ? ev.details : "") || "—";

  return (
    <>
      <tr className={showErrorRow ? "row-error" : undefined}>
        <td>{ev.occurred_at_label || ev.occurred_at || "—"}</td>
        <td>{ev.client_name}</td>
        <td>
          {ev.activity_type}
          {ev.title ? ` · ${ev.title}` : ""}
          {ev.is_report_series && ev.latest_report_id ? ` · #${ev.latest_report_id}` : null}
        </td>
        <td>
          <span className={`status-pill status-${bucket}`}>{label}</span>
        </td>
        <td>
          <div className="stack" style={{ gap: "0.35rem" }}>
            <span className={showErrorRow ? undefined : "cell-clip"}>
              {ev.display_status === "ready" && ev.has_earlier_failures
                ? "Latest attempt succeeded. Earlier failures are under Pogingen bekijken."
                : summary}
            </span>
            {earlier.length ? (
              <button
                type="button"
                className="secondary"
                style={{ alignSelf: "flex-start" }}
                onClick={() => setOpen((v) => !v)}
              >
                {open ? "Pogingen verbergen" : `Pogingen bekijken (${earlier.length})`}
              </button>
            ) : null}
          </div>
        </td>
      </tr>
      {open
        ? earlier.map((attempt) => (
            <tr
              key={attempt.id}
              className={attempt.is_error ? "row-error activity-attempt-row" : "activity-attempt-row"}
            >
              <td>{attempt.occurred_at_label || attempt.occurred_at || "—"}</td>
              <td>{ev.client_name}</td>
              <td>
                attempt · #{attempt.report_id}
                {attempt.title ? ` · ${attempt.title}` : ""}
              </td>
              <td>
                <span className={`status-pill status-${attempt.status_bucket || "info"}`}>
                  {attempt.display_label || attempt.status}
                </span>
              </td>
              <td>
                <div className="stack" style={{ gap: "0.25rem" }}>
                  {attempt.plain_summary ? <span>{attempt.plain_summary}</span> : null}
                  <span className="hint" style={{ whiteSpace: "pre-wrap" }}>
                    {attempt.details || attempt.status || "—"}
                  </span>
                </div>
              </td>
            </tr>
          ))
        : null}
    </>
  );
}

function AddPostModal({ clientId, onClose, onCreated, onError }) {
  const [platformLabel, setPlatformLabel] = useState("LinkedIn");
  const [permalink, setPermalink] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="modal-backdrop">
      <div className="modal card stack">
        <h3>Add post</h3>
        <p className="hint">For Excel/LinkedIn posts without a Meta link. No Meta login required.</p>
        <label>
          Platform label
          <input value={platformLabel} onChange={(e) => setPlatformLabel(e.target.value)} />
        </label>
        <label>
          Post URL
          <input value={permalink} onChange={(e) => setPermalink(e.target.value)} />
        </label>
        <label>
          Publication date
          <input type="date" value={publishedAt} onChange={(e) => setPublishedAt(e.target.value)} />
        </label>
        <label>
          Hook
          <input value={hook} onChange={(e) => setHook(e.target.value)} />
        </label>
        <div className="row-actions">
          <button
            className="primary"
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              onError("");
              try {
                await api(`/api/clients/${clientId}/posts/manual`, {
                  method: "POST",
                  body: {
                    platform_label: platformLabel,
                    platform_key: platformLabel.toLowerCase().replace(/\s+/g, "_").replace(/-+/g, "_"),
                    permalink,
                    published_at: publishedAt || undefined,
                    hook,
                  },
                });
                await onCreated();
              } catch (exc) {
                onError(exc.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Save
          </button>
          <button className="secondary" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function useDraft(post) {
  const [formatId, setFormatId] = useState(post.format_id == null ? "" : String(post.format_id));
  const [pillarId, setPillarId] = useState(post.pillar_id == null ? "" : String(post.pillar_id));
  const [hook, setHook] = useState(post.cells.Hook || "");
  return { formatId, setFormatId, pillarId, setPillarId, hook, setHook };
}

async function saveDraft(clientId, post, draft, onSaved, onError) {
  onError("");
  try {
    await api(`/api/clients/${clientId}/posts/${post.id}`, {
      method: "PATCH",
      body: {
        format_id: draft.formatId === "" ? null : Number(draft.formatId),
        pillar_id: draft.pillarId === "" ? null : Number(draft.pillarId),
        hook: draft.hook,
      },
    });
    await onSaved();
  } catch (exc) {
    onError(exc.message);
  }
}

function PostDesktop({ clientId, post, columns, columnLabels, formats, pillars, hooks, unsetLabel, onOpenFeed, onSaved, onError }) {
  const draft = useDraft(post);
  const [showAnalysis, setShowAnalysis] = useState(false);
  return (
    <>
      <tr id={`log-post-${post.id}`}>
        {columns.map((column) => (
          <td key={column}>
            {EDITABLE.has(column) ? (
              <Editor
                column={column}
                draft={draft}
                formats={formats}
                pillars={pillars}
                hooks={hooks}
                unsetLabel={unsetLabel}
                listId={`hook-list-${post.id}`}
              />
            ) : (
              <ReadCell column={column} value={post.cells[column]} post={post} />
            )}
          </td>
        ))}
        <td>
          <div className="row-actions">
            <button className="primary" type="button" onClick={() => saveDraft(clientId, post, draft, onSaved, onError)}>
              Save
            </button>
            <button className="secondary" type="button" onClick={() => setShowAnalysis((v) => !v)}>
              {showAnalysis ? "Hide media & insight" : "Media & insight"}
            </button>
            {onOpenFeed ? (
              <button className="secondary" type="button" onClick={() => onOpenFeed(post.id)}>
                Focus post
              </button>
            ) : null}
          </div>
          <MediaUploadPanel clientId={clientId} postId={post.id} onError={onError} onSaved={onSaved} />
        </td>
      </tr>
      {showAnalysis ? (
        <tr>
          <td colSpan={columns.length + 1}>
            <PostAnalysisPanel clientId={clientId} postId={post.id} onError={onError} onSaved={onSaved} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function PostCard({ clientId, post, columns, columnLabels, formats, pillars, hooks, unsetLabel, onOpenFeed, onSaved, onError }) {
  const draft = useDraft(post);
  const [showAnalysis, setShowAnalysis] = useState(false);
  return (
    <article className="card post-card" id={`log-post-card-${post.id}`}>
      {columns.map((column) => (
        <label key={column}>
          {columnLabels?.[column] || column}
          {EDITABLE.has(column) ? (
            <Editor
              column={column}
              draft={draft}
              formats={formats}
              pillars={pillars}
              hooks={hooks}
              unsetLabel={unsetLabel}
              listId={`hook-list-card-${post.id}`}
            />
          ) : (
            <ReadCell column={column} value={post.cells[column]} post={post} />
          )}
        </label>
      ))}
      {post.formula_rating ? <RatingBadge rating={post.formula_rating} showExplanation /> : null}
      <div className="row-actions">
        <button className="primary" type="button" onClick={() => saveDraft(clientId, post, draft, onSaved, onError)}>
          Save format, pillar and hook
        </button>
        <button className="secondary" type="button" onClick={() => setShowAnalysis((v) => !v)}>
          {showAnalysis ? "Hide media & insight" : "Media & insight"}
        </button>
        {onOpenFeed ? (
          <button className="secondary" type="button" onClick={() => onOpenFeed(post.id)}>
            Focus post
          </button>
        ) : null}
      </div>
      <MediaUploadPanel clientId={clientId} postId={post.id} onError={onError} onSaved={onSaved} />
      {showAnalysis ? (
        <PostAnalysisPanel clientId={clientId} postId={post.id} onError={onError} onSaved={onSaved} />
      ) : null}
    </article>
  );
}

function MediaUploadPanel({ clientId, postId, onError, onSaved }) {
  const [assets, setAssets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  function reload() {
    return api(`/api/clients/${clientId}/posts/${postId}/media`)
      .then((payload) => setAssets(payload.assets || []))
      .catch((exc) => onError?.(exc.message));
  }

  useEffect(() => {
    reload();
  }, [clientId, postId]);

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="hint">
        Upload media (without Meta). Carousel: multiple files, order adjustable. Files belong to
        this client/post.
      </p>
      <label className="secondary file-btn">
        Upload image/video
        <input
          type="file"
          accept="image/*,video/*,.jpg,.jpeg,.png,.webp,.gif,.mp4,.mov,.m4v,.webm"
          multiple
          hidden
          onChange={(event) => {
            const list = event.target.files;
            if (!list?.length) return;
            const body = new FormData();
            Array.from(list).forEach((file) => body.append("files", file));
            setBusy(true);
            setNotice("");
            api(`/api/clients/${clientId}/posts/${postId}/media`, { method: "POST", body, raw: true })
              .then(async (payload) => {
                setAssets(payload.assets || []);
                setNotice(
                  `${(payload.saved || []).length} file(s) saved` +
                    (payload.errors?.length ? `; ${payload.errors.join(" ")}` : "")
                );
                await onSaved?.();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => {
                setBusy(false);
                event.target.value = "";
              });
          }}
        />
      </label>
      {busy ? <p className="muted">Working…</p> : null}
      {notice ? <p className="hint">{notice}</p> : null}
      {assets.length ? (
        <ol className="plain-list">
          {assets.map((asset, index) => (
            <li key={asset.id}>
              {asset.position}. {asset.kind} · {asset.original_name} · {asset.byte_size} bytes · {asset.source}
              <span className="row-actions">
                <button
                  className="secondary"
                  type="button"
                  disabled={index === 0 || busy}
                  onClick={() => {
                    const ids = assets.map((a) => a.id);
                    const next = [...ids];
                    [next[index - 1], next[index]] = [next[index], next[index - 1]];
                    setBusy(true);
                    api(`/api/clients/${clientId}/posts/${postId}/media/reorder`, {
                      method: "POST",
                      body: { ordered_ids: next },
                    })
                      .then((payload) => setAssets(payload.assets || []))
                      .catch((exc) => onError?.(exc.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Up
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={index >= assets.length - 1 || busy}
                  onClick={() => {
                    const ids = assets.map((a) => a.id);
                    const next = [...ids];
                    [next[index + 1], next[index]] = [next[index], next[index + 1]];
                    setBusy(true);
                    api(`/api/clients/${clientId}/posts/${postId}/media/reorder`, {
                      method: "POST",
                      body: { ordered_ids: next },
                    })
                      .then((payload) => setAssets(payload.assets || []))
                      .catch((exc) => onError?.(exc.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Down
                </button>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="hint">No uploads yet. Meta URLs remain available separately if present.</p>
      )}
    </div>
  );
}

function Editor({ column, draft, formats, pillars, hooks = [], unsetLabel, listId }) {
  if (column === "Hook") {
    return (
      <div className="stack" style={{ gap: "0.35rem" }}>
        <select
          value=""
          onChange={(event) => {
            const chosen = event.target.value;
            if (chosen) draft.setHook(chosen);
          }}
        >
          <option value="">Choose hook from legend…</option>
          {hooks.map((item) => (
            <option key={item.id} value={item.name}>
              {item.name}
            </option>
          ))}
        </select>
        <input
          list={listId}
          value={draft.hook}
          onChange={(event) => draft.setHook(event.target.value)}
          placeholder="Or type a hook"
        />
        <datalist id={listId}>
          {hooks.map((item) => (
            <option key={item.id} value={item.name} />
          ))}
        </datalist>
      </div>
    );
  }
  const items = column === "Contentformat" ? formats : pillars;
  const value = column === "Contentformat" ? draft.formatId : draft.pillarId;
  const setValue = column === "Contentformat" ? draft.setFormatId : draft.setPillarId;
  return (
    <select value={value} onChange={(event) => setValue(event.target.value)}>
      <option value="">{unsetLabel}</option>
      {items.map((item) => (
        <option key={item.id} value={String(item.id)} title={item.explanation || ""}>
          {item.name}
        </option>
      ))}
    </select>
  );
}

function ReadCell({ column, value, post }) {
  if (column === "Beoordeling") {
    return <RatingBadge rating={post?.formula_rating} showExplanation />;
  }
  if ((column === "Post-URL" || column === "Media") && typeof value === "string") {
    const parts = value.split(/\s+/).filter(Boolean);
    if (parts.length && parts.every((part) => part.startsWith("https://"))) {
      return parts.map((part) => (
        <a key={part} href={part} target="_blank" rel="noreferrer">
          {part}
        </a>
      ));
    }
  }
  return value || "";
}

function RatingSettingsPanel({ client, summary, onSaved, onError }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const payload = await api(`/api/clients/${client.id}/rating-settings`);
    setSettings(payload);
  }

  useEffect(() => {
    if (!open) return;
    load().catch((exc) => onError(exc.message));
  }, [open, client.id]);

  if (!open) {
    return (
      <section className="card stack">
        <div className="row-actions" style={{ justifyContent: "space-between" }}>
          <div>
            <strong>Rating formula</strong>
            <p className="hint" style={{ margin: "0.25rem 0 0" }}>
              {summary?.active
                ? `Active: ${summary.profile_name || "formula"}${summary.is_provisional ? " (Provisional)" : ""}`
                : "Not active — rating waits for an explicit formula + thresholds."}
            </p>
          </div>
          <button className="secondary" type="button" onClick={() => setOpen(true)}>
            Settings
          </button>
        </div>
      </section>
    );
  }

  if (!settings) return <p className="muted">Loading rating settings…</p>;

  const weights = settings.weights || {};

  async function save(body) {
    setBusy(true);
    onError("");
    try {
      const payload = await api(`/api/clients/${client.id}/rating-settings`, { method: "PUT", body });
      setSettings(payload);
      await onSaved();
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack">
      <div className="row-actions" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Rating formula (per client)</h3>
        <button className="secondary" type="button" onClick={() => setOpen(false)}>
          Collapse
        </button>
      </div>
      <p className="hint">
        Maaike’s final formula has not been delivered yet. Only use a template with “Voorlopig” in the name.
        Missing figures are not counted as 0. Activate only after filling in thresholds.
      </p>
      <p className="hint">{settings.comparison_disclaimer}</p>
      {(settings.activation_blockers || []).length ? (
        <p className="banner">Still needed before activating: {(settings.activation_blockers || []).join(" ")}</p>
      ) : (
        <p className="banner">Thresholds and formula are complete — you can activate.</p>
      )}
      <div className="row-actions wrap">
        {(settings.catalog || []).map((item) => (
          <button
            key={item.key}
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => save({ load_template: item.key, formula_key: item.key })}
          >
            Load {item.name}
          </button>
        ))}
      </div>
      <label>
        Name
        <input
          value={settings.profile_name || ""}
          onChange={(e) => setSettings({ ...settings, profile_name: e.target.value })}
        />
      </label>
      <label>
        Denominator
        <select
          value={settings.denominator_metric || "reach"}
          onChange={(e) => setSettings({ ...settings, denominator_metric: e.target.value })}
        >
          <option value="reach">Reach</option>
          <option value="views">Views</option>
        </select>
      </label>
      <div className="filters-row">
        {["likes", "comments", "shares", "saves"].map((metric) => (
          <label key={metric}>
            Weight {metric}
            <input
              type="number"
              step="0.1"
              value={weights[metric] ?? 0}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  weights: { ...weights, [metric]: e.target.value },
                })
              }
            />
          </label>
        ))}
        <label>
          Good ≥
          <input
            type="number"
            step="0.1"
            value={settings.good_min ?? ""}
            placeholder="enter explicitly"
            onChange={(e) => setSettings({ ...settings, good_min: e.target.value })}
          />
        </label>
        <label>
          Average ≥
          <input
            type="number"
            step="0.1"
            value={settings.average_min ?? ""}
            placeholder="enter explicitly"
            onChange={(e) => setSettings({ ...settings, average_min: e.target.value })}
          />
        </label>
        <label>
          Min. age (hours, optional)
          <input
            type="number"
            step="1"
            value={settings.min_age_hours ?? ""}
            onChange={(e) => setSettings({ ...settings, min_age_hours: e.target.value })}
          />
        </label>
      </div>
      <label>
        Notes
        <textarea
          value={settings.notes || ""}
          onChange={(e) => setSettings({ ...settings, notes: e.target.value })}
        />
      </label>
      <div className="row-actions">
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() =>
            save({
              profile_name: settings.profile_name,
              formula_key: settings.formula_key,
              is_provisional: true,
              weights: settings.weights,
              denominator_metric: settings.denominator_metric,
              good_min: settings.good_min,
              average_min: settings.average_min,
              min_age_hours: settings.min_age_hours,
              notes: settings.notes,
              active: false,
            })
          }
        >
          Save (stays off)
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || !settings.ready_to_activate}
          onClick={() =>
            save({
              profile_name: settings.profile_name,
              formula_key: settings.formula_key,
              is_provisional: true,
              weights: settings.weights,
              denominator_metric: settings.denominator_metric,
              good_min: settings.good_min,
              average_min: settings.average_min,
              min_age_hours: settings.min_age_hours,
              notes: settings.notes,
              active: true,
            })
          }
        >
          Save + activate
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy || !settings.active}
          onClick={() => save({ active: false })}
        >
          Deactivate
        </button>
      </div>
    </section>
  );
}
