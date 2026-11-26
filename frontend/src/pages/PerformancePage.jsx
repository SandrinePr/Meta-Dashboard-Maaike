import { useEffect, useState } from "react";
import { api } from "../api.js";
import { BarChart } from "../components/SimpleCharts.jsx";
import { formatCount, monthBounds, numericMetric, postInteractions, postIso, postKind, postPlatform } from "../postMetrics.js";

const DUTCH_MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function formatMonthNl(year, month) {
  if (!year || !month) return "";
  const m = DUTCH_MONTHS[Number(month) - 1] || String(month);
  return `${m} ${year}`;
}

export default function PerformancePage({
  client,
  onOpenLogs,
  onOpenFeed,
  onOpenPost,
  onOpenCompetitors,
  onOpenConnect,
  onSynced,
  onOpenFiltered,
  selection: controlledSelection,
  onSelectionChange,
}) {
  const [instagram, setInstagram] = useState(true);
  const [facebook, setFacebook] = useState(true);
  const [monthsSpan, setMonthsSpan] = useState(1);
  const [internalSelection, setInternalSelection] = useState("");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [adminError, setAdminError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [allPosts, setAllPosts] = useState([]);

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
  const platformsKey = platforms.join(",");

  useEffect(() => {
    setPayload(null);
    setError("");
    setAdminError("");
    setNotice("");
    if (controlledSelection === undefined) setInternalSelection("");
  }, [client.id]);

  useEffect(() => {
    let cancelled = false;
    const targetClientId = client.id;
    setError("");
    setAdminError("");
    setPayload(null);

    if (!platforms.length) {
      setPayload({
        client_id: targetClientId,
        months: [],
        sections: [],
        empty_message: "Kies minimaal één kanaal (Instagram of Facebook) om resultaten te bekijken.",
        post_count: 0,
      });
      return undefined;
    }

    const params = new URLSearchParams();
    params.set("platforms", platformsKey);
    params.set("months_span", String(monthsSpan));
    if (selection) {
      params.set("year", selection.split("-")[0]);
      params.set("month", selection.split("-")[1]);
    }

    api(`/api/clients/${targetClientId}/performance?${params}`)
      .then((data) => {
        if (cancelled) return;
        if (data?.client_id != null && Number(data.client_id) !== Number(targetClientId)) {
          return;
        }
        setPayload(data);
        if (!selection && data.selected) {
          const next = `${data.selected.year}-${String(data.selected.month).padStart(2, "0")}`;
          setSelection(next);
        }
      })
      .catch((exc) => {
        if (cancelled) return;
        setError("De resultaten konden niet worden geladen.");
        setAdminError(exc.message || "");
      });

    return () => {
      cancelled = true;
    };
  }, [client.id, selection, platformsKey, monthsSpan]);

  useEffect(() => {
    let cancelled = false;
    api(`/api/clients/${client.id}/posts`)
      .then((data) => {
        if (!cancelled) setAllPosts(data?.posts || []);
      })
      .catch(() => {
        if (!cancelled) setAllPosts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [client.id, payload]);

  async function refreshFigures() {
    const targetClientId = client.id;
    setRefreshing(true);
    setError("");
    setAdminError("");
    setNotice("");
    try {
      await api(`/api/clients/${targetClientId}/posts/fetch`, { method: "POST", body: {} });
      setNotice("Cijfers zijn bijgewerkt vanuit Facebook en Instagram.");
      await onSynced?.();
      const params = new URLSearchParams({
        platforms: platformsKey,
        months_span: String(monthsSpan),
      });
      if (selection) {
        params.set("year", selection.split("-")[0]);
        params.set("month", selection.split("-")[1]);
      }
      const nextPayload = await api(`/api/clients/${targetClientId}/performance?${params}`);
      if (nextPayload?.client_id == null || Number(nextPayload.client_id) === Number(targetClientId)) {
        setPayload(nextPayload);
      }
    } catch (exc) {
      setError("Het bijwerken van de cijfers is nu niet gelukt.");
      setAdminError(exc.message || "");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="stack">
      {error ? (
        <div className="stack">
          <p className="banner error">{error}</p>
          {adminError ? (
            <details>
              <summary className="hint" style={{ cursor: "pointer" }}>
                Technische foutdetails              </summary>
              <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                {adminError}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}

      {!payload && !error ? <p className="muted">Resultaten van {client.name} laden…</p> : null}

      {payload && payload.empty_message && !payload.months?.length ? (
        <div className="card stack" style={{ gap: "0.6rem" }}>
          <strong>Nog geen resultaten om te tonen voor {client.name}</strong>
          <p style={{ margin: 0 }}>
            {!platforms.length
              ? payload.empty_message
              : client.connected
                ? `Er zijn nog geen Instagram- of Facebook-berichten opgehaald voor ${client.name}. Gebruik de knop bovenaan om eerst berichten op te halen.`
                : `Facebook en Instagram zijn nog niet gekoppeld voor ${client.name}, en er staan nog geen berichten klaar.`}
          </p>
          {!client.connected && onOpenConnect ? (
            <div className="row-actions">
              <button className="primary" type="button" onClick={onOpenConnect}>
                Accounts koppelen
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {payload && payload.months?.length ? (
        <>
          <div className="filters">
            <label>
              Eindmaand
              <select value={selection} onChange={(event) => setSelection(event.target.value)}>
                {(payload.months || []).map((item) => {
                  const nlLabel = formatMonthNl(item.year, item.month) || item.label;
                  return (
                    <option
                      key={`${item.year}-${item.month}`}
                      value={`${item.year}-${String(item.month).padStart(2, "0")}`}
                    >
                      {item.count > 0
                        ? `${nlLabel} (${item.count} ${item.count === 1 ? "bericht" : "berichten"})`
                        : `${nlLabel} (geen berichten)`}
                    </option>
                  );
                })}
              </select>
            </label>
            <label>
              Periode
              <select
                value={String(monthsSpan)}
                onChange={(e) => setMonthsSpan(Number(e.target.value))}
              >
                {(payload.span_options || [1, 2, 3, 4, 5, 6]).map((n) => (
                  <option key={n} value={n}>
                    {n === 1 ? "1 maand" : `${n} maanden`}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <span className="sidebar-title">Kanalen</span>
              <div className="filter-chips">
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
              </div>
            </div>
            <div className="row-actions" style={{ alignItems: "end" }}>
              <button
                className="secondary"
                type="button"
                disabled={!payload.refresh_available || refreshing}
                onClick={refreshFigures}
              >
                {refreshing ? "Cijfers bijwerken…" : "Cijfers vernieuwen"}
              </button>
            </div>
          </div>

          {payload.post_count === 0 ? (
            <p className="banner">
              Geen posts in{" "}
              <strong>
                {payload.selected
                  ? formatMonthNl(payload.selected.year, payload.selected.month)
                  : "deze periode"}
              </strong>
              . Kies een andere maand.
            </p>
          ) : (
            <p className="hint">{payload.post_count} posts in deze periode.</p>
          )}

          {notice ? <p className="banner">{notice}</p> : null}

          {(payload.sections || []).length || allPosts.length ? (
            <ResultsCharts
              posts={allPosts}
              selection={selection || (payload.selected ? `${payload.selected.year}-${String(payload.selected.month).padStart(2, "0")}` : "")}
              monthsSpan={monthsSpan}
              instagram={instagram}
              facebook={facebook}
              onOpenPost={openPost}
              onOpenFiltered={onOpenFiltered}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function spanBounds(yyyyMm, span) {
  const end = monthBounds(yyyyMm);
  if (!end.from || span <= 1) return end;
  const [y, m] = yyyyMm.split("-").map(Number);
  const start = new Date(y, m - span, 1);
  const from = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-01`;
  return { from, to: end.to };
}

function averageOf(rows) {
  const values = rows.map(postInteractions).filter((value) => value != null);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function channelAllowed(label, instagram, facebook) {
  const name = label.toLowerCase();
  if (name.includes("instagram")) return instagram;
  if (name.includes("facebook")) return facebook;
  return true;
}

function ResultsCharts({ posts, selection, monthsSpan, instagram, facebook, onOpenPost, onOpenFiltered }) {
  const bounds = spanBounds(selection, monthsSpan);
  const inPeriod = (posts || []).filter((post) => {
    const iso = postIso(post);
    const label = postPlatform(post);
    if (!iso || !bounds.from || iso < bounds.from || iso > bounds.to) return false;
    return channelAllowed(label, instagram, facebook);
  });
  const channels = [...new Set(inPeriod.map(postPlatform).filter(Boolean))];
  const kinds = [...new Set(inPeriod.map(postKind).filter(Boolean))];
  const best = [...inPeriod]
    .filter((post) => postInteractions(post) != null)
    .sort((a, b) => postInteractions(b) - postInteractions(a))
    .slice(0, 5);

  function openChannel(row) {
    onOpenFiltered?.({ platform: row.label, from: bounds.from, to: bounds.to, q: "" });
  }

  function openKind(row) {
    onOpenFiltered?.({ platform: "", contentSoort: row.label, from: bounds.from, to: bounds.to, q: "" });
  }

  return (
    <div className="stack">
      <div className="chart-grid">
        <BarChart
          title="Kanalen"
          hint="Gemiddelde interacties per post. Klik een kanaal voor die posts."
          rows={channels.map((label) => ({
            label,
            value: averageOf(inPeriod.filter((post) => postPlatform(post) === label)),
          }))}
          onPick={openChannel}
        />
        <BarChart
          title="Soorten posts"
          hint="Gemiddelde interacties per post."
          rows={kinds.map((label) => ({
            label,
            value: averageOf(inPeriod.filter((post) => postKind(post) === label)),
          }))}
          onPick={openKind}
        />
      </div>
      <section className="card stack">
        <h3>Best presterende posts</h3>
        <p className="hint">Gesorteerd op interacties in deze periode.</p>
        {best.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Post</th>
                  <th>Kanaal</th>
                  <th>Interacties</th>
                  <th>Bereik</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {best.map((post) => (
                  <tr key={post.id}>
                    <td className="cell-clip">{post.caption || post.cells?.Tekst || post.permalink || "—"}</td>
                    <td>{postPlatform(post) || "–"}</td>
                    <td>{formatCount(postInteractions(post))}</td>
                    <td>{formatCount(numericMetric(post, "reach"))}</td>
                    <td>
                      <button className="secondary" type="button" onClick={() => onOpenPost?.(post.id)}>
                        Bekijk post
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="hint">Geen posts met interacties in deze periode.</p>
        )}
      </section>
    </div>
  );
}
