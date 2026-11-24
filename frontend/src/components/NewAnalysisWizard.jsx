import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const MONTHS_NL = [
  [1, "januari"],
  [2, "februari"],
  [3, "maart"],
  [4, "april"],
  [5, "mei"],
  [6, "juni"],
  [7, "juli"],
  [8, "augustus"],
  [9, "september"],
  [10, "oktober"],
  [11, "november"],
  [12, "december"],
];

const TREND_CHANNELS = [
  "Instagram",
  "Facebook",
  "LinkedIn",
  "TikTok",
  "YouTube & overige kanalen",
];

function monthNameNl(month) {
  const found = MONTHS_NL.find(([m]) => m === Number(month));
  return found ? found[1] : String(month);
}

function defaultReportMonth() {
  const now = new Date();
  return {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  };
}

function sourcePillClass(src) {
  if (src.ready || src.status === "ready") return "pill ok";
  if (src.required) return "pill err";
  return "pill warn";
}

export default function NewAnalysisWizard({
  client,
  initialMode = "client",
  initialYear,
  initialMonth,
  onCreated,
  onClose,
  isCollapsible = false,
  onOpenStrategy,
  onOpenFigmaPlanning,
  onOpenSocialPosts,
  onOpenSettings,
}) {
  const def = defaultReportMonth();
  const [mode, setMode] = useState(initialMode || "client");
  const [year, setYear] = useState(initialYear || def.year);
  const [month, setMonth] = useState(initialMonth || def.month);
  const [title, setTitle] = useState("");
  const [titleEdited, setTitleEdited] = useState(false);
  const [userNotes, setUserNotes] = useState("");
  const [inspect, setInspect] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (initialMode) setMode(initialMode);
  }, [initialMode]);

  useEffect(() => {
    if (initialYear) setYear(initialYear);
    if (initialMonth) setMonth(initialMonth);
  }, [initialYear, initialMonth]);

  const defaultTitle =
    mode === "trend"
      ? `Algemeen trendrapport – ${monthNameNl(month)} ${year}`
      : `${client.name} – Maandrapport ${monthNameNl(month)} ${year}`;

  useEffect(() => {
    if (!titleEdited) {
      setTitle(defaultTitle);
    }
  }, [defaultTitle, titleEdited]);

  const loadInspect = useCallback(async () => {
    setInspectLoading(true);
    setError("");
    try {
      const qs = new URLSearchParams({
        period_year: String(year),
        period_month: String(month),
      });
      const res = await api(`/api/clients/${client.id}/reports/client/inspect?${qs.toString()}`);
      setInspect(res);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setInspectLoading(false);
    }
  }, [client.id, year, month]);

  useEffect(() => {
    loadInspect();
  }, [loadInspect]);

  function switchMode(nextMode) {
    setMode(nextMode);
    setTitleEdited(false);
    setError("");
    setNotice("");
  }

  function handleSourceAction(src) {
    if (src.cta_target === "strategy") {
      onOpenStrategy?.();
      return;
    }
    if (src.cta_target === "figma_planning") {
      onOpenFigmaPlanning?.();
      return;
    }
    if (src.cta_target === "social_posts") {
      onOpenSocialPosts?.();
      return;
    }
    if (src.cta_target === "trend_report") {
      switchMode("trend");
      setNotice(
        `Maak eerst het Algemeen trendrapport voor ${monthNameNl(month)} ${year}. Daarna koppelt HAMSTER het automatisch aan het klantrapport.`
      );
    }
  }

  async function runCreateReport({ simulateWithoutPaidAi }) {
    setBusy(simulateWithoutPaidAi ? "simulate" : "ai");
    setError("");
    setNotice("");
    try {
      let reportId = null;

      if (mode === "trend") {
        if (simulateWithoutPaidAi) {
          const sim = await api("/api/report-planning/monthly-trend/simulate", {
            method: "POST",
            body: {
              year: Number(year),
              month: Number(month),
              simulate_without_paid_ai: true,
            },
          });
          reportId = sim.report_id;
        } else {
          const prep = await api(`/api/clients/${client.id}/reports/trend/prepare`, {
            method: "POST",
            body: {
              run_year: Number(year),
              run_month: Number(month),
              research_mode: "internet",
              title: title.trim() || defaultTitle,
            },
          });
          reportId = prep?.report?.id || prep?.report_id;
          await api(`/api/clients/${client.id}/reports/${reportId}/execute`, {
            method: "POST",
            body: { dry_run_paid: false },
          });
        }
      } else {
        const prep = await api(`/api/clients/${client.id}/reports/client/prepare`, {
          method: "POST",
          body: {
            period_year: Number(year),
            period_month: Number(month),
            title: title.trim() || defaultTitle,
            maaike_planning_notes: userNotes || null,
          },
        });
        reportId = prep?.report?.id || prep?.report_id;
        if (simulateWithoutPaidAi) {
          await api(`/api/clients/${client.id}/reports/${reportId}/mock`, {
            method: "POST",
            body: { scenario: "success_with_sources" },
          });
        } else {
          await api(`/api/clients/${client.id}/reports/${reportId}/execute`, {
            method: "POST",
            body: { dry_run_paid: false },
          });
        }
      }

      if (onCreated) {
        await onCreated(reportId, { mode, year, month });
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  const win = inspect?.period || inspect?.window || {};
  const fmtWin = inspect?.format_pattern_window || {};
  const sourcesOverview = inspect?.sources_overview || {};
  const sources = sourcesOverview.sources || [];
  const missingRequired = sources.filter((s) => s.required && !s.ready);
  const missingOptional = sources.filter((s) => !s.required && !s.ready);
  const canStartClient = Boolean(inspect?.can_start_analysis) && missingRequired.length === 0;
  const aiReady = Boolean(inspect?.ai_status?.configured);
  const existingTrend = inspect?.month_trend_status || {};
  const usableTrend = existingTrend?.usable_report || existingTrend?.usable || null;

  return (
    <section className="card stack report-builder-card">
      <div className="search-form-header">
        <div>
          <h3 style={{ margin: 0 }}>Nieuw rapport voorbereiden</h3>
          <p className="hint" style={{ margin: "0.25rem 0 0" }}>
            Kies welk rapport je wilt maken en voor welke maand. HAMSTER vult de perioden en
            beschikbare bronnen automatisch in.
          </p>
        </div>
        {isCollapsible && onClose ? (
          <button className="secondary" type="button" onClick={onClose} disabled={Boolean(busy)}>
            Sluiten
          </button>
        ) : null}
      </div>

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      {/* 1. Keuze welk rapport + maand */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "0.75rem",
        }}
      >
        <button
          type="button"
          onClick={() => switchMode("client")}
          disabled={Boolean(busy)}
          style={{
            textAlign: "left",
            padding: "0.9rem 1rem",
            borderRadius: "10px",
            border: mode === "client" ? "2px solid #b87844" : "1px solid rgba(242, 240, 236, 0.16)",
            background: mode === "client" ? "#2d3b4d" : "#1a2533",
            color: "#f2f0ec",
            cursor: "pointer",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Klantrapport ({client.name})</strong>
            {mode === "client" ? <span className="pill ok">Gekozen</span> : null}
          </div>
          <p className="hint" style={{ margin: "0.35rem 0 0" }}>
            Maandanalyse van eigen berichten, formats, strategie en aanbevelingen — inclusief het
            algemene trendrapport van dezelfde maand.
          </p>
        </button>

        <button
          type="button"
          onClick={() => switchMode("trend")}
          disabled={Boolean(busy)}
          style={{
            textAlign: "left",
            padding: "0.9rem 1rem",
            borderRadius: "10px",
            border: mode === "trend" ? "2px solid #b87844" : "1px solid rgba(242, 240, 236, 0.16)",
            background: mode === "trend" ? "#2d3b4d" : "#1a2533",
            color: "#f2f0ec",
            cursor: "pointer",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Algemeen trendrapport</strong>
            {mode === "trend" ? <span className="pill ok">Gekozen</span> : null}
          </div>
          <p className="hint" style={{ margin: "0.35rem 0 0" }}>
            Zelfstandig rapport met trends per socialmediakanaal voor alle klanten. Wordt op de 1e
            van iedere maand automatisch aangemaakt.
          </p>
        </button>
      </div>

      <div className="row-actions wrap" style={{ alignItems: "end" }}>
        <label>
          Rapportmaand
          <select
            value={String(month)}
            disabled={Boolean(busy)}
            onChange={(e) => {
              setMonth(Number(e.target.value));
              setTitleEdited(false);
            }}
          >
            {MONTHS_NL.map(([m, label]) => (
              <option key={m} value={m}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Jaar
          <input
            type="number"
            min={2024}
            max={2035}
            value={year}
            disabled={Boolean(busy)}
            onChange={(e) => {
              setYear(Number(e.target.value) || def.year);
              setTitleEdited(false);
            }}
            style={{ width: "6.5rem" }}
          />
        </label>

        <label style={{ flex: "1 1 260px" }}>
          Rapportnaam
          <input
            type="text"
            value={title}
            disabled={Boolean(busy)}
            onChange={(e) => {
              setTitle(e.target.value);
              setTitleEdited(true);
            }}
          />
        </label>
      </div>

      {inspectLoading && !inspect ? <p className="muted">Gegevens voor deze maand ophalen…</p> : null}

      {/* 2A. Klantrapport: automatische perioden + bronnenoverzicht + wat je zelf doet */}
      {mode === "client" && inspect ? (
        <div className="stack">
          <div
            style={{
              background: "#1a2533",
              border: "1px solid rgba(242, 240, 236, 0.14)",
              borderRadius: "10px",
              padding: "0.9rem 1rem",
            }}
          >
            <h4 style={{ margin: "0 0 0.5rem" }}>
              Automatisch ingestelde perioden voor {monthNameNl(month)} {year}
            </h4>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "0.75rem",
              }}
            >
              <div>
                <span className="hint" style={{ display: "block" }}>
                  Analyseperiode (deze rapportmaand)
                </span>
                <strong>{win.label_nl || `${win.start} t/m ${win.end}`}</strong>
              </div>
              <div>
                <span className="hint" style={{ display: "block" }}>
                  Vergelijkingsperiode (maand ervoor)
                </span>
                <strong>
                  {win.compare_label_nl || `${win.compare_start} t/m ${win.compare_end}`}
                </strong>
              </div>
              <div>
                <span className="hint" style={{ display: "block" }}>
                  Formats &amp; terugkerende patronen (kalenderjaar)
                </span>
                <strong>{fmtWin.label_nl || "—"}</strong>
                <span className="hint" style={{ display: "block", marginTop: "0.15rem" }}>
                  {typeof fmtWin.post_count === "number"
                    ? `${fmtWin.post_count} beschikbare eigen berichten meegenomen`
                    : ""}
                </span>
              </div>
            </div>
          </div>

          {/* 3. Overzicht per bron */}
          <div className="stack">
            <div className="search-form-header">
              <div>
                <h4 style={{ margin: 0 }}>Bronnen voor dit klantrapport</h4>
                <p className="hint" style={{ margin: "0.2rem 0 0" }}>
                  Per bron zie je wat beschikbaar is, wat ontbreekt en of jij nog iets moet doen.
                </p>
              </div>
              <button
                className="secondary"
                type="button"
                onClick={loadInspect}
                disabled={inspectLoading || Boolean(busy)}
              >
                Opnieuw controleren
              </button>
            </div>

            <div className="stack" style={{ gap: "0.6rem" }}>
              {sources.map((src) => {
                const srcKey = src.id || src.key;
                const isReady = Boolean(src.ready || src.status === "ready");
                return (
                  <div
                    key={srcKey}
                    style={{
                      border:
                        src.required && !isReady
                          ? "1px solid #e08a6d"
                          : "1px solid rgba(242, 240, 236, 0.14)",
                      background:
                        src.required && !isReady
                          ? "rgba(217, 119, 87, 0.14)"
                          : "#1a2533",
                      borderRadius: "10px",
                      padding: "0.8rem 0.95rem",
                      display: "flex",
                      flexWrap: "wrap",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      gap: "0.75rem",
                    }}
                  >
                    <div style={{ flex: "1 1 340px" }}>
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "0.45rem",
                          alignItems: "center",
                          marginBottom: "0.35rem",
                        }}
                      >
                        <strong>{src.label}</strong>
                        <span className={src.required ? "pill" : "pill muted"}>
                          {src.requirement_label}
                        </span>
                        <span className={sourcePillClass(src)}>{src.status_label}</span>
                      </div>
                      <p style={{ margin: "0.15rem 0", fontSize: "0.93rem" }}>
                        <strong>Beschikbaar:</strong> {src.available_text}
                      </p>
                      {src.missing_text ? (
                        <p style={{ margin: "0.15rem 0", fontSize: "0.93rem" }}>
                          <strong>Ontbreekt:</strong> {src.missing_text}
                        </p>
                      ) : null}
                      <p
                        className="hint"
                        style={{
                          margin: "0.25rem 0 0",
                          color: src.user_action_needed ? "#ffb49a" : undefined,
                          fontWeight: src.user_action_needed ? 600 : 400,
                        }}
                      >
                        {src.user_action_needed ? "Actie nodig: " : "Wat jij moet doen: "}
                        {src.action_text}
                      </p>
                    </div>

                    {src.cta_label && !isReady ? (
                      <div style={{ alignSelf: "center" }}>
                        <button
                          className={src.required ? "primary" : "secondary"}
                          type="button"
                          disabled={Boolean(busy)}
                          onClick={() => handleSourceAction(src)}
                        >
                          {src.cta_label}
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>

          <label>
            Eigen aandachtspunten of afspraken voor deze maand (optioneel)
            <textarea
              rows={2}
              value={userNotes}
              disabled={Boolean(busy)}
              onChange={(e) => setUserNotes(e.target.value)}
              placeholder="Bijvoorbeeld: extra focus op vacatures, lopende campagne of afgesproken wijziging."
            />
          </label>

          {/* 4. Samenvatting wat de gebruiker nog moet doen + startknop */}
          {!canStartClient ? (
            <div className="banner error" style={{ margin: 0 }}>
              <strong>Je kunt de analyse nog niet starten.</strong>{" "}
              {sourcesOverview.summary_nl ||
                "Vul eerst de verplichte bronnen aan voordat HAMSTER dit klantrapport kan maken."}
              {missingRequired.some((s) => (s.id || s.key) === "trend") ? (
                <div style={{ marginTop: "0.55rem" }}>
                  <button
                    className="primary"
                    type="button"
                    disabled={Boolean(busy)}
                    onClick={() => switchMode("trend")}
                  >
                    Ga naar Algemeen trendrapport – {monthNameNl(month)} {year}
                  </button>
                </div>
              ) : null}
            </div>
          ) : missingOptional.length > 0 ? (
            <div className="banner" style={{ margin: 0 }}>
              <strong>Klaar om te starten.</strong> Alle verplichte bronnen zijn aanwezig (inclusief{" "}
              <em>
                {usableTrend?.title || `Algemeen trendrapport – ${monthNameNl(month)} ${year}`}
              </em>
              ). Aanvullende bronnen die je eventueel later nog kunt toevoegen:{" "}
              <strong>{missingOptional.map((s) => s.label).join(", ")}</strong>.
            </div>
          ) : (
            <div className="banner" style={{ margin: 0 }}>
              <strong>Alle verplichte én aanvullende bronnen staan klaar.</strong> Je kunt het
              klantrapport direct starten.
            </div>
          )}

          <div className="row-actions wrap">
            {aiReady ? (
              <button
                className="primary"
                type="button"
                disabled={!canStartClient || Boolean(busy)}
                onClick={() => runCreateReport({ simulateWithoutPaidAi: false })}
              >
                {busy === "ai" ? "Klantrapport wordt gemaakt…" : "Klantrapport starten"}
              </button>
            ) : null}
            <button
              className={aiReady ? "secondary" : "primary"}
              type="button"
              disabled={!canStartClient || Boolean(busy)}
              onClick={() => runCreateReport({ simulateWithoutPaidAi: true })}
            >
              {busy === "simulate"
                ? "Rapport wordt opgebouwd…"
                : "Klantrapport maken (simulatie zonder AI-kosten)"}
            </button>
            {!aiReady && onOpenSettings ? (
              <button
                className="secondary"
                type="button"
                disabled={Boolean(busy)}
                onClick={() => onOpenSettings("ai")}
              >
                AI-koppeling bekijken in Beheerinstellingen
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* 2B. Algemeen trendrapport: zelfstandig per socialmediakanaal (geen klantperiode/terugblik/X+2) */}
      {mode === "trend" && inspect ? (
        <div className="stack">
          <div
            style={{
              background: "#1a2533",
              border: "1px solid rgba(242, 240, 236, 0.14)",
              borderRadius: "10px",
              padding: "0.9rem 1rem",
            }}
          >
            <h4 style={{ margin: "0 0 0.45rem" }}>
              Zelfstandig Algemeen trendrapport – {monthNameNl(month)} {year}
            </h4>
            <p style={{ margin: "0 0 0.55rem", lineHeight: 1.5 }}>
              Dit rapport behandelt actuele trends per socialmediakanaal voor heel{" "}
              <strong>
                {monthNameNl(month)} {year}
              </strong>
              . Het staat los van individuele klanten en gebruikt geen klantperiode, terugblik of
              vooruitgeschoven planningsmaand.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem" }}>
              {TREND_CHANNELS.map((ch) => (
                <span key={ch} className="pill">
                  {ch}
                </span>
              ))}
            </div>
            <p className="hint" style={{ margin: "0.55rem 0 0" }}>
              Automatische planning: HAMSTER maakt dit rapport op de <strong>1e van iedere maand</strong>{" "}
              automatisch aan (tijdzone <code>Europe/Amsterdam</code>) en koppelt het daarna aan elk
              klantrapport van diezelfde maand.
            </p>
          </div>

          {usableTrend ? (
            <div className="banner" style={{ margin: 0 }}>
              Er staat al een afgerond trendrapport klaar voor {monthNameNl(month)} {year}:{" "}
              <strong>{usableTrend.title}</strong>. Opnieuw uitvoeren via de simulatieknop maakt geen
              dubbel rapport aan.
            </div>
          ) : (
            <label>
              Eigen signalen of bronnen meegeven aan dit trendrapport (optioneel)
              <textarea
                rows={2}
                value={userNotes}
                disabled={Boolean(busy)}
                onChange={(e) => setUserNotes(e.target.value)}
                placeholder="Bijvoorbeeld: nieuwe Instagram-functie, opvallende LinkedIn-update of seizoensinhaker."
              />
            </label>
          )}

          <div className="row-actions wrap">
            {aiReady && !usableTrend ? (
              <button
                className="primary"
                type="button"
                disabled={Boolean(busy)}
                onClick={() => runCreateReport({ simulateWithoutPaidAi: false })}
              >
                {busy === "ai" ? "Trendrapport wordt gemaakt…" : "Algemeen trendrapport starten"}
              </button>
            ) : null}
            <button
              className={!aiReady || usableTrend ? "primary" : "secondary"}
              type="button"
              disabled={Boolean(busy)}
              onClick={() => runCreateReport({ simulateWithoutPaidAi: true })}
            >
              {busy === "simulate"
                ? "Trendrapport controleren / maken…"
                : usableTrend
                  ? `Open bestaand trendrapport (${monthNameNl(month)} ${year})`
                  : "Algemeen trendrapport maken (simulatie zonder AI-kosten)"}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
