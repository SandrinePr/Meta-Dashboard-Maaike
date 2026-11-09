import { useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * Media inventory + prepare/save insight for one Social post.
 * Opening / preparing does not start a paid AI call.
 */
export default function PostAnalysisPanel({ clientId, postId, onError, onSaved }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [insight, setInsight] = useState("");
  const [action, setAction] = useState("");
  const [rating, setRating] = useState("");
  const [sourceAnalysisId, setSourceAnalysisId] = useState(null);
  const [prepareResult, setPrepareResult] = useState(null);

  async function reload() {
    const payload = await api(`/api/clients/${clientId}/posts/${postId}/analysis-panel`);
    setData(payload);
    const draft = payload.draft || {};
    setInsight(draft.insight_text || "");
    setAction(draft.action_text || "");
    setRating(draft.rating_text || "");
    setSourceAnalysisId(draft.source_analysis_id || null);
  }

  useEffect(() => {
    setNotice("");
    setData(null);
    reload().catch((exc) => onError?.(exc.message));
  }, [clientId, postId]);

  if (!data) {
    return <p className="muted">Loading media &amp; insight…</p>;
  }

  const inv = data.inventory || {};
  const published = inv.published_media || {};
  const uploads = inv.uploaded_media || {};
  const figma = inv.figma_planning || {};

  return (
    <section className="card stack" style={{ marginTop: "0.75rem" }}>
      <h4>Media &amp; post insight</h4>
      <p className="hint">
        Published Meta material and Figma planning are listed separately. Opening or preparing does{" "}
        <strong>not</strong> start a paid AI call. AI Trial stays under Settings → AI Connections
        (internal probe).
      </p>

      <div className="stack">
        <p>
          <strong>Type:</strong> {inv.content_kind || "—"} → analysis role{" "}
          <strong>{inv.analysis_role || "—"}</strong>
        </p>
        {(inv.limitations || []).length ? (
          <ul className="plain-list">
            {(inv.limitations || []).map((line) => (
              <li key={line} className="hint">
                Limitation: {line}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="stack">
        <h5>Published material ({published.count || 0})</h5>
        {(published.urls || []).length ? (
          <ol className="plain-list">
            {(published.urls || []).map((item) => (
              <li key={`${item.index}-${item.url}`}>
                #{item.index} · {item.guessed_kind} · {item.host}
              </li>
            ))}
          </ol>
        ) : (
          <p className="hint">No Meta media URLs on this post.</p>
        )}
      </div>

      <div className="stack">
        <h5>Uploads ({uploads.count || 0})</h5>
        {(uploads.assets || []).length ? (
          <ol className="plain-list">
            {(uploads.assets || []).map((asset) => (
              <li key={asset.id}>
                {asset.position}. {asset.kind} · {asset.original_name}
              </li>
            ))}
          </ol>
        ) : (
          <p className="hint">No manual uploads.</p>
        )}
      </div>

      <div className="stack">
        <h5>Figma planning ({figma.count || 0}) — planned, not published</h5>
        {(figma.items || []).length ? (
          <ul className="plain-list">
            {(figma.items || []).map((item) => (
              <li key={item.item_id}>
                {item.code || "—"} · {item.content_kind || "—"} · node {item.node_id} ·{" "}
                {item.page_name || "—"}
                {item.format_usable ? ` · format ${item.format_raw}` : " · format unusable"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">No linked Figma planning item for this post.</p>
        )}
      </div>

      <div className="row-actions wrap">
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setNotice("");
            setPrepareResult(null);
            api(`/api/clients/${clientId}/posts/${postId}/analysis/prepare`, { method: "POST" })
              .then((payload) => {
                setPrepareResult(payload);
                setNotice(
                  `Prepared #${payload.analysis_id}: ${payload.media_prep?.coverage || "—"} · ` +
                    `${payload.media_prep?.images_for_model || 0} image(s)/frame(s) for model · ` +
                    `estimate USD ${payload.cost_estimate_usd?.low}–${payload.cost_estimate_usd?.high} (not executed)`
                );
                setSourceAnalysisId(payload.analysis_id);
                return reload();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Prepare analysis (no paid call)
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || !prepareResult?.analysis_id}
          onClick={() => {
            const est = prepareResult?.cost_estimate_usd;
            const mediaN = prepareResult?.media_for_model?.length || prepareResult?.media_prep?.images_for_model || 0;
            const ok = window.confirm(
              `Start paid AI image analysis for post #${postId}?\n\n` +
                `Model: ${est?.model || "—"}\n` +
                `Media to model: ${mediaN} image(s)/frame(s)\n` +
                `Estimate: USD ${est?.low ?? "?"} – ${est?.high ?? "?"}\n` +
                `Full video/audio are not sent.\n\n` +
                `OK = confirm paid call. Cancel = no call.`
            );
            if (!ok) {
              setNotice("Execute cancelled — no paid call.");
              return;
            }
            setBusy(true);
            setNotice("");
            api(`/api/clients/${clientId}/posts/${postId}/analysis/execute`, {
              method: "POST",
              body: {
                confirm: true,
                analysis_id: prepareResult.analysis_id,
                max_cost_usd: Math.max(Number(est?.high) || 0.05, 0.05),
              },
            })
              .then(async (payload) => {
                const a = payload.analysis || {};
                setInsight(a.insight_text || "");
                setAction(a.action_text || "");
                setRating(a.rating_text || "");
                setSourceAnalysisId(a.id);
                setNotice(
                  `Executed analysis #${a.id}: ${a.status}` +
                    (a.cost_known ? ` · USD ${a.actual_cost_usd}` : " · cost unknown") +
                    (payload.error ? ` · ${payload.error}` : "")
                );
                await reload();
                await onSaved?.();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Execute AI analysis (paid)
        </button>
      </div>
      {prepareResult ? (
        <div className="stack">
          <h5>Ready for AI (after Prepare)</h5>
          <p className="hint">
            Coverage: {prepareResult.media_prep?.coverage || "—"} · full video to model:{" "}
            {String(prepareResult.media_prep?.full_video_to_model)} · audio:{" "}
            {String(prepareResult.media_prep?.audio_to_model)}
          </p>
          <p>
            Estimate: USD {prepareResult.cost_estimate_usd?.low}–{prepareResult.cost_estimate_usd?.high} (
            {prepareResult.cost_estimate_usd?.model})
          </p>
          {(prepareResult.media_for_model || []).length ? (
            <ol className="plain-list">
              {(prepareResult.media_for_model || []).map((item, idx) => (
                <li key={`${item.path}-${idx}`}>
                  {item.role || "image"}
                  {item.timestamp_s != null ? ` @ ${item.timestamp_s}s` : ""} · {item.path}
                </li>
              ))}
            </ol>
          ) : (
            <p className="hint">No local images/frames prepared for the model.</p>
          )}
        </div>
      ) : null}
      {notice ? <p className="hint">{notice}</p> : null}

      <div className="stack">
        <h5>Insight &amp; action (saved for reports)</h5>
        <label>
          Rating
          <input value={rating} onChange={(e) => setRating(e.target.value)} placeholder="optional" />
        </label>
        <label>
          Insight
          <textarea
            rows={3}
            value={insight}
            onChange={(e) => setInsight(e.target.value)}
            placeholder="What did we learn from this post?"
          />
        </label>
        <label>
          Action
          <textarea
            rows={2}
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="What do we repeat, stop or test?"
          />
        </label>
        <button
          className="primary"
          type="button"
          disabled={busy || (!insight.trim() && !action.trim())}
          onClick={() => {
            setBusy(true);
            setNotice("");
            api(`/api/clients/${clientId}/posts/${postId}/analysis/insight`, {
              method: "PATCH",
              body: {
                insight_text: insight,
                action_text: action,
                rating_text: rating,
                source_analysis_id: sourceAnalysisId,
                provider: "Specialist reviewed",
                model: "manual",
              },
            })
              .then(async (payload) => {
                setNotice(`Saved analysis #${payload.analysis?.id || "—"} for client reports.`);
                await reload();
                await onSaved?.();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Save insight for reports
        </button>
        <p className="hint">{data.report_note}</p>
      </div>

      {(data.analyses || []).length ? (
        <div className="stack">
          <h5>Stored analyses</h5>
          <ul className="plain-list">
            {(data.analyses || []).map((row) => (
              <li key={row.id}>
                #{row.id} · {row.status} · {row.provider} · {row.model}
                {row.insight_text ? ` — ${(row.insight_text || "").slice(0, 80)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {data.ai_trial ? (
        <p className="hint">
          Internal AI Trial row present ({data.ai_trial.status}
          {data.ai_trial.executed_at ? ` · executed ${data.ai_trial.executed_at}` : " · not executed"}
          ). Location: {data.ai_trial_location}.
        </p>
      ) : null}
    </section>
  );
}
