import { useEffect, useState } from "react";
import { api } from "../api.js";

// Human feedback + Logs adopt live below each AI trial post.

function money(range) {
  if (!range) return "onbekend";
  const low = range.low;
  const high = range.high;
  if (low == null && high == null) return "onbekend";
  return `USD ${low} – ${high} (raming)`;
}

function displayCost(value, known) {
  if (!known || value == null) return "onbekend";
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
    return error ? <p className="banner error">{error}</p> : <p className="muted">Laden…</p>;
  }

  const trial = data.trial;
  const estimate = trial?.estimate;
  const capability = trial?.capability || {};
  const modelId = capability.exact_model_id || capability.model || data.ai_status?.model || "—";
  const provider = capability.provider || data.ai_status?.base_host || "—";

  return (
    <div className="stack">
      <p className="hint">
        AI-proefrun voor berichtanalyse. Deze pagina start <strong>geen</strong> betaalde AI-aanvraag bij openen of
        vernieuwen. Opgeslagen resultaten blijven per klant gescheiden. Formatvoorstellen worden niet automatisch
        overgenomen.
      </p>

      <section className="card stack">
        <h3>Provider & model (geen Claude-label)</h3>
        <p className="banner">
          Provider: <strong>{provider}</strong>
          <br />
          Exact model-ID: <strong>{modelId}</strong>
          <br />
          {capability.is_claude
            ? "Let op: dit lijkt op Claude — presenteer het niet als Gemini."
            : capability.is_gemini
              ? "Dit is een Gemini-resultaatpad. Noem het geen Claude-resultaat."
              : capability.label_warning}
        </p>
        <p className="hint">
          Documentatie:{" "}
          <a href={capability.official_model_docs} target="_blank" rel="noreferrer">
            model
          </a>
          {" · "}
          <a href={capability.official_pricing} target="_blank" rel="noreferrer">
            prijzen
          </a>
        </p>
        <ul className="plain-list">
          {(capability.notes || []).map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <h3>Meegeleverde instructies (echte bestanden)</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Doel</th>
                <th>Bron</th>
                <th>Status</th>
                <th>Tekens</th>
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
          Voor de analyseaanvraag: Prestatieanalyse + Rol + Kwaliteitsnorm. Trend-/klantrapport/clusters
          worden niet uitgevoerd. Excel-beoordeling/inzicht/actie zitten <strong>niet</strong> in de AI-input.
        </p>
      </section>

      <section className="card stack">
        <h3>Proefrun voorbereiden</h3>
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
                  setNotice("Proefrun voorbereid (media + invoervoorbeeld). Geen AI-aanvraag uitgevoerd.");
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Proefrun opnieuw voorbereiden
          </button>
        </div>
        {trial ? (
          <p className="banner">
            Status: <strong>{trial.status}</strong> · prompt {trial.prompt_version} · voorbereid{" "}
            {trial.prepared_at}
            {trial.executed_at ? ` · resultaat ${trial.executed_at}` : ""}
          </p>
        ) : (
          <p className="hint">Nog geen proefrun voor deze klant.</p>
        )}
      </section>

      {trial ? (
        <>
          <section className="card stack">
            <h3>Kostenraming (geen werkelijke kosten)</h3>
            <p>
              Tarief {estimate?.rate?.model}: {estimate?.rate?.currency} {estimate?.rate?.input_per_1m}/1M input ·{" "}
              {estimate?.rate?.output_per_1m}/1M output · tariefdatum {estimate?.rate?.rate_date}
            </p>
            <p>
              Raming proefrun: <strong>{money(estimate?.trial_estimated_usd)}</strong>
            </p>
            <p className="hint">{estimate?.display_rule}</p>
            <p className="hint">Mislukte aanvragen kunnen toch kosten geven; ontbrekende usage is niet hetzelfde als 0.</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Bericht</th>
                    <th>Status</th>
                    <th>Tokens</th>
                    <th>Werkelijke kosten</th>
                  </tr>
                </thead>
                <tbody>
                  {(trial.usage_events || []).map((ev) => (
                    <tr key={ev.id}>
                      <td>{ev.post_id}</td>
                      <td>{ev.status}</td>
                      <td>
                        {ev.total_tokens == null
                          ? "onbekend"
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

              <h4>Beschikbare content vóór uitvoering</h4>
              <p>
                Dekking: <strong>{post.media_prep?.coverage || post.media_access?.prepared?.coverage || "—"}</strong>
              </p>
              <ul className="plain-list">
                <li>
                  Afbeeldingen voor model: {(post.media_prep?.images_for_model || []).length} · volledige video:{" "}
                  {post.media_prep?.full_video_to_model ? "ja" : "nee"} · audio:{" "}
                  {post.media_prep?.audio_to_model ? "ja" : "nee"}
                </li>
                {(post.media_prep?.images_for_model || []).map((img) => (
                  <li key={`${img.path}-${img.role}`}>
                    {img.role}
                    {img.timestamp_s != null ? ` @ ${img.timestamp_s}s` : ""} — {img.path}
                  </li>
                ))}
                {(post.media_prep?.missing || []).map((m) => (
                  <li key={m}>Ontbreekt: {m}</li>
                ))}
                {(post.media_prep?.limitations || post.media_access?.prepared?.limitations || []).map((lim) => (
                  <li key={lim}>{lim}</li>
                ))}
              </ul>

              <h4>Formatregels voor dit contenttype</h4>
              <p className="hint">{post.input_preview?.format_pack?.instruction}</p>
              <p className="hint">
                Toegestane codes:{" "}
                {(post.input_preview?.format_pack?.eligible_formats || []).map((f) => f.code).join(", ") ||
                  "(geen — verwacht ‘Geen passend bestaand format’ / ‘Niet vast te stellen’)"}
              </p>

              <details>
                <summary>Invoervoorbeeld (systeemfragment + gebruiker)</summary>
                <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                  {post.input_preview?.system_excerpt || ""}
                </pre>
                <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                  {post.input_preview?.user_full || ""}
                </pre>
                <p className="hint">
                  Excel in aanvraag: {post.input_preview?.excel_assessment_included ? "ja" : "nee"}
                </p>
              </details>

              <h4>AI-voorstel (apart van Excel; niet automatisch overgenomen)</h4>
              {post.live_ai_result ? (
                <div className="stack">
                  <p className="banner">
                    Model {post.live_ai_result.model} · prompt {post.live_ai_result.prompt_version} ·{" "}
                    {post.live_ai_result.executed_at}
                    <br />
                    Tokens:{" "}
                    {post.live_ai_result.usage?.prompt_tokens == null
                      ? "onbekend"
                      : `${post.live_ai_result.usage.prompt_tokens} / ${post.live_ai_result.usage.completion_tokens} / ${post.live_ai_result.usage.total_tokens}`}
                    {" · "}
                    Kosten:{" "}
                    {post.live_ai_result.cost_known
                      ? `USD ${post.live_ai_result.actual_cost_usd}`
                      : "onbekend"}
                    <br />
                    Verstuurde afbeeldingen: {(post.live_ai_result.images_sent || []).length}
                  </p>
                  <p className="hint">
                    Beperkingen:{" "}
                    {(post.live_ai_result.limitations || []).join(" · ") ||
                      "(geen extra beperking vastgelegd)"}
                  </p>
                  <p>
                    <strong>Format:</strong> {post.ai_format_code || "—"}
                    {post.ai_format_uncertainty ? ` (${post.ai_format_uncertainty})` : ""}
                  </p>
                  <p className="hint">{post.ai_format_rationale || ""}</p>
                  <p>
                    <strong>Pijler:</strong> {post.ai_pillar || "—"}
                  </p>
                  <p>
                    <strong>Hook:</strong> {post.ai_hook || "—"}
                  </p>
                  <p>
                    <strong>Inzicht:</strong> {post.ai_insight || "—"}
                  </p>
                  <p>
                    <strong>Actie:</strong> {post.ai_action || "—"}
                  </p>
                  <h4>Waarnemingen</h4>
                  <ul className="plain-list">
                    {(post.ai_observations || []).map((obs, idx) => (
                      <li key={`${obs.evidence_ref}-${idx}`}>
                        [{obs.evidence_ref}] {obs.fact}
                      </li>
                    ))}
                  </ul>
                  {(post.live_ai_result.result?.unassessable || []).length ? (
                    <>
                      <h4>Niet beoordeeld / onzeker</h4>
                      <ul className="plain-list">
                        {post.live_ai_result.result.unassessable.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {(post.live_ai_result.result?.hypotheses || []).length ? (
                    <>
                      <h4>Hypothesen (geen feiten)</h4>
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
                      format: post.ai_format_code || "(nog leeg)",
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
                              ? "Simulatie: C-codes gelden niet automatisch voor één afbeelding."
                              : "Simulatie: geen betaalde analyse; onvolledige media blijft onzeker.",
                        },
                      })
                        .then((payload) => {
                          setData(payload);
                          setNotice(
                            `Simulatieresultaat opgeslagen voor bericht ${post.post_id} (geen betaalde AI-aanvraag).`
                          );
                        })
                        .catch((exc) => setError(exc.message))
                        .finally(() => setBusy(false));
                    }}
                  >
                    Simulatieresultaat opslaan (geen betaalde aanvraag)
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
                          `Voorstel voor bericht ${post.post_id} geaccepteerd zonder Excel te overschrijven.`
                        );
                      })
                      .catch((exc) => setError(exc.message));
                  }}
                >
                  Voorstel accepteren (handmatig, zonder historische overschrijving)
                </button>
              </div>
              {post.accepted_proposal_json ? (
                <p className="hint">Geaccepteerd: {JSON.stringify(post.accepted_proposal_json)}</p>
              ) : (
                <p className="hint">Nog niet handmatig geaccepteerd.</p>
              )}

              <h4>Bijschrift (nagekeken)</h4>
              <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                {post.caption_preview || "(leeg)"}
              </pre>

              <h4>Excel-analyse (aparte historische bron)</h4>
              <p className="hint">
                {post.excel_assessment?.source_label || "—"} · {post.excel_assessment?.rating_text || "—"}
              </p>
              <p className="hint">{post.excel_assessment?.insight_text || ""}</p>
              <p className="hint">{post.excel_assessment?.action_text || ""}</p>
              <p className="hint">Excel wordt niet overschreven door AI of feedback.</p>

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
  { value: "", label: "(geen keuze)" },
  { value: "accept", label: "Accepteren" },
  { value: "correct", label: "Corrigeren" },
  { value: "reject", label: "Afwijzen" },
  { value: "add", label: "Toevoegen" },
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
            ? `Goedgekeurd voor bericht ${post.post_id} door ${reviewerName}.`
            : `Feedback opgeslagen voor bericht ${post.post_id} (uitvoering ${post.execution_key || "—" }).`
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
      <h4>Menselijke controle</h4>
      <p className="hint">
        Route: AI-concept → controle → eindversie → Goedgekeurd. Uitvoering:{" "}
        <code>{post.execution_key || "—"}</code>
        {fb.review_status_label ? ` · ${fb.is_approved ? "Goedgekeurd" : fb.review_status_label}` : ""}
      </p>
      <p className="banner">{post.joint_verdict || "Alleen AI-analyse; nog niet door iemand gecontroleerd"}</p>

      <label className="row-actions">
        <input
          type="checkbox"
          checked={showAiOriginal}
          onChange={(e) => setShowAiOriginal(e.target.checked)}
        />
        Toon AI-origineel
      </label>
      {showAiOriginal ? (
        <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(aiOriginal, null, 2)}
        </pre>
      ) : null}

      <label>
        Bruikbaarheid
        <select value={usability} onChange={(e) => setUsability(e.target.value)}>
          <option value="">(niet gekozen)</option>
          <option value="usable">Bruikbaar</option>
          <option value="partial">Deels bruikbaar</option>
          <option value="not_usable">Niet bruikbaar</option>
        </select>
      </label>
      <label>
        Notities
        <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <label>
        Gecorrigeerd format
        <input value={correctedFormat} onChange={(e) => setCorrectedFormat(e.target.value)} placeholder={post.ai_format_code || ""} />
      </label>
      <label>
        Gecorrigeerde contentpijler
        <input value={correctedPillar} onChange={(e) => setCorrectedPillar(e.target.value)} placeholder={post.ai_pillar || ""} />
      </label>
      <label>
        Gecorrigeerde hook
        <input value={correctedHook} onChange={(e) => setCorrectedHook(e.target.value)} placeholder={post.ai_hook || ""} />
      </label>

      <h4>Per conclusie / advies</h4>
      {(items || []).map((item, idx) => (
        <div className="stack" key={item.key || idx} style={{ borderTop: "1px solid #ddd", paddingTop: "0.75rem" }}>
          <p>
            <strong>{item.label}</strong>
          </p>
          {item.ai_text ? <p className="hint">AI: {item.ai_text}</p> : null}
          <label>
            Beslissing
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
              Medewerkerstekst
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
        Feedback opslaan
      </button>

      <h4>Eindversie &amp; goedkeuring</h4>
      <p className="hint">
        Zonder menselijke feedback blijft de status “Alleen AI-analyse; nog niet door iemand gecontroleerd”.
        “Goedgekeurd” alleen na expliciete bevestiging met naam van de controleur.
      </p>
      <label>
        Controleur
        <input
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="Naam medewerker"
        />
      </label>
      <label>
        Gecombineerde eindversie
        <textarea
          rows={5}
          value={finalVersion}
          onChange={(e) => {
            setFinalVersion(e.target.value);
            setFinalVerdict(e.target.value);
          }}
          placeholder="Combineer bruikbare AI-punten met je eigen aanvullingen"
        />
      </label>
      <div className="row-actions wrap">
        <button className="secondary" type="button" disabled={busy} onClick={() => saveFeedback()}>
          Concept opslaan
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={() => saveFeedback({ compose_final_from_items: true })}
        >
          Eindversie samenstellen uit keuzes
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || fb.is_approved}
          onClick={() => saveFeedback({ confirm_final_verdict: true })}
        >
          Expliciet goedkeuren
        </button>
      </div>
      {fb.final_verdict_confirmed || fb.is_approved ? (
        <p className="banner">
          Goedgekeurd{fb.reviewer_name ? ` door ${fb.reviewer_name}` : ""}
          {fb.final_verdict_confirmed_at ? ` op ${fb.final_verdict_confirmed_at}` : ""}.
        </p>
      ) : null}

      <h4>Overnemen in Berichten</h4>
      <p className="hint">Kies velden bewust. Excel-beoordeling/inzicht/actie blijven onaangeroerd.</p>
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
        Toon huidige vs voorgestelde waarden
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
                <strong>{field.field}</strong>: nu “{field.current || "—"}” → voorstel “{field.proposed || "—"}”
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
                    `Overgenomen in Berichten voor bericht ${post.post_id}: ${
                      (payload.applied || []).map((a) => a.field).join(", ") || "—"
                    }`
                  );
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Bevestig overnemen in Berichten
          </button>
        </div>
      ) : null}
    </div>
  );
}
