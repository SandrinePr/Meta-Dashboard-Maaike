import { useEffect, useMemo, useState } from "react";
import { api, apiUrl } from "../api.js";
import NewAnalysisWizard from "../components/NewAnalysisWizard.jsx";

function money(range) {
  if (!range) return "unknown";
  if (range.low == null && range.high == null) return "unknown";
  return `USD ${range.low} – ${range.high} (estimate)`;
}

const STATUS_LABEL = {
  draft: "concept",
  prepared: "voorbereid",
  running: "bezig",
  completed: "voltooid",
  failed: "mislukt",
  mock_completed: "mock voltooid",
};

function reportTypeLabel(type) {
  if (type === "client") return "Klantrapport";
  if (type === "trend") return "Trendrapport";
  return type || "Rapport";
}

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

function monthLabelNl(year, month) {
  if (year && month >= 1 && month <= 12) return `${MONTHS_NL[month]} ${year}`;
  return "—";
}

function isTechnicalTitle(title) {
  const t = String(title || "").trim().toLowerCase();
  if (!t) return true;
  return (
    t.startsWith("client report") ||
    t.startsWith("created in") ||
    t.startsWith("qa real") ||
    t.includes("json-syntaxherstel")
  );
}

function displayReportTitle(r, clientName = "Klant") {
  const raw = String(r?.title || "").trim();
  if (raw && !isTechnicalTitle(raw)) return raw;
  if (r?.report_type === "trend") {
    const y = r.planning_year || r.period_year;
    const m = r.planning_month || r.period_month;
    return `Social trends – planning ${monthLabelNl(y, m)}`;
  }
  return `${clientName} – analyse ${monthLabelNl(r?.period_year, r?.period_month)}`;
}

function reportStatusDisplay(r) {
  return resolveReportBadge(r).label;
}

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.04a1.003 1.003 0 0 0 0-1.42l-2.54-2.54a1.003 1.003 0 0 0-1.42 0l-1.83 1.83 3.96 3.96 1.83-1.83z"
      />
    </svg>
  );
}

function resolveReportBadge(r, presentation = null) {
  if (r?.is_approved || presentation?.status?.approved) {
    return { code: "approved", label: "Goedgekeurd" };
  }
  if (r?.status === "failed") {
    return { code: "generation_failed", label: "Mislukt" };
  }
  if (r?.status === "prepared" || !r?.executed_at) {
    return { code: "prepared", label: "Voorbereid" };
  }
  const partial = Boolean(
    r?.is_partial || presentation?.status?.partial || presentation?.status?.code === "partial_concept"
  );
  if (partial) {
    return { code: "partial_concept", label: "Deels concept" };
  }
  if (r?.review_status === "approved") {
    return { code: "approved", label: "Goedgekeurd" };
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
          : "Ter controle",
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
  const [maxBudget, setMaxBudget] = useState("0.15");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourcePublished, setSourcePublished] = useState("");
  const [sourceExcerpt, setSourceExcerpt] = useState("");
  const [mockScenario, setMockScenario] = useState("success_with_sources");
  const [preview, setPreview] = useState(null);

  async function reloadList() {
    const payload = await api(`/api/clients/${client.id}/reports`);
    setData(payload);
  }

  async function openReport(id) {
    setNotice("");
    setError("");
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
    setShowCreate(false);
    reloadList().catch((exc) => setError(exc.message));
  }, [client.id]);

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
    const title = displayReportTitle(r, client.name);
    return (
      <div
        className={`report-list-row${nested ? " is-nested" : ""}${selectedId === r.id ? " is-selected" : ""}`}
        key={r.id}
      >
        <div className="report-list-main">
          <span className="report-list-title">{title}</span>
          <div className="report-list-meta">
            <span className="report-list-type">{reportTypeLabel(r.report_type)}</span>
            <span className="report-list-period">{periodLabel(r)}</span>
            <span className={`report-status-badge is-${badge.code}`}>{badge.label}</span>
            {r.is_mock ? <span className="report-status-badge is-mock">MOCK</span> : null}
          </div>
          <details className="report-list-sub">
            <summary className="linkish">Details</summary>
            <div className="hint" style={{ marginTop: "0.35rem" }}>
              #{r.id} · v{r.version} · {formatReportDate(r.executed_at || r.prepared_at || r.updated_at)}
              {r.is_partial ? " · onderzoek/rapport deels" : ""}
            </div>
          </details>
        </div>
        <div className="report-list-actions">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => openReport(r.id).catch((exc) => setError(exc.message))}
          >
            Openen
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
            <span className="hint report-list-pdf-na">PDF alleen bij klantrapport</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack reports-page">
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      {showCreate ? (
        <NewAnalysisWizard
          key={`wizard-${client.id}`}
          client={client}
          trendReports={trendReports}
          search={search}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          setNotice={setNotice}
          onCancel={() => {
            setShowCreate(false);
          }}
          onOpenedReport={async (payload) => {
            setShowCreate(false);
            setDetail(payload);
            setSelectedId(payload?.report?.id || null);
            setPreview(null);
            await reloadList().catch(() => {});
          }}
        />
      ) : null}

      {!showCreate && detail?.report ? (
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
      ) : null}

      {!showCreate && selectedId && !detail?.report ? (
        <p className="muted">Rapport laden…</p>
      ) : null}

      {!showCreate && !detail && !selectedId ? (
        <>
          <div className="search-form-header reports-page-header">
            <div>
              <h3 style={{ marginTop: 0 }}>Rapporten</h3>
              <p className="hint" style={{ margin: 0 }}>
                Voor <strong>{client.name}</strong>. Openen start geen AI.
              </p>
            </div>
            <button
              className="primary"
              type="button"
              onClick={() => {
                setShowCreate(true);
                setDetail(null);
                setSelectedId(null);
                setError("");
                setNotice("");
              }}
            >
              Nieuwe analyse
            </button>
          </div>

          <section className="card stack">
            {!reportGroups.length ? (
              <p className="hint">Nog geen rapporten voor deze klant. Start met Nieuwe analyse.</p>
            ) : null}
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
                          ? "Verberg activiteitenlogboek"
                          : `Activiteitenlogboek (${group.older.length})`}
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
        </>
      ) : null}
    </div>
  );
}

function fmtNum(value) {
  if (value == null || value === "") return "—";
  return typeof value === "number" ? value.toLocaleString("en-US") : String(value);
}

