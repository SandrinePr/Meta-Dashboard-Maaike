import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_URL } from "../api.js";
import PostAnalysisPanel from "../components/PostAnalysisPanel.jsx";
import ResultCard from "../components/ResultCard.jsx";

/** Normalize Publicatiedatum cells (ISO or DD-MM-YYYY) to YYYY-MM-DD for filters/sort. */
function toIsoDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
  const dmy = raw.match(/^(\d{1,2})-(\d{1,2})-(\d{4})/);
  if (dmy) {
    return `${dmy[3]}-${String(dmy[2]).padStart(2, "0")}-${String(dmy[1]).padStart(2, "0")}`;
  }
  return raw.slice(0, 10);
}

function dutchUnsetLabel(label) {
  if (!label || label === "not set" || label === "not available") return "Nog niet ingevuld";
  return label;
}

export default function PostsPage({
  client,
  focusPostId,
  focusSeq = 0,
  onClearFocus,
  initialDateFrom = "",
  initialDateTo = "",
  reloadToken = 0,
  missingFilterSignal = 0,
  onOpenConnect,
  onPostsChanged,
  periodHint = "",
  showImportExportButton = true,
}) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [adminError, setAdminError] = useState("");
  const [notice, setNotice] = useState("");
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
  const [expandedPostId, setExpandedPostId] = useState(focusPostId ? Number(focusPostId) : null);

  const reload = useCallback(
    async (guard = () => true) => {
      const targetId = client.id;
      const payload = await api(`/api/clients/${targetId}/posts`);
      if (!guard()) return null;
      if (payload?.client_id != null && Number(payload.client_id) !== Number(targetId)) {
        return null;
      }
      setOverview(payload);
      return payload;
    },
    [client.id],
  );

  useEffect(() => {
    let active = true;
    setOverview(null);
    setNotice("");
    setError("");
    setAdminError("");
    setPreview(null);
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
    reload(() => active).catch((exc) => {
      if (!active) return;
      setError("De berichten van deze klant konden niet worden geladen.");
      setAdminError(exc.message || "");
    });
    return () => {
      active = false;
    };
  }, [client.id, reload]);

  useEffect(() => {
    if (!reloadToken) return undefined;
    let active = true;
    reload(() => active).catch((exc) => {
      if (!active) return;
      setError("Het verversen van de berichtenlijst is niet gelukt.");
      setAdminError(exc.message || "");
    });
    return () => {
      active = false;
    };
  }, [reloadToken, reload]);

  useEffect(() => {
    setFilters((current) => ({
      ...current,
      date_from: initialDateFrom || "",
      date_to: initialDateTo || "",
    }));
  }, [initialDateFrom, initialDateTo]);

  useEffect(() => {
    if (!missingFilterSignal) return;
    setFilters((current) => ({
      ...current,
      missing: "any",
    }));
  }, [missingFilterSignal]);

  useEffect(() => {
    if (!focusPostId || !overview) return;
    setExpandedPostId(Number(focusPostId));
    const row = document.getElementById(`log-post-${focusPostId}`);
    if (row) {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("is-focused");
    }
    onClearFocus?.();
  }, [focusPostId, focusSeq, overview]);

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
        String(post.cells?.Platform || post.platform_label || post.platform || "Overig").trim() ||
        "Overig";
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
      if (
        filters.platform &&
        !String(cells.Platform || "").toLowerCase().includes(filters.platform.toLowerCase())
      ) {
        return false;
      }
      if (
        filters.content_soort &&
        !String(cells.Contentsoort || "").toLowerCase().includes(filters.content_soort.toLowerCase())
      ) {
        return false;
      }
      if (
        filters.format &&
        !String(cells.Contentformat || "").toLowerCase().includes(filters.format.toLowerCase())
      ) {
        return false;
      }
      if (
        filters.pillar &&
        !String(cells.Contentpijler || "").toLowerCase().includes(filters.pillar.toLowerCase())
      ) {
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
      const iso = toIsoDate(cells.Publicatiedatum);
      if (filters.date_from && iso && iso < filters.date_from) return false;
      if (filters.date_to && iso && iso > filters.date_to) return false;
      return true;
    });
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const ca = a.cells || {};
      const cb = b.cells || {};
      const da = toIsoDate(ca.Publicatiedatum);
      const db = toIsoDate(cb.Publicatiedatum);
      if (sortKey === "date_asc") return da.localeCompare(db) || a.post_id - b.post_id;
      if (sortKey === "platform") {
        return String(ca.Platform || "").localeCompare(String(cb.Platform || "")) || db.localeCompare(da);
      }
      if (sortKey === "format") {
        return (
          String(ca.Contentformat || "").localeCompare(String(cb.Contentformat || "")) ||
          db.localeCompare(da)
        );
      }
      return db.localeCompare(da) || b.post_id - a.post_id;
    });
    return sorted;
  }, [overview, filters, sortKey, contentMatchIds]);

  function clearAllFilters() {
    setDraftQuery("");
    setContentMatchIds(null);
    setContentMatchNote("");
    setFilters({
      q: "",
      platform: "",
      content_soort: "",
      format: "",
      pillar: "",
      date_from: "",
      date_to: "",
      missing: "",
    });
  }

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
    setAdminError("");
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
        `Voorbeeld klaar: ${payload.counts?.add || 0} nieuw, ${payload.counts?.link || 0} aan te vullen, ${payload.counts?.conflict || 0} verschil, ${payload.counts?.skip || 0} overslaan.`,
      );
    } catch (exc) {
      setError("Het lezen van het Excel-bestand is niet gelukt.");
      setAdminError(exc.message || "");
    } finally {
      setImporting(false);
    }
  }

  async function runImport(file) {
    setImporting(true);
    setError("");
    setAdminError("");
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
      await onPostsChanged?.();
      setNotice(
        `Excel verwerkt: ${payload.applied?.added || 0} toegevoegd, ${payload.applied?.linked || 0} aangevuld, ${payload.applied?.conflicts || 0} verschillen ongewijzigd gelaten.`,
      );
    } catch (exc) {
      setError("Het inlezen van het Excel-bestand is niet gelukt.");
      setAdminError(exc.message || "");
    } finally {
      setImporting(false);
    }
  }

  if (!overview) {
    return error ? (
      <div className="stack">
        <p className="banner error">{error}</p>
        {adminError ? (
          <details>
            <summary className="hint" style={{ cursor: "pointer" }}>
              Technische foutdetails (alleen voor beheer)
            </summary>
            <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
              {adminError}
            </pre>
          </details>
        ) : null}
      </div>
    ) : (
      <p className="muted">Berichten van {client.name} laden…</p>
    );
  }

  const channelState = overview.channel_status?.state || (overview.fetch_available ? "ready_to_view" : "connect_required");
  const unsetText = dutchUnsetLabel(overview.unset_label);

  return (
    <div className="stack">
      {/* Uitleg bij Alle berichten voor Jet of Mo (punt 18) */}
      <section className="card stack" style={{ gap: "0.65rem" }}>
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "flex-start" }}
        >
          <div className="stack" style={{ gap: "0.3rem", maxWidth: "46rem" }}>
            <h3 style={{ margin: 0 }}>Alle berichten</h3>
            <p className="hint" style={{ margin: 0 }}>
              Hier staan de opgehaalde berichten van <strong>{client.name}</strong>.{" "}
              <strong>Jet of Mo</strong> kan hier per bericht het contentformat, de contentpijler,
              de hook en een Figma-link invullen, beelden toevoegen of een kort inzicht bewaren. Je
              kunt hieronder ook zoeken, filteren of het overzicht downloaden in Excel of CSV.
            </p>
          </div>
          <div className="row-actions wrap">
            <button className="secondary" type="button" onClick={() => setShowAdd(true)}>
              Bericht handmatig toevoegen
            </button>
            {showImportExportButton ? (
              <button
                className={importExportOpen ? "primary" : "secondary"}
                type="button"
                onClick={() => setImportExportOpen((open) => !open)}
              >
                Excel inlezen of downloaden
              </button>
            ) : null}
          </div>
        </div>

        {periodHint ? <p className="hint" style={{ margin: 0 }}>{periodHint}</p> : null}

        <p style={{ margin: 0 }}>
          <strong>Totaal eigen berichten van {client.name}:</strong> {totalPosts}
          {platformAvailability.length ? (
            <>
              {" "}
              · <strong>Per kanaal:</strong>{" "}
              {platformAvailability.map(([label, count]) => `${label}: ${count}`).join(" · ")}
            </>
          ) : null}
        </p>
      </section>

      {showImportExportButton && importExportOpen ? (
        <section className="card stack">
          <div className="search-form-header">
            <h3>Excel inlezen of downloaden</h3>
          </div>
          <p className="hint">
            Lees een bestaand Excel-overzicht in voor {client.name}, of download de huidige selectie
            als Excel- of CSV-bestand.
          </p>
          <div className="row-actions wrap">
            <label className="secondary file-btn">
              Excel-bestand kiezen
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
              Excel downloaden
            </a>
            <a className="secondary" href={exportUrl("csv")}>
              CSV downloaden
            </a>
          </div>
        </section>
      ) : null}

      {preview ? (
        <div className="card stack">
          <p>
            Voorbeeld voor <strong>{preview.file_name}</strong> ({preview.sheet}): {preview.row_count}{" "}
            rijen gecontroleerd.
          </p>
          <p className="hint">
            Twijfelgevallen worden niet overschreven. Opnieuw inlezen maakt geen dubbele berichten aan.
          </p>
          <div className="row-actions">
            <button
              className="primary"
              type="button"
              disabled={importing}
              onClick={() => runImport(null)}
            >
              {importing ? "Bezig met verwerken…" : "Veilige aanvullingen opslaan"}
            </button>
            <button className="secondary" type="button" onClick={() => setPreview(null)}>
              Annuleren
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Rij</th>
                  <th>Actie</th>
                  <th>Kanaal</th>
                  <th>Link</th>
                  <th>Velden</th>
                  <th>Aandachtspunten</th>
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
        </div>
      ) : null}

      {/* Zoeken en filteren alleen tonen zodra er berichten voor deze klant bestaan */}
      {totalPosts > 0 ? (
        <section className="card stack">
          <div
            className="row-actions wrap"
            style={{ justifyContent: "space-between", alignItems: "center" }}
          >
            <h3 style={{ margin: 0 }}>Zoeken &amp; filteren</h3>
            {filtersActive ? (
              <button className="secondary" type="button" onClick={clearAllFilters}>
                Alle filters wissen (toon alle {totalPosts} berichten)
              </button>
            ) : null}
          </div>
          <form
            className="filters-row"
            onSubmit={(event) => {
              event.preventDefault();
              setFilters({ ...filters, q: draftQuery.trim() });
            }}
          >
            <label style={{ flex: "1 1 16rem" }}>
              Zoekwoord
              <input
                value={draftQuery}
                onChange={(e) => setDraftQuery(e.target.value)}
                placeholder="Zoek op berichttekst, hook, inzicht of link…"
              />
            </label>
            <div className="row-actions" style={{ alignItems: "end" }}>
              <button className="primary" type="submit">
                Zoeken
              </button>
              {filters.q || draftQuery ? (
                <button
                  className="secondary"
                  type="button"
                  onClick={() => {
                    setDraftQuery("");
                    setFilters({ ...filters, q: "" });
                  }}
                >
                  Zoekwoord wissen
                </button>
              ) : null}
            </div>
          </form>
          <div className="filters-row">
            <label>
              Kanaal
              <input
                value={filters.platform}
                onChange={(e) => setFilters({ ...filters, platform: e.target.value })}
                placeholder="Instagram, Facebook, LinkedIn…"
              />
            </label>
            <label>
              Contentformat
              <input
                value={filters.format}
                onChange={(e) => setFilters({ ...filters, format: e.target.value })}
                placeholder="bijv. Reel of Carrousel"
              />
            </label>
            <label>
              Contentpijler
              <input
                value={filters.pillar}
                onChange={(e) => setFilters({ ...filters, pillar: e.target.value })}
                placeholder="bijv. Inspiratie of Kennis"
              />
            </label>
            <label>
              Controlestatus
              <select
                value={filters.missing}
                onChange={(e) => setFilters({ ...filters, missing: e.target.value })}
              >
                <option value="">Alle berichten</option>
                <option value="any">Nog na te kijken (format, pijler of hook mist)</option>
                <option value="format">Contentformat ontbreekt</option>
                <option value="pillar">Contentpijler ontbreekt</option>
                <option value="hook">Hook ontbreekt</option>
              </select>
            </label>
            <label>
              Vanaf datum
              <input
                type="date"
                value={filters.date_from}
                onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
              />
            </label>
            <label>
              Tot en met datum
              <input
                type="date"
                value={filters.date_to}
                onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
              />
            </label>
            <label>
              Volgorde
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                <option value="date_desc">Nieuwste eerst</option>
                <option value="date_asc">Oudste eerst</option>
                <option value="platform">Kanaal (A–Z)</option>
                <option value="format">Contentformat (A–Z)</option>
              </select>
            </label>
          </div>
          <details>
            <summary className="hint" style={{ cursor: "pointer" }}>
              Uitgebreid zoeken in reacties, tags en hashtags
            </summary>
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
          </details>
          <p className="hint" style={{ margin: 0 }}>
            {filtersActive ? (
              <>
                <strong> Zichtbaar:</strong> {filteredPosts.length} van {totalPosts} berichten voor{" "}
                {client.name}
              </>
            ) : (
              <>
                Alle <strong>{totalPosts}</strong> berichten van {client.name} staan in beeld
              </>
            )}
            {filters.q ? ` · zoekwoord “${filters.q}”` : ""}
            {contentMatchNote ? ` · ${contentMatchNote}` : ""}.
          </p>
        </section>
      ) : null}

      {error ? (
        <div className="stack">
          <p className="banner error">{error}</p>
          {adminError ? (
            <details>
              <summary className="hint" style={{ cursor: "pointer" }}>
                Technische foutdetails (alleen voor beheer)
              </summary>
              <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                {adminError}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
      {notice ? <p className="banner">{notice}</p> : null}

      {/* Lege staten in helder Nederlands (punt 16, 17 & 18) */}
      {totalPosts === 0 ? (
        <section className="card stack" style={{ gap: "0.6rem" }}>
          {channelState === "connect_required" ? (
            <>
              <strong>Koppel eerst je accounts voor {client.name}</strong>
              <p style={{ margin: 0 }}>
                Er zijn nog geen berichten om te tonen omdat Facebook en Instagram nog niet zijn
                gekoppeld voor {client.name}. Koppel eerst de accounts via de knop bovenaan, of voeg
                alvast handmatig een bericht of Excel-bestand toe.
              </p>
              <div className="row-actions wrap">
                {onOpenConnect ? (
                  <button className="primary" type="button" onClick={onOpenConnect}>
                    Accounts koppelen
                  </button>
                ) : null}
                <button className="secondary" type="button" onClick={() => setShowAdd(true)}>
                  Bericht handmatig toevoegen
                </button>
              </div>
            </>
          ) : (
            <>
              <strong>Haal je eerste berichten op voor {client.name}</strong>
              <p style={{ margin: 0 }}>
                Facebook en Instagram zijn gekoppeld, maar er zijn nog geen berichten opgehaald voor{" "}
                {client.name}. Gebruik de knop <strong>Eerste berichten ophalen</strong> bovenaan dit
                scherm om te beginnen.
              </p>
            </>
          )}
        </section>
      ) : filteredPosts.length > 0 ? (
        <div className="results-list logs-cards">
          {filteredPosts.map((post) => (
            <LogPostCard
              key={post.id}
              clientId={client.id}
              post={post}
              query={filters.q}
              formats={overview.formats}
              pillars={overview.pillars}
              hooks={overview.hooks || []}
              unsetLabel={unsetText}
              focused={Number(focusPostId) === Number(post.id) || Number(expandedPostId) === Number(post.id)}
              onSaved={async () => {
                await reload();
                await onPostsChanged?.();
                setNotice("Wijzigingen bij dit bericht zijn opgeslagen.");
              }}
              onError={(msg) => setError(msg == null ? "" : msg)}
            />
          ))}
        </div>
      ) : (
        <section className="card stack" style={{ gap: "0.6rem" }}>
          <strong>Geen berichten binnen deze filters</strong>
          <p style={{ margin: 0 }}>
            Er staan wel {totalPosts} berichten voor {client.name}, maar geen enkel bericht valt
            binnen de gekozen datum of zoekopdracht.
          </p>
          <div>
            <button className="primary" type="button" onClick={clearAllFilters}>
              Alle filters wissen en alle {totalPosts} berichten tonen
            </button>
          </div>
        </section>
      )}

      {/* Technische en beheeropties alleen open te klappen voor beheer (punt 17) */}
      <details className="card">
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>
          Beheer &amp; technische controle (alleen voor beheer)
        </summary>
        <div className="stack" style={{ marginTop: "0.85rem" }}>
          <RatingSettingsPanel
            client={client}
            summary={overview.rating_settings}
            onSaved={async () => {
              await reload();
              setNotice("Beoordelingsformule bijgewerkt.");
            }}
            onError={setError}
          />
          <ActivityPanel client={client} />
        </div>
      </details>

      {showAdd ? (
        <AddPostModal
          clientId={client.id}
          onClose={() => setShowAdd(false)}
          onCreated={async () => {
            setShowAdd(false);
            await reload();
            await onPostsChanged?.();
            setNotice("Bericht is handmatig toegevoegd.");
          }}
          onError={(msg) => setError(msg == null ? "" : msg)}
        />
      ) : null}
    </div>
  );
}

const MATCH_TYPE_LABELS = {
  comment: "Reacties",
  tag: "Vermeldingen (@)",
  hashtag: "Hashtags (#)",
  caption: "Berichttekst",
};

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
      setError("Vul minimaal 3 tekens in om te zoeken.");
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
      setError("Kies minimaal één kanaal en één onderdeel om in te zoeken.");
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
      onMatch?.(ids, `gevonden via zoeken op “${q}” (${ids.length} berichten)`);
    } catch {
      setError("Het zoeken in reacties en hashtags is niet gelukt.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="hint" style={{ margin: 0 }}>
        Zoek gericht in Instagram- en Facebook-reacties, tags (@), hashtags (#) en berichtteksten.
      </p>
      <form className="filters-row" onSubmit={runSearch}>
        <label style={{ flex: "1 1 16rem" }}>
          Zoek in reacties, tags of hashtags
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Minimaal 3 tekens…"
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
              {MATCH_TYPE_LABELS[key] || key}
            </button>
          ))}
        </div>
        <div className="row-actions" style={{ alignItems: "end" }}>
          <button className="secondary" type="submit" disabled={busy}>
            {busy ? "Zoeken…" : "Lijst filteren"}
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
              Filter wissen
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
    let active = true;
    const params = new URLSearchParams();
    if (filters.activity_type) params.set("activity_type", filters.activity_type);
    if (filters.status) params.set("status", filters.status);
    if (filters.errors_only) params.set("errors_only", "true");
    const q = params.toString();
    api(`/api/clients/${client.id}/activity${q ? `?${q}` : ""}`)
      .then((res) => {
        if (active) setData(res);
      })
      .catch((exc) => {
        if (active) setError(exc.message || "");
      });
    return () => {
      active = false;
    };
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
    <section className="stack" style={{ gap: "0.65rem" }}>
      <h4 style={{ margin: 0 }}>Technisch activiteitenlogboek ({client.name})</h4>
      <div className="filters-row">
        <label>
          Onderdeel
          <select
            value={filters.activity_type}
            onChange={(e) => setFilters({ ...filters, activity_type: e.target.value })}
          >
            <option value="">Alle onderdelen</option>
            {(data?.activity_types || ["meta_sync", "excel_import", "ai", "report", "data_import"]).map(
              (t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">Alle statussen</option>
            <option value="ok">Gelukt (ok)</option>
            <option value="pending">Bezig (pending)</option>
            <option value="error">Fout (error)</option>
            <option value="info">Melding (info)</option>
          </select>
        </label>
        <label className="row-actions">
          <input
            type="checkbox"
            checked={filters.errors_only}
            onChange={(e) => setFilters({ ...filters, errors_only: e.target.checked })}
          />
          Alleen foutmeldingen
        </label>
        <a className="secondary" href={exportHref}>
          Logboek downloaden (CSV)
        </a>
      </div>
      {error ? <p className="banner error">{error}</p> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Datum en tijd</th>
              <th>Klant</th>
              <th>Onderdeel</th>
              <th>Stand</th>
              <th>Technische details</th>
            </tr>
          </thead>
          <tbody>
            {(data?.events || []).map((ev) => (
              <ActivityEventRows key={ev.id} ev={ev} />
            ))}
          </tbody>
        </table>
      </div>
      {!data?.events?.length ? (
        <p className="hint">Nog geen technische logregels gevonden voor deze selectie.</p>
      ) : null}
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
                ? "Laatste poging gelukt. Eerdere pogingen staan onder Pogingen bekijken."
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
                poging · #{attempt.report_id}
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
        <h3>Bericht handmatig toevoegen</h3>
        <p className="hint">
          Handig voor bijvoorbeeld een LinkedIn-bericht of los bericht zonder directe koppeling.
        </p>
        <label>
          Kanaal
          <input value={platformLabel} onChange={(e) => setPlatformLabel(e.target.value)} />
        </label>
        <label>
          Link naar het bericht
          <input
            value={permalink}
            onChange={(e) => setPermalink(e.target.value)}
            placeholder="https://…"
          />
        </label>
        <label>
          Publicatiedatum
          <input type="date" value={publishedAt} onChange={(e) => setPublishedAt(e.target.value)} />
        </label>
        <label>
          Hook (optioneel)
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
                    platform_key: platformLabel
                      .toLowerCase()
                      .replace(/\s+/g, "_")
                      .replace(/-+/g, "_"),
                    permalink,
                    published_at: publishedAt || undefined,
                    hook,
                  },
                });
                await onCreated();
              } catch (exc) {
                onError(exc.message || "Het bericht kon niet worden opgeslagen.");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Opslaan…" : "Bericht opslaan"}
          </button>
          <button className="secondary" type="button" onClick={onClose}>
            Annuleren
          </button>
        </div>
      </div>
    </div>
  );
}

