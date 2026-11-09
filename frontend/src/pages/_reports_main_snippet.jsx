import { useEffect, useMemo, useState } from "react";
import { api, apiUrl } from "../api.js";

function money(range) {
  if (!range) return "unknown";
  if (range.low == null && range.high == null) return "unknown";
  return `USD ${range.low} – ${range.high} (estimate)`;
}

const STATUS_LABEL = {
  draft: "draft",
  prepared: "prepared",
  running: "running",
  completed: "completed",
  failed: "failed",
  mock_completed: "mock completed",
};

const ITEM_DECISION_OPTIONS = [
  { value: "", label: "(no choice)" },
  { value: "accept", label: "Accept" },
  { value: "correct", label: "Correct" },
  { value: "reject", label: "Reject" },
  { value: "add", label: "Add" },
];

const DETAIL_TABS = [
  ["overview", "Overview"],
  ["analysis", "Analysis"],
  ["action", "Action plan"],
  ["review", "Human review"],
];

function reportStatusDisplay(r) {
  return resolveReportBadge(r).label;
}

function resolveReportBadge(r, presentation = null) {
  if (r?.is_approved || presentation?.status?.approved) {
    return { code: "approved", label: "Approved" };
  }
  if (r?.status === "failed") {
    return { code: "failed", label: "Failed" };
  }
  if (r?.status === "prepared" || !r?.executed_at) {
    return { code: "prepared", label: "Prepared" };
  }
  const partial = Boolean(
    r?.is_partial || presentation?.status?.partial || presentation?.status?.code === "partial_concept"
  );
  if (partial) {
    return { code: "partial_concept", label: "Partial concept" };
  }
  if (r?.review_status === "approved") {
    return { code: "approved", label: "Approved" };
  }
  if (
    r?.review_status === "awaiting_review" ||
    r?.review_status === "in_review" ||
    r?.review_status === "final_draft" ||
    r?.can_review ||
    r?.status === "completed" ||
    r?.status === "mock_completed"
  ) {
    return {
      code: "awaiting_review",
      label:
        r?.review_status_label && r.review_status_label !== "No AI run"
          ? r.review_status_label
          : "Awaiting review",
    };
  }
  return { code: r?.status || "unknown", label: STATUS_LABEL[r?.status] || r?.status || "—" };
}