function DeltaCell({ delta }) {
  if (!delta) return <span className="hint">—</span>;
  const abs = delta.absolute;
  const label = delta.direction_label || "—";
  let pctText = "no %";
  if (delta.pct_available && delta.pct != null) {
    pctText = `${delta.pct > 0 ? "+" : ""}${delta.pct}%`;
  } else if (delta.pct_note) {
    pctText = delta.pct_note;
  }
  return (
    <span>
      {abs == null ? "—" : `${abs > 0 ? "+" : ""}${fmtNum(abs)}`} · {label}
      <br />
      <span className="hint">{pctText}</span>
    </span>
  );
}

function MetricTotalsTable({ metrics, title }) {
  if (!metrics) return null;
  const totals = metrics.totals || {};
  const averages = metrics.averages || {};
  const available = metrics.available_counts || {};
  const missing = metrics.missing_counts || {};
  const keys = ["reach", "views", "likes", "comments", "shares", "saves", "clicks"];
  return (
    <div className="stack">
      <h4>{title}</h4>
      <p className="hint">
        Posts: {fmtNum(metrics.post_count)} · totals and averages are separate · missing
        values do not count as 0
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Total (known)</th>
              <th>Average (known)</th>
              <th>Known</th>
              <th>Missing</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const tot = totals[key];
              const sum = tot && typeof tot === "object" ? tot.sum : tot;
              const avg =
                averages[key] != null
                  ? averages[key]
                  : tot && typeof tot === "object"
                    ? tot.average_over_known
                    : null;
              const known =
                available[key] != null
                  ? available[key]
                  : tot && typeof tot === "object"
                    ? tot.known_count
                    : null;
              const miss =
                missing[key] != null
                  ? missing[key]
                  : tot && typeof tot === "object"
                    ? tot.missing_count
                    : null;
              return (
                <tr key={key}>
                  <td>{key}</td>
                  <td>{fmtNum(sum)}</td>
                  <td>{fmtNum(avg)}</td>
                  <td>{fmtNum(known)}</td>
                  <td>{fmtNum(miss)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GroupTable({ title, groups, compareRows, unclassified }) {
  return (
    <div className="stack">
      <h4>{title}</h4>
      {unclassified?.count ? (
        <p className="banner error">
          Not yet classified: {unclassified.count} post(s)
          {unclassified.posts?.length ? (
            <span className="hint">
              {" "}
              — e.g. #
              {unclassified.posts
                .slice(0, 5)
                .map((p) => p.post_id)
                .join(", #")}
            </span>
          ) : null}
        </p>
      ) : (
        <p className="hint">All posts in this group are classified.</p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Posts</th>
              <th>Total reach</th>
              <th>Avg. reach</th>
              <th>Reach known / missing</th>
              <th>vs previous (reach sum)</th>
            </tr>
          </thead>
          <tbody>
            {(groups || []).map((g) => {
              const cmp = (compareRows || []).find((r) => r.name === g.name);
              return (
                <tr key={g.name} className={g.is_unclassified ? "is-warning" : undefined}>
                  <td>
                    {g.name}
                    {g.is_unclassified ? " · unclassified" : ""}
                  </td>
                  <td>{g.post_count}</td>
                  <td>{fmtNum(g.reach_sum ?? g.totals?.reach)}</td>
                  <td>{fmtNum(g.reach_avg ?? g.averages?.reach)}</td>
                  <td>
                    {fmtNum(g.known_reach_posts ?? g.available_counts?.reach)} /{" "}
                    {fmtNum(g.missing_counts?.reach)}
                  </td>
                  <td>
                    <DeltaCell delta={cmp?.delta} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AnalysisCoverageCard({ coverage }) {
  if (!coverage) return null;
  const analysis = coverage.analysis_period || {};
  const comparison = coverage.comparison_period || {};
  const sync = coverage.meta_sync || {};
  const stories = coverage.stories || {};
  const platforms = Object.entries(coverage.posts_by_platform || {});
  const prevPlatforms = Object.entries(coverage.comparison_by_platform || {});

  return (
    <section className="card stack" aria-label="Data coverage before execute">
      <h4>Before Execute — data coverage</h4>
      <p className="hint">{coverage.execute_note}</p>
      <ul className="plain-list">
        <li>
          Analysis period:{" "}
          <strong>{analysis.label || `${analysis.start || "—"} → ${analysis.end || "—"}`}</strong>
        </li>
        <li>
          Comparison period:{" "}
          <strong>
            {comparison.label || `${comparison.start || "—"} → ${comparison.end || "—"}`}
          </strong>
        </li>
        <li>
          Posts in analysis: <strong>{coverage.posts_in_analysis ?? 0}</strong>
          {platforms.length
            ? ` (${platforms.map(([name, count]) => `${name} ${count}`).join(" · ")})`
            : ""}
        </li>
        <li>
          Posts in comparison: <strong>{coverage.posts_in_comparison ?? 0}</strong>
          {prevPlatforms.length
            ? ` (${prevPlatforms.map(([name, count]) => `${name} ${count}`).join(" · ")})`
            : ""}
        </li>
        <li>
          Stories:{" "}
          {stories.present
            ? `${stories.count} available`
            : stories.missing_reason || "missing for this period"}
        </li>
      </ul>
      {(coverage.missing_layers || []).length ? (
        <>
          <h5 style={{ margin: 0 }}>Missing / incomplete for this run</h5>
          <ul className="plain-list">
            {coverage.missing_layers.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      <p className={sync.coverage_uncertain ? "banner warn-soft" : "banner"}>
        <strong>Meta sync coverage:</strong>{" "}
        {sync.coverage_proven_complete
          ? "Marked complete."
          : "Not proven complete for this analysis window."}{" "}
        {sync.coverage_note}
      </p>
      {sync.last_at ? (
        <p className="hint">
          Last Synchronise Meta: {sync.last_status || "—"} · {sync.last_at}
          {sync.last_fetch_instagram != null || sync.last_fetch_facebook != null
            ? ` · IG ${sync.last_fetch_instagram ?? "—"} / FB ${sync.last_fetch_facebook ?? "—"}`
            : ""}
        </p>
      ) : (
        <p className="hint">No Synchronise Meta run recorded yet.</p>
      )}
      <p className="hint">{coverage.linkedin_note}</p>
      <p className="hint">
        <strong>If coverage is uncertain:</strong> {sync.action}
      </p>
      <p className="hint">
        Where Maaike can check: {(coverage.where_maaike_can_verify || []).join(" · ")}
      </p>
    </section>
  );
}

function ClientReportInspectView({ data }) {
  const period = data.period || {};
  const comparison = data.comparison || {};
  const metrics = data.metrics || {};
  const prompt = data.prompt_input || {};
  const strategy = prompt.strategy || {};
  const legend = prompt.format_legend || {};

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="banner">{data.ai_analysis_banner}</p>

      <AnalysisCoverageCard coverage={data.data_coverage} />

      <h4>Periods</h4>
      <ul className="plain-list">
        <li>
          Primary: <strong>{period.label || `${period.start} to ${period.end}`}</strong> (
          {period.length_days} days
          {period.mode === "calendar_month"
            ? ` · report month ${period.year}-${String(period.month).padStart(2, "0")}`
            : " · custom period"}
          )
        </li>
        <li>
          Comparison: <strong>{period.compare_label || `${period.previous_start} to ${period.previous_end}`}</strong>{" "}
          ({period.compare_length_days} days ·{" "}
          {period.compare_mode === "previous_equal_length"
            ? `default: previous ${period.compare_length_days || period.length_days || "?"} days (not the previous calendar month)`
            : "manual"}
          {period.lengths_equal ? "" : " · note: lengths differ"})
        </li>
      </ul>

      <MetricTotalsTable metrics={metrics} title="Posts — totals & averages (current period)" />
      {metrics.by_platform && Object.keys(metrics.by_platform).length ? (
        <p className="banner">
          Platforms in this report:{" "}
          {Object.entries(metrics.by_platform)
            .map(([name, count]) => `${name} ${count}`)
            .join(" · ")}
          . My Social Feeds only includes Instagram/Facebook; LinkedIn is counted here if it is in
          the period.
        </p>
      ) : null}

      <h4>Change vs comparison period ({comparison.metric || "reach"})</h4>
      <p className="hint">{comparison.note}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>Now</th>
              <th>Previous</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Post count</td>
              <td>{fmtNum(comparison.current_post_count)}</td>
              <td>{fmtNum(comparison.previous_post_count)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.post_count} />
              </td>
            </tr>
            <tr>
              <td>Sum {comparison.metric || "reach"}</td>
              <td>{fmtNum(comparison.current?.sum)}</td>
              <td>{fmtNum(comparison.previous?.sum)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.sum} />
              </td>
            </tr>
            <tr>
              <td>Average {comparison.metric || "reach"} (known)</td>
              <td>{fmtNum(comparison.current?.average_over_known)}</td>
              <td>{fmtNum(comparison.previous?.average_over_known)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.average_over_known} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <GroupTable
        title="Formats"
        groups={metrics.by_format}
        compareRows={comparison.by_format}
        unclassified={metrics.unclassified?.format}
      />
      <GroupTable
        title="Content pillars"
        groups={metrics.by_pillar}
        compareRows={comparison.by_pillar}
        unclassified={metrics.unclassified?.pillar}
      />
      <GroupTable
        title="Hooks"
        groups={metrics.by_hook}
        compareRows={comparison.by_hook}
        unclassified={metrics.unclassified?.hook}
      />

      {(metrics.caveats || []).length ? (
        <ul className="plain-list">
          {metrics.caveats.map((c) => (
            <li key={c} className="hint">
              {c}
            </li>
          ))}
        </ul>
      ) : null}

      {(data.missing || []).length ? (
        <>
          <h4>Missing / attention</h4>
          <ul className="plain-list">
            {data.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </>
      ) : null}

      <h4>Review view — input for Maaike&apos;s prompt</h4>
      <p className="hint">{prompt.note}</p>
      <div className="table-wrap">
        <table>
          <tbody>
            <tr>
              <th>Strategy present</th>
              <td>
                {(strategy.start_answers && Object.keys(strategy.start_answers).length) ||
                (strategy.strategy_fields && Object.keys(strategy.strategy_fields).length)
                  ? `yes · ${Object.keys(strategy.start_answers || {}).length} start answers · ${
                      (strategy.targets || []).length
                    } targets`
                  : "mostly empty"}
              </td>
            </tr>
            <tr>
              <th>Format legend</th>
              <td>
                {(legend.formats || []).length} formats · {(legend.pillars || []).length} pillars ·{" "}
                {(legend.hooks || []).length} hooks
              </td>
            </tr>
            <tr>
              <th>Post data</th>
              <td>{fmtNum(prompt.post_data?.count)} posts in period (details in aggregation above)</td>
            </tr>
            <tr>
              <th>Periods</th>
              <td>
                {period.label} vs {period.compare_label}
              </td>
            </tr>
            <tr>
              <th>Trend report</th>
              <td>
                {data.linked_trend
                  ? `#${data.linked_trend.id} v${data.linked_trend.version} · ${
                      STATUS_LABEL[data.linked_trend.status] || data.linked_trend.status
                    }${
                      data.linked_trend.is_mock
                        ? " · MOCK sample"
                        : data.linked_trend.status === "prepared" && !data.linked_trend.body_present
                          ? " · no sources/run yet (empty preparation)"
                          : ""
                    }`
                  : "not linked"}
              </td>
            </tr>
            <tr>
              <th>AI analysis</th>
              <td>
                {(() => {
                  const attached =
                    prompt.attached_ai_analysis_ids ||
                    prompt.post_data?.attached_ai_analyses?.analysis_ids ||
                    data.available?.completed_analysis_ids ||
                    [];
                  if (prompt.ai_analysis_executed || attached.length) {
                    return `attached · ids ${attached.length ? attached.join(", ") : "yes"}`;
                  }
                  if (prompt.ai_analysis_status && prompt.ai_analysis_status !== "not_executed") {
                    return prompt.ai_analysis_status;
                  }
                  return "no completed post analyses attached";
                })()}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {(legend.formats || []).length ? (
        <details>
          <summary className="hint">Show format legend</summary>
          <ul className="plain-list">
            {legend.formats.map((f) => (
              <li key={f.id}>
                {f.name}
                {f.explanation ? ` — ${f.explanation}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {strategy.start_answers && Object.keys(strategy.start_answers).length ? (
        <details>
          <summary className="hint">Show strategy start answers</summary>
          <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(strategy.start_answers, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

function monthLabelEn(year, month) {
  const names = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];
  if (year && month && month >= 1 && month <= 12) return `${names[month]} ${year}`;
  return null;
}

function statusLineEn(review, presentation, badge) {
  if (review?.is_approved || presentation?.status?.approved) {
    return "Goedgekeurd";
  }
  if (presentation?.status?.code === "prepared" || badge?.code === "prepared") {
    return "Voorbereid — nog geen concept";
  }
  if (badge?.code === "failed" || badge?.code === "generation_failed") {
    return "Mislukt — niet goedkeurbaar";
  }
  if (presentation?.status?.partial || badge?.code === "partial_concept") {
    return "Concept — nog niet goedgekeurd";
  }
  return "Concept — nog niet goedgekeurd";
}

function ReportSectionEditor({
  section,
  reviewItem,
  canEdit,
  busy,
  editorName,
  onSaved,
  onError,
  onBusy,
  onDirtyChange,
  clientId,
  reportId,
  allItems,
}) {
  const initialFeedback = reviewItem?.feedback || section.feedback || "";
  const initialText =
    (reviewItem?.edited_text && String(reviewItem.edited_text).trim()) ||
    section.text ||
    section.ai_text ||
    "";
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState(initialFeedback);
  const [editText, setEditText] = useState(initialText);
  const dirty = open && (feedback !== initialFeedback || editText !== initialText);

  useEffect(() => {
    onDirtyChange?.(section.review_key, dirty);
    return () => onDirtyChange?.(section.review_key, false);
  }, [dirty, section.review_key]);

  useEffect(() => {
    if (!open) {
      setFeedback(reviewItem?.feedback || section.feedback || "");
      setEditText(
        (reviewItem?.edited_text && String(reviewItem.edited_text).trim()) ||
          section.text ||
          section.ai_text ||
          ""
      );
    }
  }, [
    open,
    section.review_key,
    reviewItem?.feedback,
    reviewItem?.edited_text,
    section.text,
    section.ai_text,
    section.feedback,
  ]);

  function closeEditor() {
    if (dirty) {
      const ok = window.confirm("Discard unsaved changes for this section?");
      if (!ok) return;
    }
    setOpen(false);
  }

  function save() {
    const key = section.review_key;
    const nextItems = (allItems || []).map((item) => {
      if (item.key !== key) return item;
      return {
        ...item,
        feedback,
        edited_text: editText,
        edited_by: editorName || item.edited_by || "",
        human_text: item.human_text || "",
        decision: item.decision || "",
      };
    });
    const hasKey = nextItems.some((item) => item.key === key);
    const payloadItems = hasKey
      ? nextItems
      : [
          ...nextItems,
          {
            key,
            label: section.label_nl || section.label_en || key,
            ai_text: section.ai_text || "",
            feedback,
            edited_text: editText,
            edited_by: editorName || "",
            decision: key === "addition.staff" ? "add" : "",
            human_text: "",
          },
        ];

    onBusy(true);
    onError("");
    api(`/api/clients/${clientId}/reports/${reportId}/review`, {
      method: "POST",
      body: {
        reviewer_name: editorName || "",
        edited_by: editorName || "",
        item_feedback: payloadItems,
        compose_final_from_items: true,
      },
    })
      .then((payload) => {
        onSaved(payload, `Opgeslagen — “${section.label_nl || section.label_en}”.`);
        setOpen(false);
      })
      .catch((exc) => onError(exc.message))
      .finally(() => onBusy(false));
  }

  const listItems = section.is_edited ? [] : section.items_display || section.items || [];
  const displayText = listItems.length
    ? null
    : section.text_display || section.text || "";

  return (
    <article className="report-doc-section" data-review-key={section.review_key}>
      <header className="report-doc-section-head">
        <h4>{section.label_nl || section.label_en}</h4>
        {canEdit ? (
          <button
            type="button"
            className="report-edit-btn"
            disabled={busy}
            onClick={() => (open ? closeEditor() : setOpen(true))}
            aria-label="Bewerken"
            aria-expanded={open}
            title="Bewerken"
          >
            <PencilIcon />
            <span className="report-edit-btn-label">Bewerken</span>
          </button>
        ) : null}
      </header>

      {listItems.length ? (
        <ul className="plain-list report-doc-body">
          {listItems.map((entry) => (
            <li key={entry}>{entry}</li>
          ))}
        </ul>
      ) : (
        <p className="report-doc-body" style={{ whiteSpace: "pre-wrap" }}>
          {displayText || "—"}
        </p>
      )}

      {section.is_edited && section.edited_by ? (
        <p className="report-edited-by">Edited by {section.edited_by}</p>
      ) : null}

      {open ? (
        <div className="report-inline-editor stack">
          {dirty ? <p className="hint report-unsaved">Unsaved changes</p> : null}
          <label>
            Your feedback
            <textarea
              rows={3}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Optional internal notes (not in the client PDF)"
            />
          </label>
          <label>
            Report text
            <textarea
              rows={8}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              placeholder="Edit the report text, or leave as-is and only save feedback"
            />
          </label>
          <div className="row-actions wrap">
            <button className="primary" type="button" disabled={busy} onClick={save}>
              Opslaan
            </button>
            <button className="secondary" type="button" disabled={busy} onClick={closeEditor}>
              Annuleren
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function ReportPanelFigures({ presentation, onClose }) {
  const rows = presentation?.key_metrics || [];
  return (
    <aside className="report-side-panel stack" aria-label="All figures">
      <div className="report-side-panel-head">
        <h3>All figures</h3>
        <button type="button" className="secondary" onClick={onClose}>
          Back to report
        </button>
      </div>
      {rows.length ? (
        <table className="report-metrics-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hint">No additional figures available.</p>
      )}
    </aside>
  );
}

function ReportPanelNotes({
  presentation,
  review,
  canReview,
  busy,
  editorName,
  clientId,
  reportId,
  setBusy,
  setError,
  setDetail,
  setNotice,
  reloadList,
  onClose,
}) {
  const attention = presentation?.review_attention_points || [];
  const missing = [
    ...(presentation?.missing_data || []),
    ...(presentation?.missing_sources || []),
  ];
  const acks = review.warning_acknowledgements || [];
  const ackMap = Object.fromEntries(
    (acks || []).filter((a) => a && a.key).map((a) => [a.key, a])
  );

  function sectionLabelFor(point) {
    const loc = String(point.location_nl || point.location || "");
    return loc || "Report";
  }

  function saveAcks(nextAcks, message) {
    setBusy(true);
    setError("");
    api(`/api/clients/${clientId}/reports/${reportId}/review`, {
      method: "POST",
      body: {
        reviewer_name: editorName || review.reviewer_name || "",
        item_feedback: review.item_feedback || [],
        warning_acknowledgements: nextAcks,
        compose_final_from_items: true,
      },
    })
      .then(async (payload) => {
        setDetail(payload);
        await reloadList();
        setNotice(message);
      })
      .catch((exc) => setError(exc.message))
      .finally(() => setBusy(false));
  }

  function handlePoint(point, status) {
    const key = `${point.kind}|${point.location || ""}|${String(point.note || "").slice(0, 120)}`;
    let note = "";
    if (status === "accepted") {
      note = window.prompt("Short note: why is this acceptable for approval?") || "";
      note = note.trim();
      if (!note) {
        setError("A note is required when accepting a review point.");
        return;
      }
    }
    const entry = {
      key,
      status,
      note,
      kind: point.kind,
      location: point.location || "",
      at: new Date().toISOString(),
      by: editorName || review.reviewer_name || "",
    };
    const next = [...(acks || []).filter((a) => a.key !== key), entry];
    saveAcks(
      next,
      status === "accepted" ? "Review point accepted with note." : "Review point marked as addressed."
    );
  }

  const editedItems = (review.item_feedback || []).filter(
    (item) =>
      String(item.edited_text || "").trim() &&
      String(item.edited_text || "").trim() !== String(item.ai_text || "").trim()
  );

  return (
    <aside className="report-side-panel stack" aria-label="Review notes">
      <div className="report-side-panel-head">
        <h3>Review notes</h3>
        <button type="button" className="secondary" onClick={onClose}>
          Back to report
        </button>
      </div>
      <p className="hint">
        Missing data and content warnings live here — not inside the readable report. Handle open
        points before approval.
      </p>

      {missing.length ? (
        <section className="stack">
          <h4>Missing data</h4>
          <ul className="plain-list">
            {missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="stack">
        <h4>Content warnings</h4>
        {attention.length ? (
          attention.map((point) => {
            const key = `${point.kind}|${point.location || ""}|${String(point.note || "").slice(0, 120)}`;
            const ack = ackMap[key];
            return (
              <div className="report-note-item" key={key}>
                <p className="report-note-section">{sectionLabelFor(point)}</p>
                <p>
                  <strong>{point.kind_nl || point.label_nl || point.kind}</strong>
                  {point.note ? ` — ${point.note}` : ""}
                </p>
                {ack ? (
                  <p className="hint">
                    {ack.status === "accepted" ? "Accepted" : "Addressed"}
                    {ack.by ? ` by ${ack.by}` : ""}
                    {ack.note ? `: ${ack.note}` : ""}
                  </p>
                ) : canReview && !review.is_approved ? (
                  <div className="row-actions wrap">
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => handlePoint(point, "addressed")}
                    >
                      Mark addressed
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => handlePoint(point, "accepted")}
                    >
                      Accept with note
                    </button>
                  </div>
                ) : (
                  <p className="hint">Open</p>
                )}
              </div>
            );
          })
        ) : (
          <p className="hint">No content warnings on this draft.</p>
        )}
      </section>

      <section className="stack">
        <h4>Original AI text &amp; edits</h4>
        {(review.item_feedback || [])
          .filter((item) => item.key !== "action_plan.human_approval")
          .map((item) => {
            const changed =
              String(item.edited_text || "").trim() &&
              String(item.edited_text || "").trim() !== String(item.ai_text || "").trim();
            if (!item.ai_text && !changed && !String(item.feedback || "").trim()) return null;
            return (
              <div className="report-note-item" key={item.key}>
                <p className="report-note-section">{item.label}</p>
                {String(item.feedback || "").trim() ? (
                  <p className="hint">Feedback: {item.feedback}</p>
                ) : null}
                {changed ? (
                  <>
                    <p className="hint">Current text</p>
                    <p className="report-doc-body">{item.edited_text}</p>
                    <p className="hint">AI original</p>
                    <p className="report-doc-body">{item.ai_text || "—"}</p>
                  </>
                ) : item.ai_text ? (
                  <>
                    <p className="hint">AI original (unchanged)</p>
                    <p className="report-doc-body">{item.ai_text}</p>
                  </>
                ) : null}
              </div>
            );
          })}
        {!editedItems.length ? (
          <p className="hint">No text edits saved yet. AI originals remain available above.</p>
        ) : null}
      </section>

      {(review.previous_approved || []).length ? (
        <section className="stack">
          <h4>Previous approvals</h4>
          <ul className="plain-list">
            {(review.previous_approved || []).map((prev, idx) => (
              <li key={`${prev.approved_at}-${idx}`}>
                {prev.reviewer_name || "—"} · {prev.approved_at || "—"}
                {prev.superseded_at ? ` · superseded ${prev.superseded_at}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </aside>
  );
}

function ReportPanelAdmin({
  report,
  review,
  presentation,
  snap,
  estimate,
  busy,
  setBusy,
  setError,
  setDetail,
  setNotice,
  reloadList,
  mockScenario,
  setMockScenario,
  maxBudget,
  preview,
  setPreview,
  sourceTitle,
  setSourceTitle,
  sourceUrl,
  setSourceUrl,
  sourcePublished,
  setSourcePublished,
  sourceExcerpt,
  setSourceExcerpt,
  clientId,
  onClose,
}) {
  const done =
    ["completed", "mock_completed", "running", "failed"].includes(report.status) && report.executed_at;
  const isClient = report.report_type === "client";

  return (
    <aside className="report-side-panel stack" aria-label="Technische details">
      <div className="report-side-panel-head">
        <h3>Technische details</h3>
        <button type="button" className="secondary" onClick={onClose}>
          Terug naar rapport
        </button>
      </div>
      <p className="hint">Technische controles en dumps. Dit opent geen AI-aanroep.</p>
      {review.execution_key ? (
        <p className="hint">
          Execution key: <code>{review.execution_key}</code>
        </p>
      ) : null}

      <div className="row-actions wrap">
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError("");
            const q =
              maxBudget === "" ? "" : `?max_budget_usd=${encodeURIComponent(maxBudget)}`;
            api(`/api/clients/${clientId}/reports/${report.id}/execution-preview${q}`)
              .then((payload) => {
                setPreview(payload);
                setNotice("Execution preview loaded (no paid call).");
              })
              .catch((exc) => setError(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Show execution preview
        </button>
        <label>
          Mock scenario
          <select value={mockScenario} onChange={(e) => setMockScenario(e.target.value)}>
            {MOCK_SCENARIOS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          type="button"
          disabled={busy || done}
          onClick={() => {
            setBusy(true);
            setError("");
            api(`/api/clients/${clientId}/reports/${report.id}/mock`, {
              method: "POST",
              body: { scenario: mockScenario },
            })
              .then(async (payload) => {
                setDetail(payload);
                await reloadList();
                setNotice(`Mock scenario “${mockScenario}” saved (no paid request).`);
              })
              .catch((exc) => setError(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Run mock
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy || done}
          onClick={() => {
            setBusy(true);
            setError("");
            api(`/api/clients/${clientId}/reports/${report.id}/execute`, {
              method: "POST",
              body: {
                dry_run_paid: true,
                max_budget_usd: maxBudget === "" ? null : Number(maxBudget),
              },
            })
              .then(() => setNotice("Unexpected: dry-run should have blocked."))
              .catch((exc) => setNotice(`Paid execute blocked (expected): ${exc.message}`))
              .finally(() => setBusy(false));
          }}
        >
          Execute (dry-run — blocks paid)
        </button>
      </div>

      {preview ? (
        <div className="stack">
          <h4>Execution preview (no paid call)</h4>
          <AnalysisCoverageCard coverage={preview.data_coverage} />
          <ul className="plain-list">
            <li>Paid call: {String(preview.paid_call)}</li>
            <li>
              Budget gate: {preview.within_budget ? "within" : "over"} (max{" "}
              {preview.max_budget_usd != null ? `USD ${preview.max_budget_usd}` : "—"})
            </li>
            <li>
              Prompt chars: {preview.prompt_package?.system_chars ?? preview.data_to_provider?.system_instruction_chars ?? "—"}
            </li>
            <li>
              Sources read:{" "}
              {(preview.sources_read || []).filter((s) => s.counted_as_read_source).length}/
              {(preview.sources_read || []).length}
            </li>
            <li>Search enabled: {String(preview.enable_google_search)}</li>
          </ul>
          {preview.prompt_package?.missing_source_layers?.length ? (
            <p className="hint">
              Missing source layers: {preview.prompt_package.missing_source_layers.join(", ")}
            </p>
          ) : null}
          <details>
            <summary>Full preview JSON</summary>
            <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(preview, null, 2)}
            </pre>
          </details>
        </div>
      ) : null}

      <h4>Cost estimate</h4>
      <ul className="plain-list">
        <li>
          Provider/model: {estimate.provider || "—"} / {estimate.exact_model || report.model || "—"}
        </li>
        <li>Token estimate: {money(estimate.estimated_cost_usd)}</li>
        <li>
          Combined high:{" "}
          {estimate.combined_high_usd != null ? `USD ${estimate.combined_high_usd}` : "unknown"}
        </li>
      </ul>

      {report.report_type === "trend" && report.status === "prepared" && snap.research_mode !== "internet" ? (
        <div className="stack">
          <h4>Add source</h4>
          <label>
            Title
            <input value={sourceTitle} onChange={(e) => setSourceTitle(e.target.value)} />
          </label>
          <label>
            URL
            <input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
          </label>
          <label>
            Publication date
            <input
              value={sourcePublished}
              onChange={(e) => setSourcePublished(e.target.value)}
              placeholder="YYYY-MM-DD"
            />
          </label>
          <label>
            Excerpt
            <textarea rows={3} value={sourceExcerpt} onChange={(e) => setSourceExcerpt(e.target.value)} />
          </label>
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError("");
              api(`/api/clients/${clientId}/reports/${report.id}/sources`, {
                method: "POST",
                body: {
                  fetch_content: true,
                  sources: [
                    {
                      title: sourceTitle,
                      url: sourceUrl,
                      published_at: sourcePublished,
                      excerpt: sourceExcerpt,
                    },
                  ],
                },
              })
                .then(async (payload) => {
                  setDetail(payload);
                  await reloadList();
                  setSourceTitle("");
                  setSourceUrl("");
                  setSourcePublished("");
                  setSourceExcerpt("");
                  const summary = payload?.report?.input_snapshot?.source_read_summary;
                  setNotice(
                    summary
                      ? `Source saved via HTTP fetch (no AI). Read ${summary.read}/${summary.total}.`
                      : "Source saved via HTTP fetch (no AI)."
                  );
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Save + fetch source (no AI)
          </button>
        </div>
      ) : null}

      {isClient ? (
        <ClientReportInspectView
          data={{
            ai_analysis_banner:
              presentation?.ai_analysis_banner?.label_en ||
              snap.ai_analysis_banner ||
              "No completed post AI analyses attached for this period yet.",
            period: snap.period,
            metrics: snap.metrics,
            comparison: snap.comparison,
            missing: snap.missing,
            available: snap.available,
            linked_trend: snap.linked_trend,
            prompt_input: snap.prompt_input || {
              strategy: {
                start_answers: Object.fromEntries(
                  (snap.strategy_summary?.start_answer_keys || []).map((k) => [k, "(saved)"])
                ),
                targets: snap.strategy_summary?.targets || [],
              },
              format_legend: { formats: [], pillars: [], hooks: [] },
              post_data: { count: snap.metrics?.post_count },
              note: "Prompt input from saved snapshot.",
            },
          }}
        />
      ) : null}

      <h4>Raw result JSON</h4>
      <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
        {JSON.stringify(report.body || {}, null, 2)}
      </pre>
    </aside>
  );
}

function ReportDetail({
  clientId,
  detail,
  busy,
  setBusy,
  setDetail,
  setError,
  setNotice,
  reloadList,
  sourceTitle,
  setSourceTitle,
  sourceUrl,
  setSourceUrl,
  sourcePublished,
  setSourcePublished,
  sourceExcerpt,
  setSourceExcerpt,
  mockScenario,
  setMockScenario,
  maxBudget,
  preview,
  setPreview,
  onClose,
}) {
  const report = detail.report;
  const review = detail.review || {};
  const presentation = detail.presentation || null;
  const snap = report.input_snapshot || {};
  const estimate = report.estimate || {};
  const isClient = report.report_type === "client";
  const badge = resolveReportBadge(
    {
      ...report,
      is_approved: review.is_approved || report.is_approved,
      review_status: review.review_status || report.review_status,
      review_status_label: review.review_status_label || report.review_status_label,
      can_review: review.can_review,
      is_partial: presentation?.status?.partial || report.is_partial,
    },
    presentation
  );

  const [editorName, setEditorName] = useState(review.reviewer_name || "");
  const [panel, setPanel] = useState(null);
  const [dirtyKeys, setDirtyKeys] = useState({});
  const [editTitle, setEditTitle] = useState(
    displayReportTitle(report, presentation?.client_name || "Klant")
  );

  useEffect(() => {
    setEditorName(review.reviewer_name || "");
    setPanel(null);
    setDirtyKeys({});
    setEditTitle(displayReportTitle(report, presentation?.client_name || "Klant"));
  }, [report.id, report.title, review.reviewer_name, review.record?.updated_at, presentation?.client_name]);

  const attention = presentation?.review_attention_points || [];
  const reviewPointCount = attention.length;
  const canReview = Boolean(review.can_review);
  const sections = presentation?.document_sections || [];
  const analysisSections = sections.filter((s) => s.group === "analysis");
  const chapterSections = sections.filter((s) => s.group === "chapters");
  const actionSections = sections.filter((s) => s.group === "action_plan");
  const additionSections = sections.filter((s) => s.group === "addition");
  const itemsByKey = Object.fromEntries(
    (review.item_feedback || []).map((item) => [item.key, item])
  );
  const staffItem = itemsByKey["addition.staff"];
  const showStaffSlot =
    canReview && !additionSections.length && staffItem && !String(staffItem.edited_text || "").trim();

  const headline = presentation?.headline_metrics || [];
  const statusShort = statusLineEn(review, presentation, badge);
  const month =
    monthLabelEn(presentation?.period_year || report.period_year, presentation?.period_month || report.period_month) ||
    presentation?.period_label ||
    `${report.period_year}-${String(report.period_month).padStart(2, "0")}`;

  const ackMap = Object.fromEntries(
    (review.warning_acknowledgements || [])
      .filter((a) => a && a.key && ["addressed", "accepted"].includes(a.status))
      .map((a) => [a.key, a])
  );
  const openWarningCount = attention.filter((point) => {
    const key = `${point.kind}|${point.location || ""}|${String(point.note || "").slice(0, 120)}`;
    return !ackMap[key];
  }).length;

  const anyDirty = Object.values(dirtyKeys).some(Boolean);

  function onDirtyChange(key, dirty) {
    setDirtyKeys((prev) => {
      if (!!prev[key] === !!dirty) return prev;
      return { ...prev, [key]: dirty };
    });
  }

  function onSectionSaved(payload, message) {
    setDetail(payload);
    reloadList();
    setNotice(message);
  }

  function tryClose() {
    if (anyDirty) {
      const ok = window.confirm("You have unsaved edits. Close anyway?");
      if (!ok) return;
    }
    onClose();
  }

  function approveReport() {
    if (!canReview || review.is_approved) return;
    if (anyDirty) {
      setError("Save or cancel open edits before approving.");
      return;
    }
    if (openWarningCount > 0) {
      setPanel("notes");
      setError(
        `${openWarningCount} review point${openWarningCount === 1 ? "" : "s"} still open. Address or accept each in Review notes before approval.`
      );
      return;
    }
    let name = String(editorName || "").trim();
    if (!name) {
      name = window.prompt("Jouw naam (wordt bij deze goedkeuring bewaard):") || "";
      name = name.trim();
      if (!name) {
        setError("Vul je naam in om het rapport goed te keuren.");
        return;
      }
      setEditorName(name);
    }
    const ok = window.confirm(
      `Rapport #${report.id} goedkeuren?\n\nAlleen deze bevestiging zet de status op Goedgekeurd.`
    );
    if (!ok) return;
    setBusy(true);
    setError("");
    api(`/api/clients/${clientId}/reports/${report.id}/review`, {
      method: "POST",
      body: {
        reviewer_name: name,
        item_feedback: review.item_feedback || [],
        warning_acknowledgements: review.warning_acknowledgements || [],
        compose_final_from_items: true,
        approve: true,
      },
    })
      .then(async (payload) => {
        setDetail(payload);
        await reloadList();
        setNotice(`Report #${report.id} approved by ${name}.`);
        setAskName(false);
      })
      .catch((exc) => setError(exc.message))
      .finally(() => setBusy(false));
  }

  const sectionProps = {
    canEdit: canReview,
    busy,
    editorName,
    clientId,
    reportId: report.id,
    allItems: review.item_feedback || [],
    onBusy: setBusy,
    onError: setError,
    onSaved: onSectionSaved,
    onDirtyChange,
  };

  return (
    <section className="card stack report-readable report-detail report-document report-document-v2">
      <header className="report-hero report-hero-calm">
        <div className="report-hero-top">
          <div>
            <p className="hint" style={{ margin: "0 0 0.35rem" }}>
              {reportTypeLabel(report.report_type)} · periode {periodLabel(report)}
            </p>
            <div className="report-title-edit">
              <label>
                {isClient ? "Klantrapportnaam" : "Trendrapportnaam"}
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  disabled={busy}
                  placeholder={
                    isClient ? "Bijv. Red Rock – analyse september 2026" : "Bijv. Social trends – planning november 2026"
                  }
                />
              </label>
              <div className="row-actions wrap">
                <button
                  className="secondary"
                  type="button"
                  disabled={busy || !editTitle.trim() || editTitle.trim() === report.title}
                  onClick={() => {
                    setBusy(true);
                    setError("");
                    api(`/api/clients/${clientId}/reports/${report.id}/title`, {
                      method: "PATCH",
                      body: { title: editTitle.trim() },
                    })
                      .then(async (payload) => {
                        setDetail(payload);
                        await reloadList();
                        setNotice("Rapportnaam opgeslagen.");
                      })
                      .catch((exc) => setError(exc.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Naam opslaan
                </button>
                <span className="hint">#{report.id} staat in Details</span>
              </div>
            </div>
            <p className="report-hero-meta">
              <strong>{presentation?.client_name || "Klant"}</strong>
              <span aria-hidden="true"> · </span>
              {month}
              <span aria-hidden="true"> · </span>
              Vergelijking {presentation?.compare_label || "—"}
              <span aria-hidden="true"> · </span>
              <span className={`report-status-badge is-${badge.code}`}>{statusShort}</span>
            </p>
            <p className="report-status-line">
              {statusShort}
              {reviewPointCount > 0
                ? ` · ${reviewPointCount} aandachtspunt${reviewPointCount === 1 ? "" : "en"}`
                : ""}
              {review.is_approved && (review.reviewer_name || editorName)
                ? ` · door ${review.reviewer_name || editorName}`
                : ""}
            </p>
            <p className="hint report-hero-actions-hint">
              {badge.code === "generation_failed" || report.status === "failed" ? (
                <>
                  Deze run is mislukt — geen concept om goed te keuren. Bekijk{" "}
                  <strong>Technische details</strong> of start een nieuwe analyse.
                  {isClient ? (
                    <>
                      {" "}
                      PDF kan metadata tonen via <strong>Download PDF</strong>.
                    </>
                  ) : null}
                </>
              ) : badge.code === "prepared" || !report.executed_at ? (
                <>
                  Dit rapport is alleen voorbereid. Start de analyse via{" "}
                  <strong>Nieuwe analyse</strong>, of bekijk de invoer onder Technische details.
                </>
              ) : (
                <>
                  Per sectie: <strong>Bewerken</strong> → <strong>Opslaan</strong>. Daarna{" "}
                  <strong>Goedkeuren</strong>
                  {isClient ? (
                    <>
                      {" "}
                      en <strong>Download PDF</strong>
                    </>
                  ) : null}
                  . Goedkeuring blijft menselijk.
                </>
              )}
            </p>
          </div>
          <div className="report-hero-actions">
            {canReview && !review.is_approved ? (
              <button className="primary" type="button" disabled={busy} onClick={approveReport}>
                Goedkeuren
              </button>
            ) : null}
            {isClient ? (
              <button
                className={canReview && !review.is_approved ? "secondary" : "primary"}
                type="button"
                disabled={busy}
                onClick={() =>
                  downloadReportPdf(clientId, report.id, { setBusy, setError, setNotice })
                }
              >
                Download PDF
              </button>
            ) : null}
            <button className="secondary" type="button" onClick={tryClose}>
              Terug naar lijst
            </button>
          </div>
        </div>
        <div className="report-hero-links row-actions wrap">
          <button type="button" className="linkish" onClick={() => setPanel("figures")}>
            Alle cijfers
          </button>
          <button type="button" className="linkish" onClick={() => setPanel("notes")}>
            Notities &amp; aandachtspunten
            {openWarningCount > 0 ? ` (${openWarningCount} open)` : ""}
          </button>
          <button type="button" className="linkish" onClick={() => setPanel("admin")}>
            Technische details
          </button>
        </div>
      </header>

      {report.status === "failed" ? (
        <div className="banner error stack">
          <strong>Generation failed</strong>
          <p>
            {(report.body?.generation_failure?.friendly_reason ||
              (String(report.error_text || "").toLowerCase().includes("high demand")
                ? "The Gemini model was temporarily unavailable due to high demand on Google's side. This is not an API-key, quota, or prompt error."
                : report.error_text) ||
              "No draft text was produced. Only metadata and sources are available for inspection.")}
          </p>
          <p className="hint">
            Only metadata and sources are available for inspection — no draft text.
            {report.body?.generation_failure?.http_status
              ? ` HTTP ${report.body.generation_failure.http_status}`
              : ""}
            {report.body?.generation_failure?.error_status
              ? ` · ${report.body.generation_failure.error_status}`
              : ""}
            {report.model ? ` · model ${report.model}` : ""}
          </p>
        </div>
      ) : null}

      {anyDirty ? <p className="banner warn-soft">You have unsaved section edits.</p> : null}

      {panel === "figures" ? (
        <ReportPanelFigures presentation={presentation} onClose={() => setPanel(null)} />
      ) : null}
      {panel === "notes" ? (
        <ReportPanelNotes
          presentation={presentation}
          review={review}
          canReview={canReview}
          busy={busy}
          editorName={editorName}
          clientId={clientId}
          reportId={report.id}
          setBusy={setBusy}
          setError={setError}
          setDetail={setDetail}
          setNotice={setNotice}
          reloadList={reloadList}
          onClose={() => setPanel(null)}
        />
      ) : null}
      {panel === "admin" ? (
        <ReportPanelAdmin
          report={report}
          review={review}
          presentation={presentation}
          snap={snap}
          estimate={estimate}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          setDetail={setDetail}
          setNotice={setNotice}
          reloadList={reloadList}
          mockScenario={mockScenario}
          setMockScenario={setMockScenario}
          maxBudget={maxBudget}
          preview={preview}
          setPreview={setPreview}
          sourceTitle={sourceTitle}
          setSourceTitle={setSourceTitle}
          sourceUrl={sourceUrl}
          setSourceUrl={setSourceUrl}
          sourcePublished={sourcePublished}
          setSourcePublished={setSourcePublished}
          sourceExcerpt={sourceExcerpt}
          setSourceExcerpt={setSourceExcerpt}
          clientId={clientId}
          onClose={() => setPanel(null)}
        />
      ) : null}

      {panel ? null : (
        <div className="report-doc">
          {!presentation?.has_readable_content && !sections.length ? (
            <p className="banner">
              {report.status === "prepared" || !report.executed_at
                ? "Prepared only — no AI draft yet. This report cannot be approved."
                : report.status === "failed"
                  ? "Generation failed — no draft text. Open Admin or sources to inspect metadata only."
                  : report.error_text || "No readable draft available."}
            </p>
          ) : null}

          {headline.length ? (
            <div className="report-headline-metrics">
              {headline.map((row) => (
                <div className="report-headline-metric" key={row.key || row.label}>
                  <p className="report-metric-label">{row.label}</p>
                  <p className="report-metric-value">{row.value}</p>
                </div>
              ))}
            </div>
          ) : null}

          {presentation?.show_summary && presentation?.summary ? (
            <section className="report-doc-block">
              <h3>Samenvatting</h3>
              <p className="report-doc-body">{presentation.summary}</p>
            </section>
          ) : null}

          {analysisSections.length ? (
            <section className="report-doc-block">
              <h3>Analyse</h3>
              {analysisSections.map((section) => (
                <ReportSectionEditor
                  key={section.review_key}
                  section={section}
                  reviewItem={itemsByKey[section.review_key]}
                  {...sectionProps}
                />
              ))}
            </section>
          ) : null}

          {chapterSections.length ? (
            <section className="report-doc-block">
              <h3>Aanvullende hoofdstukken</h3>
              {chapterSections.map((section) => (
                <ReportSectionEditor
                  key={section.review_key}
                  section={section}
                  reviewItem={itemsByKey[section.review_key]}
                  {...sectionProps}
                />
              ))}
            </section>
          ) : null}

          {actionSections.length ? (
            <section className="report-doc-block">
              <h3>Actieplan</h3>
              {actionSections.map((section) => (
                <ReportSectionEditor
                  key={section.review_key}
                  section={section}
                  reviewItem={itemsByKey[section.review_key]}
                  {...sectionProps}
                />
              ))}
            </section>
          ) : null}

          {additionSections.map((section) => (
            <ReportSectionEditor
              key={section.review_key}
              section={section}
              reviewItem={itemsByKey[section.review_key]}
              {...sectionProps}
            />
          ))}

          {showStaffSlot ? (
            <ReportSectionEditor
              section={{
                review_key: "addition.staff",
                label_en: "Staff addition",
                label_nl: "Eigen aanvulling",
                text: "",
                ai_text: "",
                is_edited: false,
                warnings: [],
              }}
              reviewItem={staffItem}
              {...sectionProps}
            />
          ) : null}

          <div className="report-approve-bar stack">
            {canReview ? (
              <>
                {review.is_approved ? (
                  <p className="banner">
                    Approved. Editing any section returns this report to draft and keeps the previous
                    approval on file.
                  </p>
                ) : (
                  <>
                    {openWarningCount > 0 ? (
                      <p className="hint">
                        {openWarningCount} review point{openWarningCount === 1 ? "" : "s"} still open —
                        handle them in{" "}
                        <button type="button" className="linkish" onClick={() => setPanel("notes")}>
                          Review notes
                        </button>{" "}
                        before approval.
                      </p>
                    ) : null}
                    <button className="primary" type="button" disabled={busy} onClick={approveReport}>
                      Goedkeuren
                    </button>
                  </>
                )}
              </>
            ) : (
              <p className="banner warn-soft">
                {report.status === "prepared" || !report.executed_at
                  ? "Prepared or unused report — not approvable until a usable AI run exists."
                  : report.status === "failed"
                    ? "Generation failed — not approvable. Inspect metadata and sources only."
                    : "This report cannot be approved."}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
