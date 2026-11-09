import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const MONTHS_NL = [
  "",
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

const TYPE_OPTIONS = [
  {
    value: "client",
    label: "Klantrapport",
    blurb:
      "Bekijk hoe de posts van één klant hebben gepresteerd en krijg advies voor de volgende planning.",
    example: "Welke posts van Red Rock werkten goed in september? Wat gaan we herhalen of testen?",
  },
  {
    value: "trend",
    label: "Trendrapport",
    blurb:
      "Bekijk ontwikkelingen in de markt en op social media en haal daar ideeën uit voor de komende planning.",
    example:
      "Welke nieuwe Instagram-formats zijn interessant voor de novemberplanning?",
  },
];

function money(range) {
  if (!range) return "nog onbekend";
  if (range.low == null && range.high == null) return "nog onbekend";
  return `USD ${range.low} – ${range.high}`;
}

function monthLabel(year, month) {
  if (year && month >= 1 && month <= 12) return `${MONTHS_NL[month]} ${year}`;
  return "—";
}

function suggestTitle(reportType, clientName, year, month) {
  if (reportType === "trend") return `Social trends – planning ${monthLabel(year, month)}`;
  return `${clientName} – analyse ${monthLabel(year, month)}`;
}

function defaultCompareLabel(year, month) {
  const d = new Date(Date.UTC(year, month - 1, 1));
  d.setUTCMonth(d.getUTCMonth() - 1);
  return monthLabel(d.getUTCFullYear(), d.getUTCMonth() + 1);
}

function isUsableTrend(r) {
  if (!r || r.report_type !== "trend") return false;
  if (r.status === "failed") return false;
  if (r.status === "completed" || r.status === "mock_completed") return true;
  if (r.analysis_usable) return true;
  return Boolean(r.executed_at);
}

function isTechnicalTrendTitle(title) {
  const t = String(title || "").trim().toLowerCase();
  if (!t) return true;
  return (
    t.startsWith("created in") ||
    t.startsWith("gemaakt in") ||
    t.includes("internetonderzoek") ||
    t.includes("handmatige bronnen")
  );
}

function trendOptionLabel(r) {
  const planY = r.planning_year || r.period_year;
  const planM = r.planning_month || r.period_month;
  const fallback = `Social trends – planning ${monthLabel(planY, planM)}`;
  const title = isTechnicalTrendTitle(r.title) ? fallback : String(r.title).trim();
  const partial = r.is_partial ? " · onderzoek gedeeltelijk" : "";
  return `${title} · planning ${monthLabel(planY, planM)}${partial}`;
}

export default function NewAnalysisWizard({
  client,
  trendReports,
  search,
  busy,
  setBusy,
  setError,
  setNotice,
  onCancel,
  onOpenedReport,
}) {
  const [step, setStep] = useState(1);
  const [reportType, setReportType] = useState("client");
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState(9);
  const [title, setTitle] = useState(() => suggestTitle("client", client.name, 2026, 9));
  const [titleTouched, setTitleTouched] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [useCustomDates, setUseCustomDates] = useState(false);
  const [periodStart, setPeriodStart] = useState("2026-09-01");
  const [periodEnd, setPeriodEnd] = useState("2026-09-30");
  const [compareCustom, setCompareCustom] = useState(false);
  const [compareStart, setCompareStart] = useState("");
  const [compareEnd, setCompareEnd] = useState("");
  const [trendId, setTrendId] = useState("");
  const [researchMode, setResearchMode] = useState("internet");
  const [inspect, setInspect] = useState(null);
  const [prepared, setPrepared] = useState(null);
  const [execPreview, setExecPreview] = useState(null);
  const [runState, setRunState] = useState(null);
  const [runError, setRunError] = useState("");

  const usableTrends = useMemo(
    () => (trendReports || []).filter(isUsableTrend),
    [trendReports]
  );

  const selectedTrend = useMemo(
    () => usableTrends.find((r) => String(r.id) === String(trendId)) || null,
    [usableTrends, trendId]
  );

  useEffect(() => {
    if (titleTouched) return;
    setTitle(suggestTitle(reportType, client.name, year, month));
  }, [reportType, client.name, year, month, titleTouched]);

  const typeMeta = TYPE_OPTIONS.find((t) => t.value === reportType);

  const compareHint = useMemo(() => {
    if (reportType === "trend") return null;
    if (compareCustom && compareStart && compareEnd) return `${compareStart} t/m ${compareEnd}`;
    if (inspect?.period?.compare_label) return inspect.period.compare_label;
    if (useCustomDates) return "vorige periode van gelijke lengte";
    return defaultCompareLabel(year, month);
  }, [
    reportType,
    compareCustom,
    compareStart,
    compareEnd,
    inspect,
    useCustomDates,
    year,
    month,
  ]);

  const periodParams = useMemo(() => {
    const params = new URLSearchParams();
    if (useCustomDates) {
      params.set("start", periodStart);
      params.set("end", periodEnd);
    } else {
      params.set("period_year", String(year));
      params.set("period_month", String(month));
    }
    if (compareCustom && compareStart && compareEnd) {
      params.set("compare_start", compareStart);
      params.set("compare_end", compareEnd);
    }
    if (trendId) params.set("linked_trend_report_id", trendId);
    return params;
  }, [
    useCustomDates,
    periodStart,
    periodEnd,
    year,
    month,
    compareCustom,
    compareStart,
    compareEnd,
    trendId,
  ]);

  const prepareBody = useMemo(() => {
    if (reportType === "trend") {
      return {
        run_year: year,
        run_month: month,
        sources: [],
        research_mode: researchMode,
        max_budget_usd: null,
        title: title.trim() || suggestTitle("trend", client.name, year, month),
      };
    }
    const body = {
      period_year: year,
      period_month: month,
      linked_trend_report_id: trendId || null,
      allow_partial_without_trend: !trendId,
      max_budget_usd: null,
      title: title.trim() || suggestTitle("client", client.name, year, month),
    };
    if (useCustomDates) {
      body.start = periodStart;
      body.end = periodEnd;
    }
    if (compareCustom && compareStart && compareEnd) {
      body.compare_start = compareStart;
      body.compare_end = compareEnd;
    }
    return body;
  }, [
    reportType,
    year,
    month,
    researchMode,
    title,
    client.name,
    trendId,
    useCustomDates,
    periodStart,
    periodEnd,
    compareCustom,
    compareStart,
    compareEnd,
  ]);

  const costLabel = useMemo(() => {
    const est =
      execPreview?.estimate?.estimated_cost_usd ||
      prepared?.report?.estimate?.estimated_cost_usd ||
      execPreview?.estimated_cost_usd;
    if (est) return `${money(est)} (zo zuinig mogelijk)`;
    return "nog onbekend — zo zuinig mogelijk";
  }, [execPreview, prepared]);

  const postCount =
    inspect?.data_coverage?.analysis_period?.post_count ??
    inspect?.metrics?.post_count ??
    null;
  const byPlatform =
    inspect?.data_coverage?.posts_by_platform || inspect?.metrics?.by_platform || {};
  const missing = inspect?.missing || [];
  const appliedSettings = useMemo(() => {
    const bits = [];
    if (reportType === "client") {
      if (useCustomDates) bits.push(`aangepaste periode ${periodStart} t/m ${periodEnd}`);
      if (compareCustom && compareStart && compareEnd) {
        bits.push(`eigen vergelijking ${compareStart} t/m ${compareEnd}`);
      }
      if (selectedTrend) bits.push(`trend: ${selectedTrend.title || `#${selectedTrend.id}`}`);
      else bits.push("geen trendrapport");
    } else {
      bits.push(
        researchMode === "internet" ? "internetzoeken aan" : "handmatige bronnen"
      );
    }
    return bits;
  }, [
    reportType,
    useCustomDates,
    periodStart,
    periodEnd,
    compareCustom,
    compareStart,
    compareEnd,
    selectedTrend,
    researchMode,
  ]);

  async function prepareFresh() {
    const path =
      reportType === "trend"
        ? `/api/clients/${client.id}/reports/trend/prepare`
        : `/api/clients/${client.id}/reports/client/prepare`;
    const payload = await api(path, { method: "POST", body: prepareBody });
    setPrepared(payload);
    return payload;
  }

  async function goToReview() {
    setError("");
    setBusy(true);
    setPrepared(null);
    setExecPreview(null);
    setRunState("preparing");
    setRunError("");
    try {
      if (reportType === "client") {
        const payload = await api(
          `/api/clients/${client.id}/reports/client/inspect?${periodParams.toString()}`
        );
        setInspect(payload);
      } else {
        setInspect({
          missing: search?.available
            ? []
            : [
                `Internetzoeken nog niet beschikbaar (${
                  search?.missing_setting || "AI_API_KEY / Gemini-model"
                }).`,
              ],
          metrics: { post_count: 0, by_platform: {} },
          data_coverage: { posts_by_platform: {} },
        });
      }
      const payload = await prepareFresh();
      const preview = await api(
        `/api/clients/${client.id}/reports/${payload.report.id}/execution-preview`
      );
      setExecPreview(preview);
      setStep(2);
      setRunState(null);
      setNotice("Voorbereiding klaar — nog geen betaalde analyse gestart.");
    } catch (exc) {
      setRunState("failed");
      setRunError(exc.message || "Voorbereiding mislukt.");
      setError(exc.message || "Voorbereiding mislukt.");
    } finally {
      setBusy(false);
    }
  }

  async function startAnalysis() {
    setError("");
    setRunError("");
    setBusy(true);
    setRunState("starting");
    try {
      let payload = prepared;
      if (!payload?.report?.id) payload = await prepareFresh();
      const reportId = payload.report.id;
      if (title.trim() && title.trim() !== payload.report.title) {
        payload = await api(`/api/clients/${client.id}/reports/${reportId}/title`, {
          method: "PATCH",
          body: { title: title.trim() },
        });
        setPrepared(payload);
      }
      const result = await api(`/api/clients/${client.id}/reports/${reportId}/execute`, {
        method: "POST",
        body: { dry_run_paid: false, max_budget_usd: null },
      });
      setNotice(`Analyse klaar voor rapport #${reportId}.`);
      setRunState(null);
      onOpenedReport(result);
    } catch (exc) {
      const msg = exc.message || "Analyse mislukt.";
      setRunState("failed");
      setRunError(msg);
      setError(msg);
      if (prepared?.report?.id) {
        try {
          setPrepared(await api(`/api/clients/${client.id}/reports/${prepared.report.id}`));
        } catch {
          /* ignore */
        }
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack report-wizard" aria-label="Nieuwe analyse">
      <div className="search-form-header reports-page-header">
        <div>
          <h3 style={{ marginTop: 0 }}>Nieuwe analyse</h3>
          <p className="hint" style={{ margin: 0 }}>
            Stap {step} van 2{typeMeta ? ` · ${typeMeta.label}` : ""}
          </p>
        </div>
        <button className="secondary" type="button" disabled={busy} onClick={onCancel}>
          Annuleren
        </button>
      </div>

      <ol className="report-wizard-steps" aria-label="Stappen">
        <li className={step === 1 ? "is-active" : "is-done"}>Kies type &amp; periode</li>
        <li className={step === 2 ? "is-active" : ""}>Controleer &amp; start</li>
      </ol>

      {step === 1 ? (
        <div className="stack">
          <p className="banner">
            Actieve klant: <strong>{client.name}</strong>
          </p>

          <fieldset className="report-type-fieldset">
            <legend>Welk rapport maak je?</legend>
            <div className="report-type-grid">
              {TYPE_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={`report-type-card${reportType === opt.value ? " is-selected" : ""}`}
                >
                  <input
                    type="radio"
                    name="report-type"
                    value={opt.value}
                    checked={reportType === opt.value}
                    onChange={() => {
                      setReportType(opt.value);
                      setTitleTouched(false);
                      setTrendId("");
                    }}
                  />
                  <span className="report-type-label">{opt.label}</span>
                  <span className="hint">{opt.blurb}</span>
                  <span className="hint report-type-example">
                    <em>Voorbeeld:</em> {opt.example}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <label>
            {reportType === "client" ? "Klantrapportnaam" : "Trendrapportnaam"}
            <input
              value={title}
              onChange={(e) => {
                setTitleTouched(true);
                setTitle(e.target.value);
              }}
              placeholder={suggestTitle(reportType, client.name, year, month)}
            />
          </label>
          <p className="hint" style={{ marginTop: 0 }}>
            Voorstel op basis van type en periode — pas aan als je wilt.
          </p>

          <div className="row-actions wrap">
            <label>
              {reportType === "trend" ? "Planningsmaand — jaar" : "Analyseperiode — jaar"}
              <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} />
            </label>
            <label>
              Maand
              <input
                type="number"
                min={1}
                max={12}
                value={month}
                onChange={(e) => setMonth(Number(e.target.value))}
              />
            </label>
          </div>

          {reportType === "client" ? (
            <p className="hint" style={{ margin: 0 }}>
              Standaardvergelijking: <strong>{compareHint}</strong>
            </p>
          ) : (
            <p className="hint" style={{ margin: 0 }}>
              Internetzoeken:{" "}
              <strong>{researchMode === "internet" ? "aan" : "uit (handmatige bronnen)"}</strong>
            </p>
          )}

          <details
            className="report-more-options"
            open={showMore}
            onToggle={(e) => setShowMore(e.currentTarget.open)}
          >
            <summary>Meer opties</summary>
            <div className="stack" style={{ marginTop: "0.75rem" }}>
              {reportType === "client" ? (
                <>
                  <label className="row-actions">
                    <input
                      type="checkbox"
                      checked={useCustomDates}
                      onChange={(e) => setUseCustomDates(e.target.checked)}
                    />
                    Aangepaste analyseperiode i.p.v. kalendermaand
                  </label>
                  {useCustomDates ? (
                    <div className="row-actions wrap">
                      <label>
                        Start
                        <input
                          type="date"
                          value={periodStart}
                          onChange={(e) => setPeriodStart(e.target.value)}
                        />
                      </label>
                      <label>
                        Eind
                        <input
                          type="date"
                          value={periodEnd}
                          onChange={(e) => setPeriodEnd(e.target.value)}
                        />
                      </label>
                    </div>
                  ) : null}

                  <label className="row-actions">
                    <input
                      type="checkbox"
                      checked={compareCustom}
                      onChange={(e) => setCompareCustom(e.target.checked)}
                    />
                    Afwijkende vergelijkingsperiode
                  </label>
                  {compareCustom ? (
                    <div className="row-actions wrap">
                      <label>
                        Vergelijk start
                        <input
                          type="date"
                          value={compareStart}
                          onChange={(e) => setCompareStart(e.target.value)}
                        />
                      </label>
                      <label>
                        Vergelijk eind
                        <input
                          type="date"
                          value={compareEnd}
                          onChange={(e) => setCompareEnd(e.target.value)}
                        />
                      </label>
                    </div>
                  ) : null}

                  <div className="stack">
                    <label>
                      Trendrapport meenemen (optioneel)
                      <select value={trendId} onChange={(e) => setTrendId(e.target.value)}>
                        <option value="">Geen trendrapport</option>
                        {usableTrends.map((r) => (
                          <option key={r.id} value={String(r.id)}>
                            {trendOptionLabel(r)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="hint" style={{ margin: 0 }}>
                      Voeg een bestaand trendrapport toe als je markttrends wilt meenemen in het
                      advies voor deze klant. Je kunt hetzelfde trendrapport voor meerdere klanten
                      gebruiken.
                    </p>
                    {!usableTrends.length ? (
                      <p className="hint">
                        Nog geen bruikbaar trendrapport. Maak eerst een Trendrapport of kies Geen
                        trendrapport.
                      </p>
                    ) : null}
                  </div>
                </>
              ) : (
                <>
                  <label>
                    Bronnen / internetzoeken
                    <select value={researchMode} onChange={(e) => setResearchMode(e.target.value)}>
                      <option value="internet">Internetzoeken aan (Gemini Google Search)</option>
                      <option value="manual">Alleen handmatige bronnen</option>
                    </select>
                  </label>
                  <p className="hint" style={{ margin: 0 }}>
                    Extra bronnen kun je na de voorbereiding toevoegen onder Technische details.
                  </p>
                </>
              )}
            </div>
          </details>

          <div className="row-actions wrap">
            <button className="primary" type="button" disabled={busy || !title.trim()} onClick={goToReview}>
              Volgende: controleer &amp; start
            </button>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="stack">
          <p className="banner">
            <strong>{title.trim() || prepared?.report?.title || typeMeta?.label}</strong>
          </p>

          <ul className="plain-list report-wizard-summary">
            {reportType === "client" ? (
              <>
                <li>
                  <strong>Klant:</strong> {client.name}
                </li>
                <li>
                  <strong>Analyseperiode:</strong>{" "}
                  {useCustomDates
                    ? `${periodStart} t/m ${periodEnd}`
                    : monthLabel(year, month)}
                </li>
                <li>
                  <strong>Vergelijkingsperiode:</strong> {compareHint}
                </li>
                <li>
                  <strong>Aantal posts:</strong>{" "}
                  {postCount != null
                    ? `${postCount}${
                        Object.keys(byPlatform).length
                          ? ` (${Object.entries(byPlatform)
                              .map(([n, c]) => `${n} ${c}`)
                              .join(" · ")})`
                          : ""
                      }`
                    : "—"}
                </li>
                <li>
                  <strong>Trendrapport:</strong>{" "}
                  {selectedTrend
                    ? selectedTrend.title || `Social trends #${selectedTrend.id}`
                    : "Geen trendrapport"}
                </li>
              </>
            ) : (
              <>
                <li>
                  <strong>Planningsmaand:</strong> {monthLabel(year, month)}
                </li>
                <li>
                  <strong>Internetzoeken:</strong>{" "}
                  {researchMode === "internet" ? "aan" : "uit"}
                </li>
                <li>
                  <strong>Bronnen:</strong> nog geen handmatige bronnen (optioneel later toe te
                  voegen)
                </li>
              </>
            )}
            <li>
              <strong>Geschatte kosten:</strong> {costLabel}
            </li>
            <li className="hint">
              <strong>Van toepassing:</strong> {appliedSettings.join(" · ")}
            </li>
          </ul>

          {missing.length ? (
            <p className="banner warn-soft">
              Let op: {missing.slice(0, 2).join(" · ")}
              {missing.length > 2 ? ` · +${missing.length - 2} meer` : ""}
            </p>
          ) : null}

          {runState === "preparing" || runState === "starting" ? (
            <p className="banner">
              {runState === "preparing" ? "Bezig met voorbereiden…" : "Analyse wordt gestart…"}
            </p>
          ) : null}

          {runState === "failed" ? (
            <div className="banner error stack">
              <strong>Analyse niet gestart of mislukt</strong>
              <p>{runError || "Onbekende fout."}</p>
              <p className="hint">
                Controleer of de periode posts heeft, of Synchroniseer Meta recent is gedraaid, of
                open het voorbereide rapport. Er is geen nieuwe kostenpost als de start vóór de
                betaalde aanroep is geblokkeerd.
              </p>
              {prepared?.report?.id ? (
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => onOpenedReport(prepared)}
                >
                  Open voorbereid rapport
                </button>
              ) : null}
            </div>
          ) : null}

          <p className="hint">
            Alleen <strong>Start analyse</strong> start de betaalde run. Oude pogingen blijven in het
            activiteitenlogboek (eerdere versies).
          </p>

          <div className="row-actions wrap">
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => {
                setStep(1);
                setPrepared(null);
                setExecPreview(null);
              }}
            >
              Terug
            </button>
            <button className="primary" type="button" disabled={busy} onClick={startAnalysis}>
              Start analyse
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