function useDraft(post) {
  const [formatId, setFormatId] = useState(post.format_id == null ? "" : String(post.format_id));
  const [pillarId, setPillarId] = useState(post.pillar_id == null ? "" : String(post.pillar_id));
  const [hook, setHook] = useState(post.cells?.Hook || post.hook || "");
  const [figmaUrl, setFigmaUrl] = useState(post.figma_url || post.cells?.Figma || "");
  useEffect(() => {
    setFormatId(post.format_id == null ? "" : String(post.format_id));
    setPillarId(post.pillar_id == null ? "" : String(post.pillar_id));
    setHook(post.cells?.Hook || post.hook || "");
    setFigmaUrl(post.figma_url || post.cells?.Figma || "");
  }, [
    post.id,
    post.format_id,
    post.pillar_id,
    post.hook,
    post.figma_url,
    post.cells?.Hook,
    post.cells?.Figma,
  ]);
  return { formatId, setFormatId, pillarId, setPillarId, hook, setHook, figmaUrl, setFigmaUrl };
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
        figma_url: draft.figmaUrl ?? "",
      },
    });
    await onSaved();
  } catch {
    onError("Het opslaan van de indeling is niet gelukt.");
  }
}

function LogPostCard({
  clientId,
  post,
  query = "",
  formats,
  pillars,
  hooks,
  unsetLabel,
  focused = false,
  onSaved,
  onError,
}) {
  const draft = useDraft(post);
  const [open, setOpen] = useState(Boolean(focused));
  const feedback = post.latest_feedback;

  useEffect(() => {
    if (focused) setOpen(true);
  }, [focused]);

  const missingLabels = [];
  if (post.format_id == null) missingLabels.push("Contentformat");
  if (post.pillar_id == null) missingLabels.push("Contentpijler");
  if (!String(post.hook || post.cells?.Hook || "").trim()) missingLabels.push("Hook");

  const formatDisplay =
    post.cells?.Contentformat && post.cells.Contentformat !== "not set"
      ? post.cells.Contentformat
      : unsetLabel;
  const pillarDisplay =
    post.cells?.Contentpijler && post.cells.Contentpijler !== "not set"
      ? post.cells.Contentpijler
      : unsetLabel;

  const cardPost = {
    ...post,
    dom_id: `log-post-${post.id}`,
    caption: post.caption || post.cells?.Tekst || "",
    account: post.account || post.cells?.Account || "",
    published_label: post.published_label || post.cells?.Publicatiedatum || "",
    platform_label: post.platform_label || post.cells?.Platform || post.platform,
    content_kind_label: post.content_kind_label || post.cells?.Contentsoort || "",
    log_rating: feedback?.rating_text || post.log_rating || "",
    log_insight: feedback?.insight_text || post.log_insight || "",
    log_action: feedback?.action_text || post.log_action || "",
  };

  return (
    <ResultCard
      post={cardPost}
      query={query}
      focused={focused || open}
      detailsOpen={open}
      detailsLabel="Bericht nakijken"
      detailsOpenLabel="Sluiten"
      onOpenDetails={() => setOpen((value) => !value)}
    >
      <div className="logs-card-meta">
        <span>
          <strong>Format:</strong> {formatDisplay}
        </span>
        <span>
          <strong>Pijler:</strong> {pillarDisplay}
        </span>
        <span>
          <strong>Hook:</strong> {post.hook || post.cells?.Hook || unsetLabel}
        </span>
        {missingLabels.length > 0 ? (
          <span
            className="badge"
            style={{
              background: "rgba(245, 158, 11, 0.22)",
              border: "1px solid rgba(251, 191, 36, 0.45)",
              color: "#fde68a",
            }}
          >
            Nog na te kijken: {missingLabels.join(", ")}
          </span>
        ) : (
          <span className="badge badge-active">Gecontroleerd</span>
        )}
      </div>
      {open ? (
        <div className="logs-card-editor stack">
          <div className="logs-edit-grid">
            <label>
              Contentformat
              <Editor
                column="Contentformat"
                draft={draft}
                formats={formats}
                pillars={pillars}
                hooks={hooks}
                unsetLabel={unsetLabel}
                listId={`hook-list-${post.id}`}
              />
            </label>
            <label>
              Contentpijler
              <Editor
                column="Contentpijler"
                draft={draft}
                formats={formats}
                pillars={pillars}
                hooks={hooks}
                unsetLabel={unsetLabel}
                listId={`hook-list-${post.id}`}
              />
            </label>
            <label>
              Hook
              <Editor
                column="Hook"
                draft={draft}
                formats={formats}
                pillars={pillars}
                hooks={hooks}
                unsetLabel={unsetLabel}
                listId={`hook-list-${post.id}`}
              />
            </label>
            <label>
              Figma-link (optioneel)
              <input
                value={draft.figmaUrl}
                onChange={(e) => draft.setFigmaUrl(e.target.value)}
                placeholder="https://www.figma.com/…"
              />
            </label>
          </div>
          <div className="row-actions wrap">
            <button
              className="primary"
              type="button"
              onClick={() => saveDraft(clientId, post, draft, onSaved, onError)}
            >
              Indeling opslaan
            </button>
          </div>
          <MediaUploadPanel
            clientId={clientId}
            postId={post.id}
            onError={onError}
            onSaved={onSaved}
          />
          <PostAnalysisPanel
            clientId={clientId}
            postId={post.id}
            onError={onError}
            onSaved={onSaved}
          />
        </div>
      ) : null}
    </ResultCard>
  );
}

