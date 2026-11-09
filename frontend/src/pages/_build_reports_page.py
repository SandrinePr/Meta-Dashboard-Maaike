# Temporary builder — delete after use.
from pathlib import Path

ROOT = Path(__file__).resolve().parent
helpers = (ROOT / "_reports_helpers_snippet.jsx").read_text(encoding="utf-8")

# Read old ReportDetail technical + source sections from backup of current file
old = (ROOT / "ReportsPage.jsx").read_text(encoding="utf-8")
# Keep technical details block from old ReportDetail by extracting between details and end of ReportDetail
tech_start = old.index('<details className="report-tech-details">')
tech_end = old.index("</details>\n    </section>\n  );\n}\n\nfunction ReportReviewBlock")
tech_block = old[tech_start:tech_end + len("</details>")]

detail_and_review = r'''
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
  const done = ["completed", "mock_completed", "running", "failed"].includes(report.status) && report.executed_at;
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
  const [tab, setTab] = useState("overview");

  useEffect(() => {
    setTab(review.can_review ? "overview" : "overview");
  }, [report.id]);

  const attention = presentation?.review_attention_points || [];
  const missing = [
    ...(presentation?.missing_data || []),
    ...(presentation?.missing_sources || []),
  ];
  const showAlert = attention.length > 0 || missing.length > 0;

  return (
    <section className="card stack report-readable report-detail">
      <div className="report-hero">
        <div className="report-hero-top">
          <div>
            <p className="step-label">{isClient ? "Client report" : "Trend report"}</p>
            <h3 style={{ marginTop: 0 }}>
              {presentation?.title_en || presentation?.title_ui || presentation?.title || report.title}
            </h3>
            <p className="hint report-hero-meta">
              <strong>{presentation?.client_name || "Client"}</strong>
              {" · "}
              Period {presentation?.period_label || `${report.period_year}-${String(report.period_month).padStart(2, "0")}`}
              {" · "}
              Comparison {presentation?.compare_label || "—"}
              {" · "}
              v{report.version}
              {report.is_mock ? " · MOCK" : ""}
            </p>
            <p className="report-hero-status-row">
              <span className={`report-status-badge is-${badge.code}`}>{badge.label}</span>
              <span className="hint">
                {presentation?.content_source_label_en ||
                  (review.is_approved ? "Human final version (approved)" : "AI concept — not approved")}
              </span>
            </p>
          </div>
          <div className="report-hero-actions">
            {isClient ? (
              <button
                className="primary"
                type="button"
                disabled={busy}
                onClick={() => downloadReportPdf(clientId, report.id, { setBusy, setError, setNotice })}
              >
                Download PDF
              </button>
            ) : null}
            <button className="secondary" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {showAlert ? (
          <div className={`report-alert ${badge.code === "failed" || presentation?.status?.partial ? "is-warn" : ""}`}>
            <strong>Needs attention</strong>
            <p className="hint" style={{ marginTop: "0.35rem" }}>
              Missing data and review flags from the saved report. These do not rewrite the AI draft.
            </p>
            {missing.length ? (
              <ul className="plain-list">
                {missing.map((m) => (
                  <li key={`m-${m}`}>{m}</li>
                ))}
              </ul>
            ) : null}
            {attention.length ? (
              <ul className="plain-list">
                {attention.map((point) => (
                  <li key={`${point.kind}-${point.location}-${point.note?.slice(0, 24)}`}>
                    <strong>{point.kind_nl || point.label_nl || point.kind}</strong>
                    {point.location_nl ? ` — ${point.location_nl}` : ""}: {point.note}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {report.error_text && report.status === "failed" ? (
          <p className="banner error">{report.error_text}</p>
        ) : null}
      </div>

      <div className="subnav-tabs report-detail-tabs" role="tablist" aria-label="Report sections">
        {DETAIL_TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "subnav-tab is-active" : "subnav-tab"}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="report-tab-panel">
        {tab === "overview" ? (
          <div className="stack">
            {presentation?.content_source === "approved_final" ? (
              <>
                <h4>Approved final version</h4>
                <p style={{ whiteSpace: "pre-wrap" }}>{presentation.approved_final_text}</p>
              </>
            ) : !presentation?.has_readable_content ? (
              <>
                <p className="banner">
                  {report.status === "prepared" || !report.executed_at
                    ? "Prepared only — no AI draft yet. This report cannot be approved."
                    : report.status === "failed"
                      ? report.error_text || "Failed report — no usable AI draft."
                      : report.error_text || "No readable draft available."}
                </p>
                {(presentation?.key_metrics || []).length ? (
                  <>
                    <h4>Key figures</h4>
                    <table className="report-metrics-table">
                      <thead>
                        <tr>
                          <th>Metric</th>
                          <th>Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {presentation.key_metrics.map((row) => (
                          <tr key={row.label}>
                            <td>{row.label}</td>
                            <td>{row.value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="hint">
                    {isClient
                      ? "No key figures in this saved presentation yet."
                      : "Trend overview uses technical details and sources below."}
                  </p>
                )}
              </>
            ) : (
              <>
                {presentation?.show_summary !== false && presentation?.summary ? (
                  <>
                    <h4>Short summary</h4>
                    <p>{presentation.summary}</p>
                  </>
                ) : null}
                {(presentation?.key_metrics || []).length ? (
                  <>
                    <h4>Key figures</h4>
                    <table className="report-metrics-table">
                      <thead>
                        <tr>
                          <th>Metric</th>
                          <th>Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {presentation.key_metrics.map((row) => (
                          <tr key={row.label}>
                            <td>{row.label}</td>
                            <td>{row.value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="hint">
                    {isClient
                      ? "No key figures in this saved presentation yet."
                      : "Trend overview uses technical details and sources below."}
                  </p>
                )}
              </>
            )}
          </div>
        ) : null}

        {tab === "analysis" ? (
          <div className="stack">
            {presentation?.content_source === "approved_final" ? (
              <p className="hint">This report is approved. The final text is on Overview / Human review.</p>
            ) : null}
            {(presentation?.six_answers || []).length ? (
              <>
                <h4>Six analysis questions</h4>
                {presentation.six_answers.map((item) => (
                  <div className="report-section" key={item.key}>
                    <h5>{item.label_en}</h5>
                    <p className="hint">{item.label_nl}</p>
                    <p style={{ whiteSpace: "pre-wrap" }}>{item.text_display || item.text}</p>
                  </div>
                ))}
              </>
            ) : (
              <p className="hint">No analysis answers in the saved draft.</p>
            )}
            {(presentation?.chapters || []).length ? (
              <>
                <h4>Additional chapters</h4>
                {presentation.chapters.map((item) => (
                  <div className="report-section" key={item.key}>
                    <h5>{item.label_en}</h5>
                    <p className="hint">{item.label_nl}</p>
                    <p style={{ whiteSpace: "pre-wrap" }}>{item.text_display || item.text}</p>
                  </div>
                ))}
              </>
            ) : null}
          </div>
        ) : null}

        {tab === "action" ? (
          <div className="stack">
            {(presentation?.action_plan || []).length ? (
              presentation.action_plan.map((item) => (
                <div className="report-section" key={item.key}>
                  <h5>{item.label_en}</h5>
                  {(item.items_display || item.items)?.length ? (
                    <ul className="plain-list">
                      {(item.items_display || item.items).map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ul>
                  ) : (
                    <p style={{ whiteSpace: "pre-wrap" }}>{item.text_display || item.text}</p>
                  )}
                </div>
              ))
            ) : (
              <p className="hint">No action plan in the saved draft.</p>
            )}
          </div>
        ) : null}

        {tab === "review" ? (
          <ReportReviewBlock
            clientId={clientId}
            detail={detail}
            busy={busy}
            setBusy={setBusy}
            setDetail={setDetail}
            setError={setError}
            setNotice={setNotice}
            reloadList={reloadList}
          />
        ) : null}
      </div>

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
            Excerpt (content read)
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
                  setNotice("Source saved (no fetch/AI).");
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Save source
          </button>
        </div>
      ) : null}

      __TECH_BLOCK__
    </section>
  );
}

function ReportReviewBlock({ clientId, detail, busy, setBusy, setDetail, setError, setNotice, reloadList }) {
  const report = detail.report;
  const review = detail.review || {};
  const canReview = Boolean(review.can_review);
  const [items, setItems] = useState(review.item_feedback || []);
  const [finalText, setFinalText] = useState(review.final_version_text || "");
  const [reviewerName, setReviewerName] = useState(review.reviewer_name || "");

  useEffect(() => {
    const next = detail.review || {};
    setItems(next.item_feedback || []);
    setFinalText(next.final_version_text || "");
    setReviewerName(next.reviewer_name || "");
  }, [report.id, review.execution_key, review.record?.updated_at]);

  function updateItem(idx, patch) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  function saveReview(extra = {}) {
    setBusy(true);
    setError("");
    api(`/api/clients/${clientId}/reports/${report.id}/review`, {
      method: "POST",
      body: {
        reviewer_name: reviewerName,
        item_feedback: items,
        final_version_text: finalText,
        ...extra,
      },
    })
      .then(async (payload) => {
        setDetail(payload);
        await reloadList();
        setNotice(
          extra.approve
            ? `Report #${report.id} approved by ${reviewerName}.`
            : extra.compose_final_from_items
              ? `Final version composed for report #${report.id}.`
              : `Review saved for report #${report.id} (${payload.review?.execution_key || "—"}).`
        );
      })
      .catch((exc) => setError(exc.message))
      .finally(() => setBusy(false));
  }

  if (!canReview) {
    return (
      <div className="stack">
        <h4>Human review</h4>
        <p className="banner warn-soft">
          {report.status === "prepared" || !report.executed_at
            ? "Prepared or unused report — not approvable until a usable AI run exists."
            : report.status === "failed"
              ? "Failed / unusable analysis — not approvable."
              : "Staff review is not available for this report."}
        </p>
        <p className="hint">
          Approval requires an explicit human confirmation after a usable AI draft. A new execution
          gets a new review key and does not inherit an old approval.
        </p>
      </div>
    );
  }

  return (
    <div className="stack report-review-panel">
      <h4>Human review</h4>
      <p className="hint">
        Execution <code>{review.execution_key || "—"}</code>
        {" · "}
        <strong>{review.is_approved ? "Approved" : review.review_status_label || "Awaiting review"}</strong>
        {review.record?.approved_at ? ` · approved ${review.record.approved_at}` : ""}
      </p>
      <p className="hint">
        AI draft, specialist corrections and final text stay separate. New AI runs must be reviewed again.
      </p>

      <div className="report-review-grid">
        <section className="report-review-col">
          <h5>AI wrote</h5>
          <p className="hint">Saved AI original for this execution (read-only).</p>
          {(items || []).map((item, idx) => (
            <div className="report-section" key={`ai-${item.key || idx}`}>
              <h5>{item.label}</h5>
              <p style={{ whiteSpace: "pre-wrap" }}>{item.ai_text || "—"}</p>
            </div>
          ))}
        </section>

        <section className="report-review-col">
          <h5>Specialist corrects</h5>
          <p className="hint">Accept, correct, reject or add per conclusion.</p>
          {(items || []).map((item, idx) => (
            <div className="report-section" key={`edit-${item.key || idx}`}>
              <h5>{item.label}</h5>
              <label>
                Decision
                <select
                  value={item.decision || ""}
                  onChange={(e) => updateItem(idx, { decision: e.target.value })}
                >
                  {ITEM_DECISION_OPTIONS.map((o) => (
                    <option key={o.value || "empty"} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              {item.decision === "correct" || item.decision === "add" || item.key === "addition.staff" ? (
                <label>
                  Staff text
                  <textarea
                    rows={3}
                    value={item.human_text || ""}
                    onChange={(e) => updateItem(idx, { human_text: e.target.value })}
                  />
                </label>
              ) : null}
            </div>
          ))}
        </section>

        <section className="report-review-col">
          <h5>Final text</h5>
          <p className="hint">Merged version used after explicit approval / PDF for approved reports.</p>
          <label>
            Reviewer
            <input
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              placeholder="Staff name"
            />
          </label>
          <label>
            Merged final version
            <textarea
              rows={12}
              value={finalText}
              onChange={(e) => setFinalText(e.target.value)}
              placeholder="Combine useful AI points and your own additions here"
            />
          </label>
        </section>
      </div>

      <div className="row-actions wrap">
        <button className="secondary" type="button" disabled={busy} onClick={() => saveReview()}>
          Save review
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => saveReview({ compose_final_from_items: true })}
        >
          Compose final from choices
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || review.is_approved || !String(finalText || "").trim() || !String(reviewerName || "").trim()}
          onClick={() => {
            const ok = window.confirm(
              `Approve report #${report.id} explicitly?\\n\\nThis confirms the human final version. A later AI run will not keep this approval.`
            );
            if (!ok) return;
            saveReview({ approve: true });
          }}
        >
          Explicitly approve
        </button>
      </div>
      {review.is_approved ? (
        <p className="banner">
          Approved by {review.reviewer_name || reviewerName}
          {review.record?.approved_at ? ` on ${review.record.approved_at}` : ""}.
        </p>
      ) : (
        <p className="hint">“Approved” appears only after explicit approval.</p>
      )}
    </div>
  );
}
'''

detail_and_review = detail_and_review.replace("__TECH_BLOCK__", tech_block)

# Main page head - read from a separate template file we'll write with Write tool
main = (ROOT / "_reports_main_snippet.jsx").read_text(encoding="utf-8")

out = main + "\n" + helpers + detail_and_review + "\n"
(ROOT / "ReportsPage.jsx").write_text(out, encoding="utf-8")
print("wrote", len(out), "chars")