function formatReportDate(value) {
  if (!value) return "—";
  const raw = String(value).replace("Z", "+00:00");
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return String(value).slice(0, 16);
  return dt.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function periodLabel(r) {
  if (!r) return "—";
  return `${r.period_year}-${String(r.period_month).padStart(2, "0")}`;
}

function groupSavedReports(reports) {
  const map = new Map();
  for (const r of reports || []) {
    const key = `${r.report_type}:${r.period_year}-${String(r.period_month).padStart(2, "0")}`;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(r);
  }
  return Array.from(map.entries())
    .map(([key, items]) => {
      const sorted = [...items].sort((a, b) => b.version - a.version || b.id - a.id);
      return {
        key,
        report_type: sorted[0].report_type,
        period: periodLabel(sorted[0]),
        latest: sorted[0],
        older: sorted.slice(1),
      };
    })
    .sort((a, b) => {
      const da = a.latest.updated_at || a.latest.executed_at || a.latest.prepared_at || "";
      const db = b.latest.updated_at || b.latest.executed_at || b.latest.prepared_at || "";
      return String(db).localeCompare(String(da)) || b.latest.id - a.latest.id;
    });
}

async function downloadReportPdf(clientId, reportId, { setBusy, setError, setNotice }) {
  setBusy(true);
  setError("");
  try {
    const response = await fetch(apiUrl(`/api/clients/${clientId}/reports/${reportId}/pdf`), {
      method: "GET",
      credentials: "include",
    });
    if (!response.ok) {
      let detailMsg = "PDF download failed.";
      try {
        const payload = await response.json();
        if (payload?.detail) detailMsg = payload.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detailMsg);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/i.exec(disposition);
    const filename = match?.[1] || `client-report-${reportId}.pdf`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setNotice(`PDF downloaded for report #${reportId} (no AI credits used).`);
  } catch (exc) {
    setError(exc.message || "PDF download failed.");
  } finally {
    setBusy(false);
  }
}

const MOCK_SCENARIOS = [
  { value: "success_with_sources", label: "Success with sources" },
  { value: "sources_missing", label: "Insufficient/inaccessible sources" },
  { value: "search_not_configured", label: "Search service not configured" },
  { value: "insufficient_budget", label: "Insufficient budget" },
  { value: "generation_failed", label: "Generation failed" },
];

export default function ReportsPage({ client }) {
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState({});
  const now = new Date();
  const [trendYear, setTrendYear] = useState(now.getFullYear());
  const [trendMonth, setTrendMonth] = useState(now.getMonth() + 1);
  const [clientYear, setClientYear] = useState(2026);
  const [clientMonth, setClientMonth] = useState(9);
  const [useCustomDates, setUseCustomDates] = useState(false);
  const [periodStart, setPeriodStart] = useState("2026-09-01");
  const [periodEnd, setPeriodEnd] = useState("2026-09-30");
  const [compareCustom, setCompareCustom] = useState(false);
  const [compareStart, setCompareStart] = useState("");
  const [compareEnd, setCompareEnd] = useState("");
  const [trendId, setTrendId] = useState("");
  const [partialOk, setPartialOk] = useState(false);
  const [researchMode, setResearchMode] = useState("internet");
  const [maxBudget, setMaxBudget] = useState("0.15");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourcePublished, setSourcePublished] = useState("");
  const [sourceExcerpt, setSourceExcerpt] = useState("");
  const [mockScenario, setMockScenario] = useState("success_with_sources");
  const [preview, setPreview] = useState(null);
  const [inspect, setInspect] = useState(null);

  async function reloadList() {
    const payload = await api(`/api/clients/${client.id}/reports`);
    setData(payload);
  }

  async function openReport(id) {
    const payload = await api(`/api/clients/${client.id}/reports/${id}`);
    setSelectedId(id);
    setDetail(payload);
    setPreview(null);
  }

  useEffect(() => {
    setError("");
    setNotice("");
    setDetail(null);
    setSelectedId(null);
    setPreview(null);
    setInspect(null);
    setShowCreate(false);
    reloadList().catch((exc) => setError(exc.message));
  }, [client.id]);

  function clientPeriodParams() {
    const params = new URLSearchParams();
    if (useCustomDates) {
      params.set("start", periodStart);
      params.set("end", periodEnd);
    } else {
      params.set("period_year", String(clientYear));
      params.set("period_month", String(clientMonth));
    }
    if (compareCustom && compareStart && compareEnd) {
      params.set("compare_start", compareStart);
      params.set("compare_end", compareEnd);
    }
    if (trendId) params.set("linked_trend_report_id", trendId);
    return params;
  }

  function clientPrepareBody() {
    const body = {
      period_year: clientYear,
      period_month: clientMonth,
      linked_trend_report_id: trendId || null,
      allow_partial_without_trend: partialOk,
      max_budget_usd: maxBudget === "" ? null : Number(maxBudget),
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
  }

  const trendReports = useMemo(
    () => (data?.reports || []).filter((r) => r.report_type === "trend"),
    [data]
  );
  const reportGroups = useMemo(() => groupSavedReports(data?.reports || []), [data]);

  if (!data) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Loading…</p>;
  }

  const search = data.internet_search || {};

  function renderReportRow(r, { nested = false } = {}) {
    const badge = resolveReportBadge(r);
    const canPdf = r.report_type === "client";
    return (
      <div
        className={`report-list-row${nested ? " is-nested" : ""}${selectedId === r.id ? " is-selected" : ""}`}
        key={r.id}
      >
        <div className="report-list-main">
          <div className="report-list-meta">
            <span className="report-list-period">{periodLabel(r)}</span>
            <span className="report-list-type">
              {r.report_type === "client" ? "Client report" : "Trend report"}
            </span>
            <span className={`report-status-badge is-${badge.code}`}>{badge.label}</span>
            {r.is_mock ? <span className="report-status-badge is-mock">MOCK</span> : null}
          </div>
          <div className="report-list-sub">
            <span>v{r.version}</span>
            <span>·</span>
            <span>{formatReportDate(r.executed_at || r.prepared_at || r.updated_at)}</span>
            <span>·</span>
            <span>#{r.id}</span>
          </div>
        </div>
        <div className="report-list-actions">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => openReport(r.id).catch((exc) => setError(exc.message))}
          >
            Open report
          </button>
          {canPdf ? (
            <button
              className="primary"
              type="button"
              disabled={busy}
              onClick={() => downloadReportPdf(client.id, r.id, { setBusy, setError, setNotice })}
            >
              Download PDF
            </button>
          ) : (
            <span className="hint report-list-pdf-na">PDF for client reports</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack reports-page">
      <div className="search-form-header reports-page-header">
        <div>
          <h3>Reports</h3>
          <p className="hint" style={{ margin: 0 }}>
            Saved reports for <strong>{client.name}</strong>. Opening a report does not start AI.
          </p>
        </div>
        <button className="secondary" type="button" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Hide create form" : "Create report"}
        </button>
      </div>

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      <section className="card stack">
        <div className="search-form-header">
          <h3>Saved reports</h3>
        </div>
        {!reportGroups.length ? <p className="hint">No reports for this client yet.</p> : null}
        <div className="report-list stack">
          {reportGroups.map((group) => (
            <div className="report-list-group" key={group.key}>
              {renderReportRow(group.latest)}
              {group.older.length ? (
                <div className="report-list-older">
                  <button
                    className="linkish"
                    type="button"
                    onClick={() =>
                      setExpandedGroups((prev) => ({
                        ...prev,
                        [group.key]: !prev[group.key],
                      }))
                    }
                  >
                    {expandedGroups[group.key]
                      ? "Hide older versions"
                      : `Older versions (${group.older.length})`}
                  </button>
                  {expandedGroups[group.key]
                    ? group.older.map((r) => renderReportRow(r, { nested: true }))
                    : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      {detail?.report ? (
        <ReportDetail
          clientId={client.id}
          detail={detail}
          busy={busy}
          setBusy={setBusy}
          setDetail={setDetail}
          setError={setError}
          setNotice={setNotice}
          reloadList={reloadList}
          sourceTitle={sourceTitle}
          setSourceTitle={setSourceTitle}
          sourceUrl={sourceUrl}
          setSourceUrl={setSourceUrl}
          sourcePublished={sourcePublished}
          setSourcePublished={setSourcePublished}
          sourceExcerpt={sourceExcerpt}
          setSourceExcerpt={setSourceExcerpt}
          mockScenario={mockScenario}
          setMockScenario={setMockScenario}
          maxBudget={maxBudget}
          preview={preview}
          setPreview={setPreview}
          onClose={() => {
            setDetail(null);
            setSelectedId(null);
            setPreview(null);
          }}
        />
      ) : selectedId ? (
        <p className="muted">Loading report…</p>
      ) : null}

      {showCreate ? (
        <div className="stack report-create-panel">
          <section className="card stack">
            <div className="search-form-header">
              <h3>Internet research / generation</h3>
            </div>
            <p className={search.available ? "banner" : "banner warn-soft"}>
              {search.available
                ? `Search route available: ${search.exact_model_id || search.model}`
                : `Not yet available for real search generation — missing: ${
                    search.missing_setting || "AI_API_KEY / Gemini model"
                  }. You can still prepare, inspect, and mock-test.`}
            </p>
            {search.reason ? <p className="hint">{search.reason}</p> : null}
            {search.note ? <p className="hint">{search.note}</p> : null}
            {search.hard_budget_note ? <p className="hint">{search.hard_budget_note}</p> : null}
            <p className="hint">
              Prompt version: {data.prompt_version} · OpenAI-compat grounding:{" "}
              {search.openai_compat_supports_grounding ? "yes" : "no (native generateContent required)"}
            </p>
            {search.search_pricing ? (
              <p className="hint">
                Search: {search.search_pricing.free_queries_per_month} free/month, then $
                {search.search_pricing.paid_per_1000_queries}/1k · rate date{" "}
                {search.search_pricing.rate_date}
              </p>
            ) : null}
          </section>

          <section className="card stack">
            <div className="search-form-header">
              <h3>Prepare trend report</h3>
            </div>
            <p className="hint">
              Choose month and sources mode. Strategy topics are included as context. Saving a URL
              alone does not mean the content has been read.
            </p>
            <div className="row-actions wrap">
              <label>
                Run year
                <input
                  type="number"
                  value={trendYear}
                  onChange={(e) => setTrendYear(Number(e.target.value))}
                />
              </label>
              <label>
                Run month
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={trendMonth}
                  onChange={(e) => setTrendMonth(Number(e.target.value))}
                />
              </label>
              <label>
                Research
                <select value={researchMode} onChange={(e) => setResearchMode(e.target.value)}>
                  <option value="internet">Internet research (Gemini Google Search)</option>
                  <option value="manual">Provided / manual sources</option>
                </select>
              </label>
              <label>
                Max. budget USD (estimate gate)
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={maxBudget}
                  onChange={(e) => setMaxBudget(e.target.value)}
                />
              </label>
              <button
                className="primary"
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError("");
                  api(`/api/clients/${client.id}/reports/trend/prepare`, {
                    method: "POST",
                    body: {
                      run_year: trendYear,
                      run_month: trendMonth,
                      sources: [],
                      research_mode: researchMode,
                      max_budget_usd: maxBudget === "" ? null : Number(maxBudget),
                    },
                  })
                    .then(async (payload) => {
                      setDetail(payload);
                      setSelectedId(payload.report.id);
                      setPreview(null);
                      setShowCreate(false);
                      await reloadList();
                      setNotice("Trend report prepared (no AI/search request).");
                    })
                    .catch((exc) => setError(exc.message))
                    .finally(() => setBusy(false));
                }}
              >
                Prepare trend report
              </button>
            </div>
          </section>

          <section className="card stack">
            <div className="search-form-header">
              <h3>Client report — review data</h3>
            </div>
            <p className="hint">
              Client: <strong>{client.name}</strong>. Python shows figures and prompt input without an
              AI call.
            </p>
            <div className="row-actions wrap">
              <label className="row-actions">
                <input
                  type="checkbox"
                  checked={useCustomDates}
                  onChange={(e) => setUseCustomDates(e.target.checked)}
                />
                Custom period instead of calendar month
              </label>
              {!useCustomDates ? (
                <>
                  <label>
                    Year
                    <input
                      type="number"
                      value={clientYear}
                      onChange={(e) => setClientYear(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    Month
                    <input
                      type="number"
                      min={1}
                      max={12}
                      value={clientMonth}
                      onChange={(e) => setClientMonth(Number(e.target.value))}
                    />
                  </label>
                </>
              ) : (
                <>
                  <label>
                    Start
                    <input
                      type="date"
                      value={periodStart}
                      onChange={(e) => setPeriodStart(e.target.value)}
                    />
                  </label>
                  <label>
                    End
                    <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
                  </label>
                </>
              )}
              <label className="row-actions">
                <input
                  type="checkbox"
                  checked={compareCustom}
                  onChange={(e) => setCompareCustom(e.target.checked)}
                />
                Comparison period manual
              </label>
              {compareCustom ? (
                <>
                  <label>
                    Compare start
                    <input
                      type="date"
                      value={compareStart}
                      onChange={(e) => setCompareStart(e.target.value)}
                    />
                  </label>
                  <label>
                    Compare end
                    <input
                      type="date"
                      value={compareEnd}
                      onChange={(e) => setCompareEnd(e.target.value)}
                    />
                  </label>
                </>
              ) : null}
              <label>
                Trend report (optional for inspect)
                <select value={trendId} onChange={(e) => setTrendId(e.target.value)}>
                  <option value="">(none)</option>
                  {trendReports.map((r) => (
                    <option key={r.id} value={String(r.id)}>
                      #{r.id} v{r.version} · {r.period_year}-{String(r.period_month).padStart(2, "0")} ·{" "}
                      {STATUS_LABEL[r.status] || r.status}
                      {r.is_mock ? " · MOCK sample" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError("");
                  const q = clientPeriodParams().toString();
                  api(`/api/clients/${client.id}/reports/client/inspect?${q}`)
                    .then((payload) => {
                      setInspect(payload);
                      setNotice("Data loaded (no AI, not saved).");
                    })
                    .catch((exc) => setError(exc.message))
                    .finally(() => setBusy(false));
                }}
              >
                Show figures &amp; prompt input
              </button>
            </div>

            {inspect ? <ClientReportInspectView data={inspect} /> : null}

            <h4>Save as prepared client report</h4>
            <p className="hint">
              Saves figures and prompt input. No AI conclusions. Without Claude/Gemini the status stays
              “prepared / AI not run yet”.
            </p>
            <div className="row-actions wrap">
              <label>
                Max. budget USD
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={maxBudget}
                  onChange={(e) => setMaxBudget(e.target.value)}
                />
              </label>
              <label className="row-actions">
                <input
                  type="checkbox"
                  checked={partialOk}
                  onChange={(e) => setPartialOk(e.target.checked)}
                />
                Allow partial without trend report
              </label>
              <button
                className="secondary"
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError("");
                  api(`/api/clients/${client.id}/reports/client/prepare`, {
                    method: "POST",
                    body: clientPrepareBody(),
                  })
                    .then(async (payload) => {
                      setDetail(payload);
                      setSelectedId(payload.report.id);
                      setPreview(null);
                      setShowCreate(false);
                      await reloadList();
                      setNotice(
                        "Client report prepared and saved (figures + prompt input; no AI analysis)."
                      );
                    })
                    .catch((exc) => setError(exc.message))
                    .finally(() => setBusy(false));
                }}
              >
                Prepare &amp; save client report
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