function MediaUploadPanel({ clientId, postId, onError, onSaved }) {
  const [assets, setAssets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  function reload() {
    return api(`/api/clients/${clientId}/posts/${postId}/media`)
      .then((payload) => setAssets(payload.assets || []))
      .catch(() => {});
  }

  useEffect(() => {
    reload();
  }, [clientId, postId]);

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="hint" style={{ margin: 0 }}>
        Extra beeld of video bij dit bericht toevoegen (bijvoorbeeld voor een carrousel).
      </p>
      <div className="row-actions wrap">
        <label className="secondary file-btn">
          Afbeelding of video kiezen
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
              api(`/api/clients/${clientId}/posts/${postId}/media`, {
                method: "POST",
                body,
                raw: true,
              })
                .then(async (payload) => {
                  setAssets(payload.assets || []);
                  setNotice(`${(payload.saved || []).length} bestand(en) toegevoegd.`);
                  await onSaved?.();
                })
                .catch(() => onError?.("Het uploaden van het bestand is niet gelukt."))
                .finally(() => {
                  setBusy(false);
                  event.target.value = "";
                });
            }}
          />
        </label>
      </div>
      {busy ? <p className="muted">Bezig met uploaden…</p> : null}
      {notice ? <p className="hint">{notice}</p> : null}
      {assets.length ? (
        <ol className="plain-list">
          {assets.map((asset, index) => (
            <li key={asset.id}>
              {asset.position}. {asset.original_name}{" "}
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
                      .catch(() => onError?.("Volgorde aanpassen is niet gelukt."))
                      .finally(() => setBusy(false));
                  }}
                >
                  Omhoog
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
                      .catch(() => onError?.("Volgorde aanpassen is niet gelukt."))
                      .finally(() => setBusy(false));
                  }}
                >
                  Omlaag
                </button>
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function Editor({ column, draft, formats, pillars, hooks = [], unsetLabel, listId }) {
  if (column === "Hook") {
    return (
      <div className="stack" style={{ gap: "0.35rem" }}>
        {hooks.length ? (
          <select
            value=""
            onChange={(event) => {
              const chosen = event.target.value;
              if (chosen) draft.setHook(chosen);
            }}
          >
            <option value="">Kies een hook uit de legenda…</option>
            {hooks.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        ) : null}
        <input
          list={listId}
          value={draft.hook}
          onChange={(event) => draft.setHook(event.target.value)}
          placeholder="Typ de openingszin of hook"
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
      <div className="row-actions" style={{ justifyContent: "space-between" }}>
        <div>
          <strong>Automatische beoordelingsformule</strong>
          <p className="hint" style={{ margin: "0.2rem 0 0" }}>
            {summary?.active
              ? `Actief: ${summary.profile_name || "formule"}${summary.is_provisional ? " (voorlopig)" : ""}`
              : "Staat uit — wordt pas actief nadat beheer een formule en drempelwaarden instelt."}
          </p>
        </div>
        <button className="secondary" type="button" onClick={() => setOpen(true)}>
          Formule beheren
        </button>
      </div>
    );
  }

  if (!settings) return <p className="muted">Formule-instellingen laden…</p>;

  const weights = settings.weights || {};

  async function save(body) {
    setBusy(true);
    onError("");
    try {
      const payload = await api(`/api/clients/${client.id}/rating-settings`, {
        method: "PUT",
        body,
      });
      setSettings(payload);
      await onSaved();
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="stack">
      <div className="row-actions" style={{ justifyContent: "space-between" }}>
        <h4 style={{ margin: 0 }}>Beoordelingsformule per klant</h4>
        <button className="secondary" type="button" onClick={() => setOpen(false)}>
          Inklappen
        </button>
      </div>
      <p className="hint">{settings.comparison_disclaimer}</p>
      {(settings.activation_blockers || []).length ? (
        <p className="banner">
          Nog nodig vóór activeren: {(settings.activation_blockers || []).join(" ")}
        </p>
      ) : (
        <p className="banner">Drempelwaarden en formule zijn compleet en kunnen geactiveerd worden.</p>
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
            Sjabloon laden: {item.name}
          </button>
        ))}
      </div>
      <label>
        Naam formule
        <input
          value={settings.profile_name || ""}
          onChange={(e) => setSettings({ ...settings, profile_name: e.target.value })}
        />
      </label>
      <label>
        Delen door
        <select
          value={settings.denominator_metric || "reach"}
          onChange={(e) => setSettings({ ...settings, denominator_metric: e.target.value })}
        >
          <option value="reach">Bereik</option>
          <option value="views">Weergaven</option>
        </select>
      </label>
      <div className="filters-row">
        {[
          ["likes", "Weging likes"],
          ["comments", "Weging reacties"],
          ["shares", "Weging gedeeld"],
          ["saves", "Weging opgeslagen"],
        ].map(([metric, label]) => (
          <label key={metric}>
            {label}
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
          Goed vanaf (≥)
          <input
            type="number"
            step="0.1"
            value={settings.good_min ?? ""}
            onChange={(e) => setSettings({ ...settings, good_min: e.target.value })}
          />
        </label>
        <label>
          Gemiddeld vanaf (≥)
          <input
            type="number"
            step="0.1"
            value={settings.average_min ?? ""}
            onChange={(e) => setSettings({ ...settings, average_min: e.target.value })}
          />
        </label>
      </div>
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
          Opslaan (blijft uit)
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
          Opslaan &amp; aanzetten
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy || !settings.active}
          onClick={() => save({ active: false })}
        >
          Uitzetten
        </button>
      </div>
    </section>
  );
}
