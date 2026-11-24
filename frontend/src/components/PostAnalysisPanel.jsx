import { useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * AI-feedbackpaneel voor één bericht.
 * Het openen, voorbereiden of testen met een voorbeeld start nooit een betaalde aanroep.
 */
export default function PostAnalysisPanel({ clientId, postId, onError, onSaved }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [adminDetail, setAdminDetail] = useState("");
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
    setAdminDetail("");
    setPrepareResult(null);
    setData(null);
    reload().catch((exc) => {
      setAdminDetail(exc.message || "");
      onError?.("De feedback voor dit bericht kon niet worden geladen.");
    });
  }, [clientId, postId]);

  if (!data) {
    return <p className="muted">Feedback bij dit bericht laden…</p>;
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
      <h4>Inzicht, vervolgactie &amp; AI-feedback</h4>
      <p className="hint">
        Vul hieronder zelf je beoordeling, inzicht en vervolgactie in, of vraag een AI-voorstel op.
        Het openen van dit blok kost geen tegoed.
      </p>

      {!claudeReady ? (
        <p className="banner warn-soft">
          Live AI-feedback staat nog niet aan. Je kunt wel zelf inzichten invullen of op{" "}
          <strong>Voorbeeldfeedback testen</strong> klikken.
        </p>
      ) : null}

      <div className="row-actions wrap">
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setNotice("");
            setAdminDetail("");
            setPrepareResult(null);
            api(`/api/clients/${clientId}/posts/${postId}/analysis/prepare`, { method: "POST" })
              .then((payload) => {
                setPrepareResult(payload);
                setNotice("Gegevens van dit bericht staan klaar om AI-feedback op te vragen.");
                setSourceAnalysisId(payload.analysis_id);
                return reload();
              })
              .catch((exc) => {
                setAdminDetail(exc.message || "");
                onError?.("Het voorbereiden van de AI-feedback is niet gelukt.");
              })
              .finally(() => setBusy(false));
          }}
        >
          1. Gegevens klaarzetten (gratis)
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || !prepareResult?.analysis_id || !claudeReady}
          title={
            !claudeReady
              ? "Live AI-feedback is nog niet geactiveerd door beheer"
              : !prepareResult?.analysis_id
                ? "Zet eerst de gegevens klaar via stap 1"
                : "Vraag AI-feedback aan voor dit bericht"
          }
          onClick={() => {
            const est = prepareResult?.cost_estimate_usd;
            const ok = window.confirm(
              `Wil je betaalde AI-feedback aanvragen voor dit bericht?\n\n` +
                `Geschatte kosten: USD ${est?.low ?? "?"} – ${est?.high ?? "?"}\n\n` +
                `Klik op OK om door te gaan of op Annuleren om niets uit te voeren.`,
            );
            if (!ok) {
              setNotice("Geannuleerd — er is geen AI-aanroep gestart.");
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
                setNotice("AI-feedback is opgehaald en hieronder ingevuld.");
                await reload();
                await onSaved?.();
              })
              .catch((exc) => {
                setAdminDetail(exc.message || "");
                onError?.("Het ophalen van AI-feedback is niet gelukt.");
              })
              .finally(() => setBusy(false));
          }}
        >
          2. Vraag AI-feedback (betaald)
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setNotice("");
            setAdminDetail("");
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
                setNotice("Voorbeeldfeedback is ingevuld (gratis). Je kunt de tekst hieronder aanpassen.");
                await reload();
                await onSaved?.();
              })
              .catch((exc) => {
                setAdminDetail(exc.message || "");
                onError?.("Het maken van voorbeeldfeedback is niet gelukt.");
              })
              .finally(() => setBusy(false));
          }}
        >
          Voorbeeldfeedback testen (gratis)
        </button>
      </div>

      {notice ? <p className="hint">{notice}</p> : null}

      <div className="stack">
        <label>
          Korte beoordeling (optioneel)
          <input
            value={rating}
            onChange={(e) => setRating(e.target.value)}
            placeholder="bijv. Sterke openingshook, veel opgeslagen"
          />
        </label>
        <label>
          Inzicht bij dit bericht
          <textarea
            rows={3}
            value={insight}
            onChange={(e) => setInsight(e.target.value)}
            placeholder="Wat valt op aan dit bericht en waarom werkte het wel of niet?"
          />
        </label>
        <label>
          Vervolgactie
          <textarea
            rows={2}
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="Wat herhalen, aanpassen of testen we de volgende keer?"
          />
        </label>
        <div>
          <button
            className="primary"
            type="button"
            disabled={busy || (!insight.trim() && !action.trim() && !rating.trim())}
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
                  provider: draft.provider || "Handmatig gecontroleerd",
                  model: draft.model || "manual",
                },
              })
                .then(async () => {
                  setNotice("Inzicht en vervolgactie zijn opgeslagen bij dit bericht.");
                  await reload();
                  await onSaved?.();
                })
                .catch((exc) => {
                  setAdminDetail(exc.message || "");
                  onError?.("Het opslaan van het inzicht is niet gelukt.");
                })
                .finally(() => setBusy(false));
            }}
          >
            Inzicht en vervolgactie opslaan
          </button>
        </div>
      </div>

      <details>
        <summary className="hint" style={{ cursor: "pointer" }}>
          Technische AI-details (alleen voor beheer)
        </summary>
        <div className="stack" style={{ marginTop: "0.5rem", gap: "0.35rem" }}>
          <p className="hint" style={{ margin: 0 }}>
            Status koppeling: {claudeReady ? `Gereed (${claude.model || "—"})` : `Mist ${missingSetting}`} ·
            Promptversie: {prompt.prompt_version || "—"} ({prompt.source || "—"}) · Media:{" "}
            {preview.published_media_count ?? published.count ?? 0} gepubliceerd /{" "}
            {preview.uploaded_media_count ?? uploads.count ?? 0} geüpload
          </p>
          {prepareResult ? (
            <p className="hint" style={{ margin: 0 }}>
              Voorbereide run #{prepareResult.analysis_id} · dekking{" "}
              {prepareResult.media_prep?.coverage || "—"} · kostenindicatie USD{" "}
              {prepareResult.cost_estimate_usd?.low}–{prepareResult.cost_estimate_usd?.high}
            </p>
          ) : null}
          {adminDetail ? (
            <pre className="hint" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
              {adminDetail}
            </pre>
          ) : null}
          {(data.analyses || []).length ? (
            <ul className="plain-list">
              {(data.analyses || []).map((row) => (
                <li key={row.id} className="hint">
                  #{row.id} · {row.status} · {row.provider} · {row.model}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </details>
    </section>
  );
}
