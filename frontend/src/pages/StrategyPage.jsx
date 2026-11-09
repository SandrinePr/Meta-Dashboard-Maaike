import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

export default function StrategyPage({ client }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [innerTab, setInnerTab] = useState("specialist");
  const [targetDraft, setTargetDraft] = useState({
    account_key: "",
    platform: "",
    metric_name: "",
    target_kind: "absolute",
    baseline_value: "",
    target_value: "",
    unit: "",
    period_year: new Date().getFullYear(),
    period_quarter: "",
    notes: "",
  });

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/strategy`);
    setData(payload);
  }

  useEffect(() => {
    setError("");
    setNotice("");
    reload().catch((exc) => setError(exc.message));
  }, [client.id]);

  const answers = data?.start_answers || {};
  const fields = data?.strategy_fields || {};
  const account = data?.account_info || {};
  const questions = data?.questions || [];

  const filledKeys = useMemo(
    () => questions.filter((q) => String(answers[q.key] || "").trim()).map((q) => q.key),
    [questions, answers],
  );
  const pending = data?.pending_questions || [];
  const openRequired = useMemo(() => pending.filter((item) => item.required), [pending]);
  const openOptional = useMemo(() => pending.filter((item) => !item.required), [pending]);

  const findingsText = fields.specialist_findings || "";
  const conclusionsText = fields.specialist_conclusions || "";

  if (!data) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Loading…</p>;
  }

  async function save({ markComplete = false } = {}) {
    setSaving(true);
    setError("");
    try {
      const payload = await api(`/api/clients/${client.id}/strategy`, {
        method: "PUT",
        body: {
          account_info: account,
          start_answers: answers,
          strategy_fields: fields,
          source_notes: data.source_notes,
          mark_complete: markComplete,
        },
      });
      setData(payload);
      setNotice(markComplete ? "Strategy marked complete." : "Draft saved. You can continue later.");
    } catch (exc) {
      setError(exc.message);
    } finally {
      setSaving(false);
    }
  }

  function setAnswer(key, value) {
    setData({ ...data, start_answers: { ...answers, [key]: value } });
  }

  function setField(key, value) {
    setData({ ...data, strategy_fields: { ...fields, [key]: value } });
  }

  return (
    <div className="stack">
      <div className="subnav-tabs" role="tablist" aria-label="Targets and strategy">
        <button
          type="button"
          role="tab"
          className={innerTab === "specialist" ? "subnav-tab is-active" : "subnav-tab"}
          aria-selected={innerTab === "specialist"}
          onClick={() => setInnerTab("specialist")}
        >
          Specialist
        </button>
        <button
          type="button"
          role="tab"
          className={innerTab === "figma" ? "subnav-tab is-active" : "subnav-tab"}
          aria-selected={innerTab === "figma"}
          onClick={() => setInnerTab("figma")}
        >
          Figma planning
        </button>
      </div>

      {innerTab === "figma" ? (
        <FigmaPlanningPanel clientId={client.id} onError={setError} onNotice={setNotice} />
      ) : null}

      {innerTab === "specialist" ? (
        <>
          <div className={`banner ${data.completed_at ? "" : "warn-soft"}`}>
            <strong>Status:</strong>{" "}
            {data.completed_at ? `Complete (${data.completed_at})` : "Draft — not marked complete"}
            <br />
            An incomplete strategy does not block Social posts, import or reports. Meta is not required.
          </div>

          <section className="card stack">
            <h3>Strategy & targets</h3>
            <p className="hint">
              Filled by the specialist. Source texts and question labels stay as stored for this
              client (including original language).
            </p>
            <h4>1. Taken from source files</h4>
            {(data.source_notes || []).length ? (
              <ul className="plain-list">
                {(data.source_notes || []).map((note, index) => (
                  <li key={index}>
                    <strong>{note.bron}</strong> — {note.gebruik}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="hint">No source notes yet. Use “Prefill from Red Rock sources”.</p>
            )}
            <div className="row-actions">
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  api(`/api/clients/${client.id}/strategy/prefill-redrock`, { method: "POST", body: {} })
                    .then((payload) => {
                      setData(payload);
                      setNotice("Prefill from local Red Rock sources applied.");
                    })
                    .catch((exc) => setError(exc.message));
                }}
              >
                Prefill from Red Rock sources
              </button>
            </div>
            {filledKeys.length ? (
              <div className="stack">
                {questions
                  .filter((q) => filledKeys.includes(q.key))
                  .map((question) => (
                    <label key={question.key}>
                      {question.label}
                      <span className="hint"> (imported / editable)</span>
                      <textarea
                        rows={3}
                        value={answers[question.key] || ""}
                        onChange={(e) => setAnswer(question.key, e.target.value)}
                      />
                    </label>
                  ))}
              </div>
            ) : null}
            <label>
              Account name
              <input
                value={account.naam || ""}
                onChange={(e) => setData({ ...data, account_info: { ...account, naam: e.target.value } })}
              />
            </label>
            {Object.keys(fields).filter((k) => k !== "specialist_findings" && k !== "specialist_conclusions").length ? (
              <>
                <h4>Strategy fields from sources</h4>
                {Object.entries(fields)
                  .filter(([key]) => key !== "specialist_findings" && key !== "specialist_conclusions")
                  .map(([key, value]) => {
                    const text =
                      value == null
                        ? ""
                        : typeof value === "string"
                          ? value
                          : JSON.stringify(value, null, 2);
                    return (
                      <label key={key}>
                        {key}
                        <textarea
                          rows={4}
                          value={text}
                          onChange={(e) => setField(key, e.target.value)}
                        />
                      </label>
                    );
                  })}
              </>
            ) : null}
          </section>

          <section className="card stack">
            <h4>2. Open questions</h4>
            {!openRequired.length && !openOptional.length ? (
              <p className="banner">No open questions left. You can mark the strategy complete.</p>
            ) : null}
            {openRequired.length ? (
              <>
                <p>
                  <strong>Required to complete</strong>
                </p>
                {openRequired.map((item) => (
                  <label key={`req-${item.key}-${item.question}`}>
                    {item.question}
                    <textarea
                      rows={3}
                      placeholder="Not in source files yet — add here"
                      value={answers[item.key] || ""}
                      onChange={(e) => setAnswer(item.key, e.target.value)}
                    />
                  </label>
                ))}
              </>
            ) : null}
            {openOptional.length ? (
              <>
                <p>
                  <strong>Optional</strong>
                </p>
                {openOptional.map((item) => (
                  <label key={`opt-${item.key}-${item.question}`}>
                    {item.question}
                    <textarea
                      rows={2}
                      placeholder="Optional"
                      value={answers[item.key] || ""}
                      onChange={(e) => setAnswer(item.key, e.target.value)}
                    />
                  </label>
                ))}
              </>
            ) : null}
            <div className="row-actions">
              <button className="primary" type="button" disabled={saving} onClick={() => save()}>
                Save draft
              </button>
              <button className="secondary" type="button" disabled={saving} onClick={() => save({ markComplete: true })}>
                Mark strategy complete
              </button>
            </div>
          </section>

          <section className="card stack">
            <h4>3. Targets</h4>
            <p className="hint">
              Year and optional quarter targets. Use <code>absolute</code> for “reach this number”
              and <code>growth</code> for “add this many”. Without a measurement, progress stays “not
              measurable yet”.
            </p>
            <div className="filters-row">
              <label>
                Platform / account
                <input
                  value={targetDraft.platform}
                  onChange={(e) => setTargetDraft({ ...targetDraft, platform: e.target.value })}
                  placeholder="e.g. Instagram"
                />
              </label>
              <label>
                Account label (optional)
                <input
                  value={targetDraft.account_key}
                  onChange={(e) => setTargetDraft({ ...targetDraft, account_key: e.target.value })}
                />
              </label>
              <label>
                Metric
                <input
                  value={targetDraft.metric_name}
                  onChange={(e) => setTargetDraft({ ...targetDraft, metric_name: e.target.value })}
                  placeholder="e.g. followers"
                />
              </label>
              <label>
                Kind
                <select
                  value={targetDraft.target_kind}
                  onChange={(e) => setTargetDraft({ ...targetDraft, target_kind: e.target.value })}
                >
                  <option value="absolute">absolute (reach)</option>
                  <option value="growth">growth (add)</option>
                </select>
              </label>
              <label>
                Baseline
                <input
                  value={targetDraft.baseline_value}
                  onChange={(e) => setTargetDraft({ ...targetDraft, baseline_value: e.target.value })}
                />
              </label>
              <label>
                Target value
                <input
                  value={targetDraft.target_value}
                  onChange={(e) => setTargetDraft({ ...targetDraft, target_value: e.target.value })}
                />
              </label>
              <label>
                Unit
                <input
                  value={targetDraft.unit}
                  onChange={(e) => setTargetDraft({ ...targetDraft, unit: e.target.value })}
                  placeholder="count / %"
                />
              </label>
              <label>
                Year
                <input
                  value={targetDraft.period_year}
                  onChange={(e) => setTargetDraft({ ...targetDraft, period_year: e.target.value })}
                />
              </label>
              <label>
                Quarter (optional)
                <input
                  value={targetDraft.period_quarter}
                  onChange={(e) => setTargetDraft({ ...targetDraft, period_quarter: e.target.value })}
                  placeholder="1–4"
                />
              </label>
            </div>
            <button
              className="primary"
              type="button"
              onClick={() => {
                if (!String(targetDraft.metric_name || "").trim()) {
                  setError("Enter a metric for the target.");
                  return;
                }
                api(`/api/clients/${client.id}/targets`, {
                  method: "POST",
                  body: {
                    ...targetDraft,
                    baseline_value: targetDraft.baseline_value === "" ? null : Number(targetDraft.baseline_value),
                    target_value: targetDraft.target_value === "" ? null : Number(targetDraft.target_value),
                    period_year: targetDraft.period_year === "" ? null : Number(targetDraft.period_year),
                    period_quarter: targetDraft.period_quarter === "" ? null : Number(targetDraft.period_quarter),
                  },
                })
                  .then(() => reload())
                  .then(() => setNotice("Target saved."))
                  .catch((exc) => setError(exc.message));
              }}
            >
              Save target
            </button>

            {(data.targets || []).length === 0 ? <p className="hint">No targets yet.</p> : null}
            {(data.targets || []).map((target) => (
              <article className="card stack" key={target.id}>
                <p>
                  <strong>
                    {target.platform || "—"}
                    {target.account_key ? ` · ${target.account_key}` : ""} · {target.metric_name}
                  </strong>{" "}
                  ({target.target_kind}) {target.period_year}
                  {target.period_quarter ? ` Q${target.period_quarter}` : ""}
                </p>
                <p className="hint">
                  Baseline {target.baseline_value ?? "—"} → target {target.target_value ?? "—"}{" "}
                  {target.unit}. Progress: <strong>{target.progress?.status || "not measurable yet"}</strong>
                  {target.progress?.ratio != null ? ` (${Math.round(target.progress.ratio * 100)}%)` : ""}
                </p>
                <ManualMeasure clientId={client.id} target={target} onSaved={reload} onError={setError} />
              </article>
            ))}
          </section>

          <section className="card stack specialist-findings">
            <h3>Specialist Findings & Conclusions</h3>
            <p className="hint">
              Human specialist notes — kept separate from AI report concepts. Stored with this
              client’s strategy fields. Review workflow for AI output stays in Reports & Analysis.
            </p>
            <label>
              Findings
              <textarea
                rows={5}
                value={findingsText}
                onChange={(e) => setField("specialist_findings", e.target.value)}
                placeholder="What the specialist observed…"
              />
            </label>
            <label>
              Conclusions
              <textarea
                rows={5}
                value={conclusionsText}
                onChange={(e) => setField("specialist_conclusions", e.target.value)}
                placeholder="Conclusions and recommendations…"
              />
            </label>
            <div className="row-actions">
              <button className="primary" type="button" disabled={saving} onClick={() => save()}>
                Save findings
              </button>
            </div>
          </section>
        </>
      ) : null}

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
    </div>
  );
}

function FigmaPlanningPanel({ clientId, onError, onNotice }) {
  const [overview, setOverview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fileKey, setFileKey] = useState("ew9PZ6d9NlRsL4ES8fMySO");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [preview, setPreview] = useState(null);
  const [acceptKindMismatch, setAcceptKindMismatch] = useState(false);
  const [postId, setPostId] = useState("");

  async function reload() {
    const payload = await api(`/api/clients/${clientId}/figma-planning`);
    setOverview(payload);
    if (payload.connection?.file_key) setFileKey(payload.connection.file_key);
  }

  useEffect(() => {
    reload().catch((exc) => onError(exc.message));
  }, [clientId]);

  if (!overview) return <p className="muted">Loading Figma planning…</p>;

  const items = overview.items || [];
  const connection = overview.connection || {};

  return (
    <div className="stack">
      <section className="card stack">
        <h3>Figma planning</h3>
        <p className="hint">
          Read-only link to Social Beheer creatives. Format / pillar / hook come from Figma briefs.
          Placeholders such as “Hier in te vullen” and “n.v.t.” are not usable. Week codes (B1, C1)
          are hints only — confirm post matches manually. Existing manual classifications are never
          overwritten automatically.
        </p>
        <div className="row-actions wrap">
          <label>
            File key
            <input value={fileKey} onChange={(e) => setFileKey(e.target.value)} style={{ minWidth: "22rem" }} />
          </label>
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              api(`/api/clients/${clientId}/figma-planning/connection`, {
                method: "PUT",
                body: { file_key: fileKey, file_name: "RRO - Social Beheer - Uitwerking creatives" },
              })
                .then(() => reload())
                .then(() => onNotice("Figma file linked to this client."))
                .catch((exc) => onError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Link file to client
          </button>
          <button
            className="primary"
            type="button"
            disabled={busy || !connection.linked}
            onClick={() => {
              setBusy(true);
              api(`/api/clients/${clientId}/figma-planning/sync`, { method: "POST", body: {} })
                .then((payload) => {
                  setOverview({
                    ...overview,
                    connection: payload.connection,
                    items: payload.items,
                  });
                  onNotice(
                    `Sync complete: ${payload.stats?.inserted || 0} new, ${payload.stats?.updated || 0} updated.`,
                  );
                })
                .catch((exc) => onError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Sync from Figma API
          </button>
        </div>
        <p className="hint">
          Linked: {connection.linked ? "yes" : "no"}
          {connection.source_url ? (
            <>
              {" "}
              ·{" "}
              <a href={connection.source_url} target="_blank" rel="noreferrer">
                Open source file
              </a>
            </>
          ) : null}
          {connection.last_synced_at ? ` · Last sync ${connection.last_synced_at}` : null}
          {connection.last_sync_note ? ` — ${connection.last_sync_note}` : null}
        </p>
        <p className="hint">
          Figma API token:{" "}
          {overview.figma_api?.configured
            ? "configured"
            : overview.figma_api?.missing_setting || "missing"}
          . Without a token, use a metadata snapshot import (server-side).
        </p>
        {!overview.figma_api?.configured ? (
          <p className="hint">
            Live Figma API sync needs <code>FIGMA_ACCESS_TOKEN</code> in <code>.env</code>. Until
            then this panel uses the linked file + imported snapshot (read-only) — fine for the demo.
          </p>
        ) : null}
      </section>

      <section className="card stack">
        <h3>Imported planning items</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>Code</th>
                <th>Kind</th>
                <th>Format</th>
                <th>Pillar</th>
                <th>Hook</th>
                <th>Node</th>
                <th>Link</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    {item.period_year && item.period_month
                      ? `${item.period_year}-${String(item.period_month).padStart(2, "0")}`
                      : item.page_name || "—"}
                  </td>
                  <td>{item.code || "—"}</td>
                  <td>{item.content_kind || "—"}</td>
                  <td>
                    {item.format_usable ? item.format_raw : <span className="muted">unusable</span>}
                  </td>
                  <td>
                    {item.pillar_usable ? item.pillar_raw : <span className="muted">unusable</span>}
                  </td>
                  <td title={item.hook_raw || ""}>
                    {item.hook_usable ? (item.hook_raw || "").slice(0, 48) : <span className="muted">unusable</span>}
                  </td>
                  <td>
                    <a href={item.source_url} target="_blank" rel="noreferrer">
                      {item.node_id}
                    </a>
                  </td>
                  <td>
                    {item.linked_post_id
                      ? `post #${item.linked_post_id}`
                      : item.link_status || "unlinked"}
                  </td>
                  <td>
                    <button
                      className="secondary"
                      type="button"
                      onClick={() => {
                        setSelectedItemId(String(item.id));
                        setPreview(null);
                        setAcceptKindMismatch(false);
                        setPostId("");
                        api(`/api/clients/${clientId}/figma-planning/items/${item.id}/suggestions`)
                          .then((payload) => setSuggestions(payload.suggestions || []))
                          .catch((exc) => onError(exc.message));
                      }}
                    >
                      Match…
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!items.length ? (
          <p className="hint">No planning items imported yet for this client.</p>
        ) : null}
      </section>

      {selectedItemId ? (
        <section className="card stack">
          <h3>Link planning item #{selectedItemId} to a post</h3>
          <p className="hint">
            Suggestions are low-confidence hints. Confirm the post yourself before saving.
          </p>
          <div className="row-actions wrap">
            <label>
              Post ID
              <input value={postId} onChange={(e) => setPostId(e.target.value)} placeholder="e.g. 8" />
            </label>
            <button
              className="secondary"
              type="button"
              disabled={!postId}
              onClick={() => {
                setAcceptKindMismatch(false);
                api(`/api/clients/${clientId}/figma-planning/items/${selectedItemId}/preview-link`, {
                  method: "POST",
                  body: { post_id: Number(postId) },
                })
                  .then(setPreview)
                  .catch((exc) => onError(exc.message));
              }}
            >
              Preview field changes
            </button>
          </div>
          {suggestions.length ? (
            <ul className="plain-list">
              {suggestions.map((s) => (
                <li key={s.post_id}>
                  <button type="button" className="secondary" onClick={() => setPostId(String(s.post_id))}>
                    Use post #{s.post_id}
                  </button>{" "}
                  {s.platform} · {s.published_at || "no date"} · {s.content_kind || "—"}
                  {s.planning_month ? ` · planning ${s.planning_month}` : ""}
                  {s.week_letter ? ` · week ${s.week_letter}` : ""}
                  {s.planning_week_letter ? ` (wanted ${s.planning_week_letter})` : ""} · score{" "}
                  {s.score}/{s.confidence || "low"} ({(s.reasons || []).join(", ") || "hint"}) —{" "}
                  {s.note}
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">
              No suggestions in the planning month/week yet — sync or import posts for that month, then
              enter a post ID manually. Date + content kind alone never auto-links.
            </p>
          )}
          {preview ? (
            <div className="stack">
              <h4>Before save</h4>
              <p className="banner">
                <strong>{preview.content_kind_compare?.display || "Figma / gepubliceerd"}</strong>
              </p>
              <p className="hint">{preview.note}</p>
              {preview.content_kind_compare?.mismatch ? (
                <label className="stack">
                  <span>
                    <input
                      type="checkbox"
                      checked={acceptKindMismatch}
                      onChange={(e) => setAcceptKindMismatch(e.target.checked)}
                    />{" "}
                    {preview.content_kind_compare.accept_prompt ||
                      "Ik bevestig bewust dat Figma en de gepubliceerde post een andere contentsoort hebben."}
                  </span>
                </label>
              ) : null}
              {(preview.changes || []).length ? (
                <ul className="plain-list">
                  {preview.changes.map((c) => (
                    <li key={c.field}>
                      <strong>{c.field}</strong>: fill “{c.from || "(empty)"}” → “{c.to}”
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="hint">No fields would be filled (all skipped or empty proposals).</p>
              )}
              {(preview.skipped || []).length ? (
                <>
                  <h4>Skipped</h4>
                  <ul className="plain-list">
                    {preview.skipped.map((s) => (
                      <li key={`${s.field}-${s.reason}`}>
                        <strong>{s.field}</strong>: {s.reason}
                        {s.current ? ` (current: ${s.current})` : ""}
                        {s.proposed ? ` (proposed: ${s.proposed})` : ""}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
              <div className="row-actions wrap">
                <button
                  className="primary"
                  type="button"
                  disabled={
                    busy || (preview.content_kind_compare?.mismatch && !acceptKindMismatch)
                  }
                  onClick={() => {
                    setBusy(true);
                    api(`/api/clients/${clientId}/figma-planning/items/${selectedItemId}/link`, {
                      method: "POST",
                      body: {
                        post_id: Number(postId),
                        confirm: true,
                        accept_content_kind_mismatch: Boolean(
                          preview.content_kind_compare?.mismatch && acceptKindMismatch
                        ),
                      },
                    })
                      .then(() => reload())
                      .then(() => {
                        onNotice(`Linked planning item #${selectedItemId} to post #${postId}.`);
                        setPreview(null);
                        setAcceptKindMismatch(false);
                      })
                      .catch((exc) => onError(exc.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Confirm link (fill empty fields only)
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setPreview(null);
                    setAcceptKindMismatch(false);
                    onNotice(
                      "Link cancelled — no format or pillar was saved from this preview."
                    );
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function ManualMeasure({ clientId, target, onSaved, onError }) {
  const [value, setValue] = useState("");
  const [measuredAt, setMeasuredAt] = useState("");
  const [source, setSource] = useState("manual");
  return (
    <div className="row-actions wrap">
      <input type="date" value={measuredAt} onChange={(e) => setMeasuredAt(e.target.value)} title="Measured on" />
      <input placeholder="measurement" value={value} onChange={(e) => setValue(e.target.value)} />
      <input placeholder="source (manual/Meta/…)" value={source} onChange={(e) => setSource(e.target.value)} />
      <button
        className="secondary"
        type="button"
        onClick={() => {
          if (value === "") {
            onError("Enter a measurement value.");
            return;
          }
          api(`/api/clients/${clientId}/targets/${target.id}/measurements`, {
            method: "POST",
            body: { value: Number(value), measured_at: measuredAt || undefined, source_name: source },
          })
            .then(onSaved)
            .catch((exc) => onError(exc.message));
        }}
      >
        Add measurement
      </button>
    </div>
  );
}
