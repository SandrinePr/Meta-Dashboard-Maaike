import { useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * Claude post feedback panel for one Social post.
 * Opening / preparing / mock never starts a paid AI call.
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
    setPrepareResult(null);
    setData(null);
    reload().catch((exc) => onError?.(exc.message));
  }, [clientId, postId]);

  if (!data) {
    return <p className="muted">Loading Claude feedback…</p>;
  }

  const inv = data.inventory || {};
  const published = inv.published_media || {};
  const uploads = inv.uploaded_media || {};
  const claude = data.claude || {};
  const prompt = data.prompt || {};
  const preview = data.input_preview || {};
  const draft = data.draft || {};
  const claudeReady = Boolean(claude.configured);
  const missingSetting = claude.missing_setting || "CLAUDE_API_KEY";

  return (
    <section className="card stack logs-feedback-panel" style={{ marginTop: "0.75rem" }}>
      <h4>Claude post feedback</h4>
      <p className="hint">
        Request feedback explicitly. Opening this card never starts a paid call. Reports stay on
        Gemini; post feedback uses Anthropic Claude with Maaike&apos;s saved post prompt.
      </p>

      {!claudeReady ? (
        <p className="banner warn-soft">
          Claude is not configured. Set <strong>{missingSetting}</strong> server-side on Render (or
          in <code>.env</code>) and restart. Until then you can still prepare input and run{" "}
          <strong>Mock feedback</strong>.
        </p>
      ) : (
        <p className="hint">
          Claude ready · model <strong>{claude.model || "—"}</strong> · prompt{" "}
          <strong>{prompt.prompt_version || "—"}</strong> ({prompt.source || "—"})
        </p>
      )}

      {draft.source_analysis_id ? (
        <div className="stack" style={{ gap: "0.25rem" }}>
          <p style={{ margin: 0 }}>
            <strong>Saved feedback</strong> #{draft.source_analysis_id} · {draft.status || "—"} ·{" "}
            {draft.provider || "—"} · {draft.model || "—"}
            {draft.prompt_version ? ` · prompt ${draft.prompt_version}` : ""}
          </p>
          <p className="hint" style={{ margin: 0 }}>
            Reloading this card shows the stored text below — no new paid call.
          </p>
        </div>
      ) : null}

      <div className="stack">
        <h5>Input that Claude can use</h5>
        <ul className="plain-list">
          <li>
            Caption: {preview.has_caption || inv.caption_preview ? "yes" : "missing"}
            {inv.caption_preview ? ` — “${String(inv.caption_preview).slice(0, 120)}…”` : ""}
          </li>
          <li>
            Published media URLs: {preview.published_media_count ?? published.count ?? 0}
            {preview.can_use_images || (published.count || 0) || (uploads.count || 0)
              ? " (images/frames can be prepared for the model)"
              : ""}
          </li>
          <li>Uploads: {preview.uploaded_media_count ?? uploads.count ?? 0}</li>
          <li>
            Role: {preview.analysis_role || inv.analysis_role || "—"} · prompt{" "}
            {preview.prompt_version || prompt.prompt_version || "—"}
          </li>
        </ul>
        {(preview.limitations || inv.limitations || []).length ? (
          <ul className="plain-list">
            {(preview.limitations || inv.limitations || []).map((line) => (
              <li key={line} className="hint">
                Limitation: {line}
              </li>
            ))}
          </ul>
        ) : null}
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
                    `${payload.media_prep?.images_for_model || 0} image(s)/frame(s) · ` +
                    `prompt ${payload.prompt_version || "—"} · estimate USD ${payload.cost_estimate_usd?.low}–${payload.cost_estimate_usd?.high} (not executed)`,
                );
                setSourceAnalysisId(payload.analysis_id);
                return reload();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Prepare input (no paid call)
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || !prepareResult?.analysis_id || !claudeReady}
          title={
            !claudeReady
              ? `Set ${missingSetting} first`
              : !prepareResult?.analysis_id
                ? "Prepare input first"
                : "Start paid Claude feedback"
          }
          onClick={() => {
            const est = prepareResult?.cost_estimate_usd;
            const mediaN =
              prepareResult?.media_for_model?.length || prepareResult?.media_prep?.images_for_model || 0;
            const ok = window.confirm(
              `Start paid Claude post feedback for post #${postId}?\n\n` +
                `Provider: ${prepareResult?.provider || est?.provider || "Anthropic Claude"}\n` +
                `Model: ${est?.model || prepareResult?.model || "—"}\n` +
                `Prompt: ${prepareResult?.prompt_version || "—"}\n` +
                `Prepared media for model: ${mediaN}\n` +
                `Estimate: USD ${est?.low ?? "?"} – ${est?.high ?? "?"}\n\n` +
                `OK = confirm paid Claude call. Cancel = no call.`,
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
                    (payload.error ? ` · ${payload.error}` : ""),
                );
                await reload();
                await onSaved?.();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Ask Claude for feedback (paid)
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setNotice("");
            api(`/api/clients/${clientId}/posts/${postId}/analysis/mock`, {
              method: "POST",
              body: { analysis_id: prepareResult?.analysis_id || null },
            })
              .then(async (payload) => {
                const a = payload.analysis || {};
                setInsight(a.insight_text || "");
                setAction(a.action_text || "");
                setRating(a.rating_text || "");
                setSourceAnalysisId(a.id);
                setPrepareResult((prev) => prev || { analysis_id: a.id });
                const checks = payload.input_checks || {};
                setNotice(
                  `Mock feedback #${a.id} saved · prompt=${checks.prompt_version || a.prompt_version || "—"}` +
                    ` · caption=${checks.has_caption || checks.post_snapshot ? "yes" : "n/a"}` +
                    ` · metrics=${checks.metrics ? "yes" : "n/a"} · no paid call`,
                );
                await reload();
                await onSaved?.();
              })
              .catch((exc) => onError?.(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Mock feedback (no paid call)
        </button>
      </div>

      {prepareResult ? (
        <div className="stack">
          <h5>Prepared for Claude</h5>
          <p className="hint">
            Provider {prepareResult.provider || "Anthropic Claude"} · model{" "}
            {prepareResult.model || prepareResult.cost_estimate_usd?.model || "—"} · prompt{" "}
            {prepareResult.prompt_version || "—"} ({prepareResult.prompt_source || "—"})
          </p>
          <p className="hint">
            Coverage: {prepareResult.media_prep?.coverage || "—"} · images/frames for model:{" "}
            {prepareResult.media_prep?.images_for_model ?? 0} · full video:{" "}
            {String(prepareResult.media_prep?.full_video_to_model)} · audio:{" "}
            {String(prepareResult.media_prep?.audio_to_model)}
          </p>
          <p>
            Estimate: USD {prepareResult.cost_estimate_usd?.low}–{prepareResult.cost_estimate_usd?.high}
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
            <p className="hint">No local images/frames prepared — caption/metrics still go in the prompt.</p>
          )}
        </div>
      ) : null}
      {notice ? <p className="hint">{notice}</p> : null}

      <div className="stack">
        <h5>Insight &amp; action (saved on this post)</h5>
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
                provider: draft.provider || "Specialist reviewed",
                model: draft.model || "manual",
              },
            })
              .then(async (payload) => {
                setNotice(`Saved analysis #${payload.analysis?.id || "—"} for this post / reports.`);
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
                {row.prompt_version ? ` · ${row.prompt_version}` : ""}
                {row.insight_text ? ` — ${(row.insight_text || "").slice(0, 80)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
