import { useEffect, useState } from "react";
import { api } from "../api.js";

// Human feedback + Logs adopt live below each AI trial post.

function money(range) {
  if (!range) return "unknown";
  const low = range.low;
  const high = range.high;
  if (low == null && high == null) return "unknown";
  return `USD ${low} – ${high} (estimate)`;
}

function displayCost(value, known) {
  if (!known || value == null) return "unknown";
  return String(value);
}

export default function AiTrialPage({ client }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/ai-trial`);
    setData(payload);
  }

  useEffect(() => {
    setError("");
    setNotice("");
    reload().catch((exc) => setError(exc.message));
  }, [client.id]);

  if (!data) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Loading…</p>;
  }

  const trial = data.trial;
  const estimate = trial?.estimate;
  const capability = trial?.capability || {};
  const modelId = capability.exact_model_id || capability.model || data.ai_status?.model || "—";
  const provider = capability.provider || data.ai_status?.base_host || "—";

  return (
    <div className="stack">
      <p className="hint">
        AI trial for post analysis. This page does <strong>not</strong> start a paid AI request on open or
        reload. Saved results stay separated per client. Format proposals are not automatically
        accepted.
      </p>

      <section className="card stack">
        <h3>Provider & model (no Claude label)</h3>
        <p className="banner">
          Provider: <strong>{provider}</strong>
          <br />
          Exact model ID: <strong>{modelId}</strong>
          <br />
          {capability.is_claude
            ? "Note: this looks like Claude — do not present it as Gemini."
            : capability.is_gemini
              ? "This is a Gemini result path. Do not call it a Claude result."
              : capability.label_warning}
        </p>
        <p className="hint">
          Docs:{" "}
          <a href={capability.official_model_docs} target="_blank" rel="noreferrer">
            model
          </a>
          {" · "}
          <a href={capability.official_pricing} target="_blank" rel="noreferrer">
            pricing
          </a>
        </p>
        <ul className="plain-list">
          {(capability.notes || []).map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <h3>Instructions included (real files)</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Purpose</th>
                <th>Source</th>
                <th>Status</th>
                <th>Characters</th>
              </tr>
            </thead>
            <tbody>
              {(data.prompt_catalog || []).map((row) => (
                <tr key={`${row.purpose}-${row.source_path}`}>
                  <td>{row.purpose}</td>
                  <td>{row.source_label}</td>
                  <td>{row.status}</td>
                  <td>{row.chars ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          For the analysis request: Performance analysis + Role + Quality standard. Trend/client report/clusters
          are not run. Excel rating/insight/action are <strong>not</strong> in the AI input.
        </p>
      </section>

      <section className="card stack">
        <h3>Prepare trial</h3>
        <div className="row-actions">
          <button
            className="primary"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError("");
              api(`/api/clients/${client.id}/ai-trial/prepare`, { method: "POST", body: {} })
                .then((payload) => {
                  setData(payload);
                  setNotice("Trial prepared (media + input preview). No AI request executed.");
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Prepare trial (again)
          </button>
        </div>
        {trial ? (
          <p className="banner">
            Status: <strong>{trial.status}</strong> · prompt {trial.prompt_version} · prepared{" "}
            {trial.prepared_at}
            {trial.executed_at ? ` · result ${trial.executed_at}` : ""}
          </p>
        ) : (
          <p className="hint">No trial for this client yet.</p>
        )}
      </section>

      {trial ? (
        <>
          <section className="card stack">
            <h3>Cost estimate (not actual cost)</h3>
            <p>
              Rate {estimate?.rate?.model}: {estimate?.rate?.currency} {estimate?.rate?.input_per_1m}/1M input ·{" "}
              {estimate?.rate?.output_per_1m}/1M output · rate date {estimate?.rate?.rate_date}
            </p>
            <p>
              Trial estimate: <strong>{money(estimate?.trial_estimated_usd)}</strong>
            </p>
            <p className="hint">{estimate?.display_rule}</p>
            <p className="hint">Failed requests can still incur cost; missing usage ≠ 0.</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Post</th>
                    <th>Status</th>
                    <th>Tokens</th>
                    <th>Actual cost</th>
                  </tr>
                </thead>
                <tbody>
                  {(trial.usage_events || []).map((ev) => (
                    <tr key={ev.id}>
                      <td>{ev.post_id}</td>
                      <td>{ev.status}</td>
                      <td>
                        {ev.total_tokens == null
                          ? "unknown"
                          : `${ev.prompt_tokens}/${ev.completion_tokens}/${ev.total_tokens}`}
                      </td>
                      <td>{displayCost(ev.actual_cost, ev.cost_known)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {(trial.posts || []).map((post) => (
            <article className="card stack" key={post.post_id}>
              <h3>
                {post.role} · post {post.post_id} · {post.content_kind}
              </h3>
              <p className="hint">{post.selection_reason}</p>
              <p>
                <a href={post.permalink} target="_blank" rel="noreferrer">
                  {post.permalink}
                </a>
              </p>

              <h4>Available content before execution</h4>
              <p>
                Coverage: <strong>{post.media_prep?.coverage || post.media_access?.prepared?.coverage || "—"}</strong>
              </p>
              <ul className="plain-list">
                <li>
                  Images for model: {(post.media_prep?.images_for_model || []).length} · full video:{" "}
                  {post.media_prep?.full_video_to_model ? "yes" : "no"} · audio:{" "}
                  {post.media_prep?.audio_to_model ? "yes" : "no"}
                </li>
                {(post.media_prep?.images_for_model || []).map((img) => (
                  <li key={`${img.path}-${img.role}`}>
                    {img.role}
                    {img.timestamp_s != null ? ` @ ${img.timestamp_s}s` : ""} — {img.path}
                  </li>
                ))}
                {(post.media_prep?.missing || []).map((m) => (
                  <li key={m}>Missing: {m}</li>
                ))}
                {(post.media_prep?.limitations || post.media_access?.prepared?.limitations || []).map((lim) => (
                  <li key={lim}>{lim}</li>
                ))}
              </ul>

              <h4>Format rules for this content type</h4>
              <p className="hint">{post.input_preview?.format_pack?.instruction}</p>
              <p className="hint">
                Eligible codes:{" "}
                {(post.input_preview?.format_pack?.eligible_formats || []).map((f) => f.code).join(", ") ||
                  "(none — expect ‘Geen passend bestaand format’ / ‘Niet vast te stellen’)"}
              </p>

              <details>
                <summary>Input preview (system excerpt + user)</summary>
                <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                  {post.input_preview?.system_excerpt || ""}
                </pre>
                <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                  {post.input_preview?.user_full || ""}
                </pre>
                <p className="hint">
                  Excel in request: {post.input_preview?.excel_assessment_included ? "yes" : "no"}
                </p>
              </details>

              <h4>AI proposal (separate from Excel; not automatically accepted)</h4>
              {post.live_ai_result ? (
                <div className="stack">
                  <p className="banner">
                    Model {post.live_ai_result.model} · prompt {post.live_ai_result.prompt_version} ·{" "}
                    {post.live_ai_result.executed_at}
                    <br />
                    Tokens:{" "}
                    {post.live_ai_result.usage?.prompt_tokens == null
                      ? "unknown"
                      : `${post.live_ai_result.usage.prompt_tokens} / ${post.live_ai_result.usage.completion_tokens} / ${post.live_ai_result.usage.total_tokens}`}
                    {" · "}
                    Cost:{" "}
                    {post.live_ai_result.cost_known
                      ? `USD ${post.live_ai_result.actual_cost_usd}`
                      : "unknown"}
                    <br />
                    Images sent: {(post.live_ai_result.images_sent || []).length}
                  </p>
                  <p className="hint">
                    Limitations:{" "}
                    {(post.live_ai_result.limitations || []).join(" · ") ||
                      "(no extra limitation recorded)"}
                  </p>
                  <p>
                    <strong>Format:</strong> {post.ai_format_code || "—"}
                    {post.ai_format_uncertainty ? ` (${post.ai_format_uncertainty})` : ""}
                  </p>
                  <p className="hint">{post.ai_format_rationale || ""}</p>
                  <p>
                    <strong>Pillar:</strong> {post.ai_pillar || "—"}
                  </p>
                  <p>
                    <strong>Hook:</strong> {post.ai_hook || "—"}
                  </p>
                  <p>
                    <strong>Insight:</strong> {post.ai_insight || "—"}
                  </p>
                  <p>
                    <strong>Action:</strong> {post.ai_action || "—"}
                  </p>
                  <h4>Observations</h4>
                  <ul className="plain-list">
                    {(post.ai_observations || []).map((obs, idx) => (
                      <li key={`${obs.evidence_ref}-${idx}`}>
                        [{obs.evidence_ref}] {obs.fact}
                      </li>
                    ))}
                  </ul>
                  {(post.live_ai_result.result?.unassessable || []).length ? (
                    <>
                      <h4>Not assessed / uncertain</h4>
                      <ul className="plain-list">
                        {post.live_ai_result.result.unassessable.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {(post.live_ai_result.result?.hypotheses || []).length ? (
                    <>
                      <h4>Hypotheses (not facts)</h4>
                      <ul className="plain-list">
                        {post.live_ai_result.result.hypotheses.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {post.live_ai_result.error ? (
                    <p className="banner error">{post.live_ai_result.error}</p>
                  ) : null}
                </div>
              ) : (
                <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(
                    {
                      status: post.status,
                      observations: post.ai_observations,
                      format: post.ai_format_code || "(still empty)",
                      uncertainty: post.ai_format_uncertainty || "(open)",
                      pillar: post.ai_pillar || "(open)",
                      hook: post.ai_hook || "(open)",
                      insight: post.ai_insight || "(open)",
                      action: post.ai_action || "(open)",
                    },
                    null,
                    2
                  )}
                </pre>
              )}
              <div className="row-actions">
                {trial.status !== "completed" ? (
                  <button
                    className="secondary"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true);
                      setError("");
                      const imageDefault =
                        post.role === "image"
                          ? "Geen passend bestaand format"
                          : "Niet vast te stellen";
                      api(`/api/clients/${client.id}/ai-trial/posts/${post.post_id}/mock`, {
                        method: "POST",
                        body: {
                          proposed_format_code: imageDefault,
                          format_rationale:
                            post.role === "image"
                              ? "Mock: C-codes do not automatically apply to a single image."
                              : "Mock: no paid analysis; incomplete media remains uncertain.",
                        },
                      })
                        .then((payload) => {
                          setData(payload);
                          setNotice(
                            `Mock result saved for post ${post.post_id} (no paid AI request).`
                          );
                        })
                        .catch((exc) => setError(exc.message))
                        .finally(() => setBusy(false));
                    }}
                  >
                    Save mock result (no paid call)
                  </button>
                ) : null}
                <button
                  className="secondary"
                  type="button"
                  onClick={() => {
                    api(`/api/clients/${client.id}/ai-trial/posts/${post.post_id}/accept`, {
                      method: "POST",
                      body: {},
                    })
                      .then((payload) => {
                        setData(payload);
                        setNotice(
                          `Proposal for post ${post.post_id} accepted without overwriting Excel.`
                        );
                      })
                      .catch((exc) => setError(exc.message));
                  }}
                >
                  Accept proposal (manual, without historical overwrite)
                </button>
              </div>
              {post.accepted_proposal_json ? (
                <p className="hint">Accepted: {JSON.stringify(post.accepted_proposal_json)}</p>
              ) : (
                <p className="hint">Not manually accepted yet.</p>
              )}

              <h4>Caption (reviewed)</h4>
              <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                {post.caption_preview || "(empty)"}
              </pre>

              <h4>Excel analysis (separate historical source)</h4>
              <p className="hint">
                {post.excel_assessment?.source_label || "—"} · {post.excel_assessment?.rating_text || "—"}
              </p>
              <p className="hint">{post.excel_assessment?.insight_text || ""}</p>
              <p className="hint">{post.excel_assessment?.action_text || ""}</p>
              <p className="hint">Excel is not overwritten by AI or feedback.</p>

              <HumanFeedbackBlock
                clientId={client.id}
                post={post}
                busy={busy}
                setBusy={setBusy}
                setData={setData}
                setError={setError}
                setNotice={setNotice}
              />
            </article>
          ))}
        </>
      ) : null}

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
    </div>
  );
}

const POST_ITEM_DECISIONS = [
  { value: "", label: "(no choice)" },
  { value: "accept", label: "Accept" },
  { value: "correct", label: "Correct" },
  { value: "reject", label: "Reject" },
  { value: "add", label: "Add" },
];

function HumanFeedbackBlock({ clientId, post, busy, setBusy, setData, setError, setNotice }) {
  const fb = post.human_feedback_record || {};
  const [usability, setUsability] = useState(fb.usability || "");
  const [notes, setNotes] = useState(fb.notes || "");
  const [correctedFormat, setCorrectedFormat] = useState(fb.corrected_format || "");
  const [correctedPillar, setCorrectedPillar] = useState(fb.corrected_pillar || "");
  const [correctedHook, setCorrectedHook] = useState(fb.corrected_hook || "");
  const [finalVerdict, setFinalVerdict] = useState(fb.final_verdict || "");
  const [reviewerName, setReviewerName] = useState(fb.reviewer_name || "");
  const [finalVersion, setFinalVersion] = useState(fb.final_version_text || "");
  const [items, setItems] = useState(fb.item_decisions || post.review_items_seed || []);
  const [showAiOriginal, setShowAiOriginal] = useState(true);
  const [adoptPreview, setAdoptPreview] = useState(null);
  const [selectedFields, setSelectedFields] = useState([]);

  useEffect(() => {
    const next = post.human_feedback_record || {};
    setUsability(next.usability || "");
    setNotes(next.notes || "");
    setCorrectedFormat(next.corrected_format || "");
    setCorrectedPillar(next.corrected_pillar || "");
    setCorrectedHook(next.corrected_hook || "");
    setFinalVerdict(next.final_verdict || "");
    setReviewerName(next.reviewer_name || "");
    setFinalVersion(next.final_version_text || "");
    setItems(next.item_decisions || post.review_items_seed || []);
    setAdoptPreview(null);
    setSelectedFields([]);
  }, [post.post_id, post.execution_key, post.human_feedback_record?.updated_at]);

  function updateItem(idx, patch) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  function saveFeedback(extra = {}) {
    setBusy(true);
    setError("");
    api(`/api/clients/${clientId}/ai-trial/posts/${post.post_id}/feedback`, {
      method: "POST",
      body: {
        usability,
        notes,
        corrected_format: correctedFormat,
        corrected_pillar: correctedPillar,
        corrected_hook: correctedHook,
        final_verdict: finalVerdict || finalVersion,
        final_version_text: finalVersion || finalVerdict,
        reviewer_name: reviewerName,
        item_decisions: items,
        ...extra,
      },
    })
      .then((payload) => {
        setData(payload);
        setNotice(
          extra.confirm_final_verdict
            ? `Approved for post ${post.post_id} by ${reviewerName}.`
            : `Feedback saved for post ${post.post_id} (execution ${post.execution_key || "—" }).`
        );
      })
      .catch((exc) => setError(exc.message))
      .finally(() => setBusy(false));
  }

  const aiOriginal = fb.ai_original || {
    proposed_format_code: post.ai_format_code,
    proposed_pillar: post.ai_pillar,
    proposed_hook: post.ai_hook,
    ai_insight: post.ai_insight,
    ai_action: post.ai_action,
  };

  return (
    <div className="stack">
      <h4>Human review</h4>
      <p className="hint">
        Route: AI draft → review → final version → Approved. Execution:{" "}
        <code>{post.execution_key || "—"}</code>
        {fb.review_status_label ? ` · ${fb.is_approved ? "Approved" : fb.review_status_label}` : ""}
      </p>
      <p className="banner">{post.joint_verdict || "AI analysis only; not human-reviewed"}</p>

      <label className="row-actions">
        <input
          type="checkbox"
          checked={showAiOriginal}
          onChange={(e) => setShowAiOriginal(e.target.checked)}
        />
        Show AI original
      </label>
      {showAiOriginal ? (
        <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(aiOriginal, null, 2)}
        </pre>
      ) : null}

      <label>
        Usability
        <select value={usability} onChange={(e) => setUsability(e.target.value)}>
          <option value="">(not chosen)</option>
          <option value="usable">Usable</option>
          <option value="partial">Partially usable</option>
          <option value="not_usable">Not usable</option>
        </select>
      </label>
      <label>
        Notes
        <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <label>
        Corrected format
        <input value={correctedFormat} onChange={(e) => setCorrectedFormat(e.target.value)} placeholder={post.ai_format_code || ""} />
      </label>
      <label>
        Corrected content pillar
        <input value={correctedPillar} onChange={(e) => setCorrectedPillar(e.target.value)} placeholder={post.ai_pillar || ""} />
      </label>
      <label>
        Corrected hook
        <input value={correctedHook} onChange={(e) => setCorrectedHook(e.target.value)} placeholder={post.ai_hook || ""} />
      </label>

      <h4>Per conclusion / advice</h4>
      {(items || []).map((item, idx) => (
        <div className="stack" key={item.key || idx} style={{ borderTop: "1px solid #ddd", paddingTop: "0.75rem" }}>
          <p>
            <strong>{item.label}</strong>
          </p>
          {item.ai_text ? <p className="hint">AI: {item.ai_text}</p> : null}
          <label>
            Decision
            <select
              value={item.decision || ""}
              onChange={(e) => updateItem(idx, { decision: e.target.value })}
            >
              {POST_ITEM_DECISIONS.map((o) => (
                <option key={o.value || "empty"} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {item.decision === "correct" || item.decision === "add" || item.key === "addition" ? (
            <label>
              Staff text
              <textarea
                rows={2}
                value={item.human_text || ""}
                onChange={(e) => updateItem(idx, { human_text: e.target.value })}
              />
            </label>
          ) : null}
        </div>
      ))}

      <button className="secondary" type="button" disabled={busy} onClick={() => saveFeedback()}>
        Save feedback
      </button>

      <h4>Final version &amp; approval</h4>
      <p className="hint">
        Without human feedback the status remains “AI analysis only; not human-reviewed”.
        “Approved” only after explicit confirmation with reviewer name.
      </p>
      <label>
        Reviewer
        <input
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="Staff name"
        />
      </label>
      <label>
        Combined final version
        <textarea
          rows={5}
          value={finalVersion}
          onChange={(e) => {
            setFinalVersion(e.target.value);
            setFinalVerdict(e.target.value);
          }}
          placeholder="Combine usable AI points and your own additions"
        />
      </label>
      <div className="row-actions wrap">
        <button className="secondary" type="button" disabled={busy} onClick={() => saveFeedback()}>
          Save draft
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => saveFeedback({ compose_final_from_items: true })}
        >
          Compose final version from choices
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || fb.is_approved}
          onClick={() => saveFeedback({ confirm_final_verdict: true })}
        >
          Explicitly approve
        </button>
      </div>
      {fb.final_verdict_confirmed || fb.is_approved ? (
        <p className="banner">
          Approved{fb.reviewer_name ? ` by ${fb.reviewer_name}` : ""}
          {fb.final_verdict_confirmed_at ? ` on ${fb.final_verdict_confirmed_at}` : ""}.
        </p>
      ) : null}

      <h4>Adopt into Logs</h4>
      <p className="hint">Choose fields deliberately. Excel rating/insight/action remain untouched.</p>
      <button
        className="secondary"
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError("");
          api(`/api/clients/${clientId}/ai-trial/posts/${post.post_id}/logs-preview`)
            .then((payload) => {
              setAdoptPreview(payload);
              setSelectedFields(
                (payload.fields || []).filter((f) => f.changed && f.resolvable).map((f) => f.field)
              );
            })
            .catch((exc) => setError(exc.message))
            .finally(() => setBusy(false));
        }}
      >
        Show current vs proposed values
      </button>
      {adoptPreview ? (
        <div className="stack">
          {(adoptPreview.fields || []).map((field) => (
            <label key={field.field} className="row-actions">
              <input
                type="checkbox"
                checked={selectedFields.includes(field.field)}
                disabled={!field.changed || !field.resolvable}
                onChange={(e) => {
                  setSelectedFields((prev) =>
                    e.target.checked ? [...prev, field.field] : prev.filter((x) => x !== field.field)
                  );
                }}
              />
              <span>
                <strong>{field.field}</strong>: now “{field.current || "—"}” → proposed “{field.proposed || "—"}”
                {field.note ? ` (${field.note})` : ""}
              </span>
            </label>
          ))}
          <p className="hint">{adoptPreview.excel_unchanged?.note}</p>
          <button
            className="primary"
            type="button"
            disabled={busy || selectedFields.length === 0}
            onClick={() => {
              setBusy(true);
              setError("");
              api(`/api/clients/${clientId}/ai-trial/posts/${post.post_id}/adopt-logs`, {
                method: "POST",
                body: { fields: selectedFields },
              })
                .then((payload) => {
                  if (payload.trial) {
                    setData((prev) => ({ ...prev, trial: payload.trial }));
                  } else {
                    return api(`/api/clients/${clientId}/ai-trial`).then(setData);
                  }
                  setAdoptPreview(payload.preview_after || null);
                  setNotice(
                    `Adopted into Logs for post ${post.post_id}: ${
                      (payload.applied || []).map((a) => a.field).join(", ") || "—"
                    }`
                  );
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Confirm adopt into Logs
          </button>
        </div>
      ) : null}
    </div>
  );
}
