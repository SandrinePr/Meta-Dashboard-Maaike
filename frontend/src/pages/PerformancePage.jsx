import { useEffect, useState } from "react";
import { api } from "../api.js";
import ResultCard from "../components/ResultCard.jsx";

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

const METRIC_TITLES_NL = {
  views: "Weergaven",
  likes: "Likes",
  comments: "Reacties",
  saves: "Opgeslagen",
  shares: "Gedeeld",
};

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
      <section className="card stack" style={{ gap: "0.5rem" }}>
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          <div>
            <strong>Resultaten van {client.name}</strong>
            <p className="hint" style={{ margin: "0.2rem 0 0" }}>
              Hier staan uitsluitend de eigen Instagram- en Facebook-cijfers van{" "}
              <strong>{client.name}</strong>. Cijfers en voorbeelden van andere bedrijven bekijk je
              apart bij <strong>Concurrenten</strong>.
            </p>
          </div>
          {onOpenCompetitors ? (
            <button className="secondary" type="button" onClick={onOpenCompetitors}>
              Naar Concurrenten
            </button>
          ) : null}
        </div>
      </section>

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
              Geen berichten van {client.name} gevonden in{" "}
              <strong>
                {payload.selected
                  ? formatMonthNl(payload.selected.year, payload.selected.month)
                  : "deze periode"}
              </strong>
              . Kies een andere maand of haal nieuwe berichten op.
            </p>
          ) : (
            <p className="hint">
              Top 3 eigen berichten van <strong>{client.name}</strong> op basis van{" "}
              <strong>{payload.post_count}</strong>{" "}
              {payload.post_count === 1 ? "bericht" : "berichten"} in de gekozen periode. Klik op{" "}
              <strong>Open in Alle berichten</strong> om de indeling of feedback bij een bericht te
              bekijken.
            </p>
          )}

          {notice ? <p className="banner">{notice}</p> : null}

          {(payload.sections || []).map((section, index) => {
            const metricTitle = METRIC_TITLES_NL[section.metric] || section.label;
            return (
              <section key={section.metric} className="stack">
                {index > 0 ? <hr className="rro-perf-section-divider" /> : null}
                <h3 className="rro-perf-section-header">{metricTitle} · top 3</h3>
                {!section.posts.length ? (
                  <div className="banner">
                    Geen berichten met {metricTitle.toLowerCase()} in deze periode.
                  </div>
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
                            {` · ${metricTitle}: `}
                            <strong>{post.metric_value_label ?? post.metric_value}</strong>
                          </div>
                        }
                        onOpenPost={openPost}
                      />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
