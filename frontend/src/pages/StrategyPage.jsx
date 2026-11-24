import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiUrl } from "../api.js";

const AUTOSAVE_DELAY_MS = 900;

function dutchSaveError(exc) {
  const raw = String(exc?.message || exc || "").trim();
  if (!raw) return "Opslaan lukte niet";
  if (/failed to fetch|networkerror|load failed/i.test(raw)) return "Opslaan lukte niet";
  return raw.length < 160 ? raw : "Opslaan lukte niet";
}

function statusClass(status) {
  if (status === "definitief") return "strategy-status is-final";
  if (status === "te_controleren") return "strategy-status is-review";
  return "strategy-status is-draft";
}

export default function StrategyPage({ client, initialTab = "specialist" }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saveStatus, setSaveStatus] = useState("idle");
  const [innerTab, setInnerTab] = useState(initialTab || "specialist");

  useEffect(() => {
    if (initialTab) setInnerTab(initialTab);
  }, [initialTab, client?.id]);
  const [pdfBlob, setPdfBlob] = useState(null);
  const [pdfName, setPdfName] = useState("");
  const [proposalDraft, setProposalDraft] = useState(null);
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

  const dataRef = useRef(null);
  const autosaveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const dirtyRef = useRef(false);

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/strategy`);
    dataRef.current = payload;
    setData(payload);
    setProposalDraft(payload.pending_proposal || null);
    return payload;
  }

  useEffect(() => {
    setError("");
    setNotice("");
    setSaveStatus("idle");
    setPdfBlob(null);
    setPdfName("");
    dirtyRef.current = false;
    reload().catch((exc) => setError(exc.message));
    return () => {
      if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    };
  }, [client.id]);

  const answers = data?.start_answers || {};
  const fields = data?.strategy_fields || {};
  const account = data?.account_info || {};
  const questions = data?.questions || [];
  const publicFields = data?.public_strategy_fields || {};
  const canvaUrl = String(data?.canva_url || fields.canva_strategy_url || "").trim();
  const reviewStatus = data?.review_status || "concept";
  const pendingProposal = proposalDraft || data?.pending_proposal || null;

  const openRequired = useMemo(
    () => (data?.pending_questions || []).filter((item) => item.required),
    [data],
  );
  const openOptional = useMemo(
    () => (data?.pending_questions || []).filter((item) => !item.required),
    [data],
  );

  function scheduleAutosave() {
    dirtyRef.current = true;
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = window.setTimeout(() => {
      flushAutosave().catch(() => {});
    }, AUTOSAVE_DELAY_MS);
  }

  async function flushAutosave({ markComplete = false, clearComplete = false } = {}) {
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    const run = async () => {
      const current = dataRef.current;
      if (!current) return null;
      setSaveStatus("saving");
      setError("");
      try {
        const payload = await api(`/api/clients/${client.id}/strategy`, {
          method: "PUT",
          body: {
            account_info: current.account_info || {},
            start_answers: current.start_answers || {},
            strategy_fields: current.strategy_fields || {},
            source_notes: current.source_notes || [],
            mark_complete: markComplete,
            clear_complete: clearComplete,
          },
        });
        if (payload?.persist && payload.persist.durable !== true) {
          throw new Error(
            payload.persist.error || "Externe opslag bevestigde de wijziging niet.",
          );
        }
        dataRef.current = payload;
        setData(payload);
        setProposalDraft(payload.pending_proposal || null);
        dirtyRef.current = false;
        setSaveStatus("saved");
        if (markComplete) setNotice("Strategie is definitief.");
        else if (clearComplete) setNotice("Strategie staat weer op concept.");
        return payload;
      } catch (exc) {
        dirtyRef.current = true;
        setSaveStatus("error");
        setError(dutchSaveError(exc));
        throw exc;
      }
    };
    const queued = saveChainRef.current.then(run, run);
    saveChainRef.current = queued.catch(() => {});
    return queued;
  }

  function patchLocal(updater) {
    setData((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      dataRef.current = next;
      return next;
    });
    scheduleAutosave();
  }

  function setAnswer(key, value) {
    patchLocal((prev) => ({
      ...prev,
      start_answers: { ...(prev?.start_answers || {}), [key]: value },
    }));
  }

  function setField(key, value) {
    patchLocal((prev) => ({
      ...prev,
      strategy_fields: { ...(prev?.strategy_fields || {}), [key]: value },
    }));
  }

  function setProposalAnswer(key, value) {
    setProposalDraft((prev) => ({
      ...(prev || {}),
      start_answers: { ...((prev && prev.start_answers) || {}), [key]: value },
    }));
  }

  if (!data) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Laden…</p>;
  }

  const findingsText = fields.specialist_findings || "";
  const conclusionsText = fields.specialist_conclusions || "";
  const isRedRock = /red\s*rock/i.test(String(client?.name || ""));

  return (
    <div className="stack">
      <div className="subnav-tabs" role="tablist" aria-label="Doelen en strategie">
        <button
          type="button"
          role="tab"
          className={innerTab === "specialist" ? "subnav-tab is-active" : "subnav-tab"}
          aria-selected={innerTab === "specialist"}
          onClick={() => setInnerTab("specialist")}
        >
          Doelen & strategie
        </button>
        <button
          type="button"
          role="tab"
          className={innerTab === "figma" ? "subnav-tab is-active" : "subnav-tab"}
          aria-selected={innerTab === "figma"}
          onClick={() => setInnerTab("figma")}
        >
          Figma-planning
        </button>
      </div>

      {innerTab === "figma" ? (
        <FigmaPlanningPanel clientId={client.id} onError={setError} onNotice={setNotice} />
      ) : null}

      {innerTab === "specialist" ? (
        <>
          <div className="strategy-header-row">
            <div className={statusClass(reviewStatus)} role="status">
              <strong>{data.review_status_label || "Concept"}</strong>
              <span>{data.next_step}</span>
            </div>
            <div className="setup-save-status" aria-live="polite">
              {saveStatus === "saving" ? <span className="setup-save-saving">Bezig met opslaan…</span> : null}
              {saveStatus === "saved" ? <span className="setup-save-ok">Opgeslagen</span> : null}
              {saveStatus === "error" ? (
                <span className="setup-save-error">
                  Opslaan mislukt.{" "}
                  <button type="button" className="linkish" onClick={() => flushAutosave().catch(() => {})}>
                    Opnieuw proberen
                  </button>
                </span>
              ) : null}
            </div>
          </div>

          <section className="card stack">
            <h3>Stand van zaken</h3>
            <p className="hint">
              Gebaseerd op de opgeslagen gegevens van {client.name} — dezelfde bron als in Klant
              inrichten.
            </p>
            <div className="strategy-status-grid">
              <div>
                <h4>Zelf ingevuld</h4>
                {(data.editor_filled || []).length ? (
                  <ul className="plain-list">
                    {(data.editor_filled || []).map((item) => (
                      <li key={`ed-${item.key}`}>
                        <strong>{item.label}</strong>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Nog geen eigen antwoorden.</p>
                )}
              </div>
              <div>
                <h4>Voorstel van HAMSTER</h4>
                {(data.hamster_proposals || []).length ? (
                  <ul className="plain-list">
                    {(data.hamster_proposals || []).map((item) => (
                      <li key={`hs-${item.key}`}>
                        <strong>{item.label}</strong>
                        {item.state === "te_controleren" ? (
                          <span className="hint"> — klaar ter controle</span>
                        ) : null}
                        {item.state === "opgenomen" || item.state === "voorstel_opgenomen" ? (
                          <span className="hint"> — opgenomen</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Geen voorstel klaar. Lees een PDF in of vul handmatig in.</p>
                )}
              </div>
              <div>
                <h4>Nog verplicht</h4>
                {(data.missing_required_items || []).length ? (
                  <ul className="plain-list">
                    {(data.missing_required_items || []).map((item) => (
                      <li key={`miss-${item.key}`}>
                        <strong>{item.label}</strong>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="banner">Geen verplichte gaten meer.</p>
                )}
              </div>
            </div>
          </section>

          <StrategyActions
            clientId={client.id}
            canvaUrl={canvaUrl}
            pdfBlob={pdfBlob}
            pdfName={pdfName || data.strategy_pdf?.filename || data.last_pdf_meta?.filename || ""}
            strategyPdf={data.strategy_pdf || null}
            onCanvaUrl={(url) => {
              setField("canva_strategy_url", url);
              setNotice(url ? "Canva-link bewaard (optioneel)." : "Canva-link gewist.");
            }}
            onPdfStored={(payload, fileMeta) => {
              dataRef.current = payload;
              setData(payload);
              if (fileMeta?.blob) {
                setPdfBlob(fileMeta.blob);
                setPdfName(fileMeta.name || "");
              }
              setSaveStatus("saved");
              setNotice("PDF opgeslagen bij deze klant. Goedgekeurde strategie bleef ongewijzigd.");
            }}
            onError={setError}
          />

          <StrategyImportPanel
            clientId={client.id}
            onStaged={(payload, fileMeta) => {
              dataRef.current = payload;
              setData(payload);
              setProposalDraft(payload.pending_proposal || null);
              if (fileMeta?.blob) {
                setPdfBlob(fileMeta.blob);
                setPdfName(fileMeta.name || "");
              }
              if (payload.pending_proposal) {
                setNotice("Voorstel klaargezet ter controle. Nog niet definitief.");
              } else {
                setNotice(
                  "Bron bewaard. Geen nieuwe voorstellen — handmatige antwoorden bleven staan.",
                );
              }
              setSaveStatus("saved");
            }}
            onError={setError}
          />

          {pendingProposal ? (
            <section className="card stack strategy-proposal-card">
              <h3>Voorstel ter controle</h3>
              <p className="hint">
                Pas het voorstel aan en keur het goed. Pas daarna telt het als opgeslagen strategie.
                Handmatig ingevulde velden blijven staan.
              </p>
              {Object.keys(pendingProposal.start_answers || {}).length ? (
                <div className="stack">
                  {questions
                    .filter((q) => (pendingProposal.start_answers || {})[q.key])
                    .map((question) => (
                      <label key={`prop-${question.key}`}>
                        {question.label}
                        <span className="hint"> (voorstel)</span>
                        <textarea
                          rows={3}
                          value={(pendingProposal.start_answers || {})[question.key] || ""}
                          onChange={(e) => setProposalAnswer(question.key, e.target.value)}
                        />
                      </label>
                    ))}
                </div>
              ) : (
                <p className="muted">Geen nieuwe antwoorden in dit voorstel (velden waren al gevuld).</p>
              )}
              <div className="row-actions wrap">
                <button
                  className="primary"
                  type="button"
                  onClick={() => {
                    api(`/api/clients/${client.id}/strategy/proposal/approve`, {
                      method: "POST",
                      body: { proposal: pendingProposal },
                    })
                      .then((payload) => {
                        if (payload?.persist && payload.persist.durable !== true) {
                          throw new Error(
                            payload.persist.error || "Externe opslag bevestigde de goedkeuring niet.",
                          );
                        }
                        dataRef.current = payload;
                        setData(payload);
                        setProposalDraft(null);
                        setNotice("Voorstel goedgekeurd en opgenomen in de strategie.");
                        setSaveStatus("saved");
                      })
                      .catch((exc) => setError(dutchSaveError(exc)));
                  }}
                >
                  Voorstel goedkeuren
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => {
                    api(`/api/clients/${client.id}/strategy/proposal/discard`, { method: "POST", body: {} })
                      .then((payload) => {
                        dataRef.current = payload;
                        setData(payload);
                        setProposalDraft(null);
                        setNotice("Voorstel verworpen. Opgeslagen antwoorden ongewijzigd.");
                      })
                      .catch((exc) => setError(dutchSaveError(exc)));
                  }}
                >
                  Voorstel verwerpen
                </button>
              </div>
            </section>
          ) : null}

          {(data.overview_sections || []).length ? (
            <section className="card stack">
              <h3>Overzicht</h3>
              {(data.overview_sections || []).map((section) => (
                <div key={section.id} className="stack">
                  <h4 style={{ marginBottom: 0 }}>{section.title}</h4>
                  <ul className="plain-list">
                    {(section.items || []).map((item) => (
                      <li key={`${section.id}-${item.label}`}>
                        <strong>{item.label}:</strong>{" "}
                        {String(item.value || "").trim() ? (
                          String(item.value).length > 280 ? (
                            `${String(item.value).slice(0, 280)}…`
                          ) : (
                            item.value
                          )
                        ) : (
                          <span className="muted">— ontbreekt</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          ) : null}

          <section className="card stack">
            <h3>Strategie bewerken</h3>
            <p className="hint">Wijzigingen worden automatisch bewaard (zelfde gegevens als Klant inrichten).</p>
            {isRedRock ? (
              <div className="row-actions">
                <button
                  className="secondary"
                  type="button"
                  onClick={() => {
                    api(`/api/clients/${client.id}/strategy/prefill-redrock`, { method: "POST", body: {} })
                      .then((payload) => {
                        dataRef.current = payload;
                        setData(payload);
                        setNotice("Red Rock-bronnen als starttekst gezet (handmatige antwoorden behouden).");
                      })
                      .catch((exc) => setError(exc.message));
                  }}
                >
                  Prefill uit Red Rock-bronnen
                </button>
              </div>
            ) : null}
            <label>
              Accountnaam
              <input
                value={account.naam || ""}
                onChange={(e) =>
                  patchLocal((prev) => ({
                    ...prev,
                    account_info: { ...(prev?.account_info || {}), naam: e.target.value },
                  }))
                }
              />
            </label>
            {questions.map((question) => (
              <label key={question.key}>
                {question.label}
                {question.required_for_complete ? "" : " (optioneel)"}
                <textarea
                  rows={3}
                  value={answers[question.key] || ""}
                  onChange={(e) => setAnswer(question.key, e.target.value)}
                  placeholder={question.short_question || ""}
                />
              </label>
            ))}
            {Object.keys(publicFields).filter(
              (k) => k !== "specialist_findings" && k !== "specialist_conclusions",
            ).length ? (
              <>
                <h4>Overige strategieveelden</h4>
                {Object.entries(publicFields)
                  .filter(([key]) => key !== "specialist_findings" && key !== "specialist_conclusions")
                  .map(([key, value]) => {
                    const text =
                      value == null ? "" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
                    return (
                      <label key={key}>
                        {key}
                        <textarea rows={3} value={text} onChange={(e) => setField(key, e.target.value)} />
                      </label>
                    );
                  })}
              </>
            ) : null}
          </section>

          <section className="card stack">
            <h4>Open vragen</h4>
            {!openRequired.length && !openOptional.length ? (
              <p className="banner">Geen open vragen meer. Je kunt afronden zonder Canva-link.</p>
            ) : null}
            {openRequired.map((item) => (
              <label key={`req-${item.key}`}>
                {item.question}
                <textarea
                  rows={3}
                  placeholder="Nog niet in bronnen — vul hier in"
                  value={answers[item.key] || ""}
                  onChange={(e) => setAnswer(item.key, e.target.value)}
                />
              </label>
            ))}
            {openOptional.map((item) => (
              <label key={`opt-${item.key}`}>
                {item.question} <span className="hint">(optioneel)</span>
                <textarea
                  rows={2}
                  value={answers[item.key] || ""}
                  onChange={(e) => setAnswer(item.key, e.target.value)}
                />
              </label>
            ))}
            <div className="row-actions wrap">
              {reviewStatus === "definitief" ? (
                <button
                  className="secondary"
                  type="button"
                  onClick={() => flushAutosave({ clearComplete: true }).catch(() => {})}
                >
                  Terug naar concept
                </button>
              ) : (
                <button
                  className="primary"
                  type="button"
                  disabled={Boolean(pendingProposal) || (data.missing_required_items || []).length > 0}
                  onClick={() => flushAutosave({ markComplete: true }).catch(() => {})}
                >
                  Strategie definitief maken
                </button>
              )}
            </div>
            {pendingProposal ? (
              <p className="hint">Keur eerst het voorstel goed of verwerp het, daarna kun je afronden.</p>
            ) : null}
          </section>

          <section className="card stack">
            <h4>Doelen</h4>
            <p className="hint">
              Jaar- of kwartaaldoelen. Zonder meting blijft de voortgang “nog niet meetbaar”.
            </p>
            <div className="filters-row">
              <label>
                Platform
                <input
                  value={targetDraft.platform}
                  onChange={(e) => setTargetDraft({ ...targetDraft, platform: e.target.value })}
                  placeholder="bijv. Instagram"
                />
              </label>
              <label>
                Metric
                <input
                  value={targetDraft.metric_name}
                  onChange={(e) => setTargetDraft({ ...targetDraft, metric_name: e.target.value })}
                  placeholder="bijv. volgers"
                />
              </label>
              <label>
                Soort
                <select
                  value={targetDraft.target_kind}
                  onChange={(e) => setTargetDraft({ ...targetDraft, target_kind: e.target.value })}
                >
                  <option value="absolute">absoluut (bereiken)</option>
                  <option value="growth">groei (erbij)</option>
                </select>
              </label>
              <label>
                Doelwaarde
                <input
                  value={targetDraft.target_value}
                  onChange={(e) => setTargetDraft({ ...targetDraft, target_value: e.target.value })}
                />
              </label>
              <label>
                Jaar
                <input
                  value={targetDraft.period_year}
                  onChange={(e) => setTargetDraft({ ...targetDraft, period_year: e.target.value })}
                />
              </label>
            </div>
            <button
              className="primary"
              type="button"
              onClick={() => {
                if (!String(targetDraft.metric_name || "").trim()) {
                  setError("Vul een metric in voor het doel.");
                  return;
                }
                api(`/api/clients/${client.id}/targets`, {
                  method: "POST",
                  body: {
                    ...targetDraft,
                    baseline_value:
                      targetDraft.baseline_value === "" ? null : Number(targetDraft.baseline_value),
                    target_value:
                      targetDraft.target_value === "" ? null : Number(targetDraft.target_value),
                    period_year:
                      targetDraft.period_year === "" ? null : Number(targetDraft.period_year),
                    period_quarter:
                      targetDraft.period_quarter === "" ? null : Number(targetDraft.period_quarter),
                  },
                })
                  .then(() => reload())
                  .then(() => setNotice("Doel opgeslagen."))
                  .catch((exc) => setError(exc.message));
              }}
            >
              Doel opslaan
            </button>
            {(data.targets || []).length === 0 ? <p className="hint">Nog geen doelen.</p> : null}
            {(data.targets || []).map((target) => (
              <article className="card stack" key={target.id}>
                <p>
                  <strong>
                    {target.platform || "—"} · {target.metric_name}
                  </strong>{" "}
                  ({target.target_kind}) {target.period_year}
                  {target.period_quarter ? ` Q${target.period_quarter}` : ""}
                </p>
                <p className="hint">
                  Basis {target.baseline_value ?? "—"} → doel {target.target_value ?? "—"} {target.unit}.
                  Voortgang: <strong>{target.progress?.status || "nog niet meetbaar"}</strong>
                </p>
                <ManualMeasure clientId={client.id} target={target} onSaved={reload} onError={setError} />
              </article>
            ))}
          </section>

          <section className="card stack specialist-findings">
            <h3>Bevindingen & conclusies</h3>
            <label>
              Bevindingen
              <textarea
                rows={4}
                value={findingsText}
                onChange={(e) => setField("specialist_findings", e.target.value)}
              />
            </label>
            <label>
              Conclusies
              <textarea
                rows={4}
                value={conclusionsText}
                onChange={(e) => setField("specialist_conclusions", e.target.value)}
              />
            </label>
          </section>
        </>
      ) : null}

      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
    </div>
  );
}

function StrategyActions({
  clientId,
  canvaUrl,
  pdfBlob,
  pdfName,
  strategyPdf,
  onCanvaUrl,
  onPdfStored,
  onError,
}) {
  const [draftCanva, setDraftCanva] = useState(canvaUrl || "");
  const [reuploadBusy, setReuploadBusy] = useState(false);
  useEffect(() => {
    setDraftCanva(canvaUrl || "");
  }, [canvaUrl]);

  const storedAvailable = Boolean(strategyPdf?.available);
  const needsReupload = !storedAvailable && !pdfBlob && Boolean(strategyPdf?.needs_reupload);
  const hasPdfFile = storedAvailable || Boolean(pdfBlob);
  const resolvedName = pdfName || strategyPdf?.filename || "strategie.pdf";

  async function fetchStoredPdfBlob(disposition = "inline") {
    const query = new URLSearchParams({ disposition });
    if (strategyPdf?.file_ref) query.set("ref", strategyPdf.file_ref);
    const response = await fetch(
      apiUrl(`/api/clients/${clientId}/strategy/pdf?${query.toString()}`),
      { credentials: "include" },
    );
    if (!response.ok) {
      let detail = "PDF openen mislukt.";
      try {
        const payload = await response.json();
        if (payload?.detail) detail = payload.detail;
      } catch {
        // ignore non-JSON body
      }
      throw new Error(detail);
    }
    return response.blob();
  }

  return (
    <section className="card stack">
      <h3>Bronnen & acties</h3>
      <p className="hint">
        Canva is optioneel en blokkeert afronden niet. Acties verschijnen als er een link of
        opgeslagen PDF beschikbaar is.
      </p>
      <label>
        Canva-link (optioneel)
        <input
          value={draftCanva}
          onChange={(e) => setDraftCanva(e.target.value)}
          onBlur={() => {
            const next = String(draftCanva || "").trim();
            if (next !== String(canvaUrl || "").trim()) onCanvaUrl(next);
          }}
          placeholder="https://www.canva.com/design/…"
        />
      </label>
      {hasPdfFile ? (
        <p className="hint">
          Opgeslagen PDF bij deze klant: <strong>{resolvedName}</strong>
        </p>
      ) : null}
      {needsReupload ? (
        <p className="hint">
          Alleen bestandsnaam bekend (<strong>{strategyPdf.filename}</strong>) — voeg het originele
          PDF-bestand opnieuw toe om te bekijken of downloaden.
        </p>
      ) : null}
      <div className="row-actions wrap">
        {canvaUrl ? (
          <a className="button secondary" href={canvaUrl} target="_blank" rel="noreferrer">
            Openen in Canva
          </a>
        ) : null}
        {hasPdfFile ? (
          <>
            <button
              type="button"
              className="secondary"
              onClick={async () => {
                try {
                  if (storedAvailable) {
                    const blob = await fetchStoredPdfBlob("inline");
                    const url = URL.createObjectURL(blob);
                    window.open(url, "_blank", "noopener,noreferrer");
                    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
                    return;
                  }
                  if (pdfBlob) {
                    const url = URL.createObjectURL(pdfBlob);
                    window.open(url, "_blank", "noopener,noreferrer");
                    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
                  }
                } catch (exc) {
                  onError?.(dutchSaveError(exc));
                }
              }}
            >
              PDF bekijken
            </button>
            <button
              type="button"
              className="secondary"
              onClick={async () => {
                try {
                  const blob = storedAvailable
                    ? await fetchStoredPdfBlob("attachment")
                    : pdfBlob;
                  if (!blob) return;
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement("a");
                  anchor.href = url;
                  anchor.download = resolvedName;
                  anchor.click();
                  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
                } catch (exc) {
                  onError?.(dutchSaveError(exc));
                }
              }}
            >
              PDF downloaden
            </button>
          </>
        ) : null}
        {needsReupload ? (
          <label className="secondary file-btn">
            {reuploadBusy ? "Bezig…" : "PDF opnieuw toevoegen"}
            <input
              type="file"
              accept="application/pdf,.pdf"
              hidden
              disabled={reuploadBusy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                const body = new FormData();
                body.append("file", file);
                setReuploadBusy(true);
                api(`/api/clients/${clientId}/strategy/pdf`, {
                  method: "POST",
                  body,
                  raw: true,
                })
                  .then((payload) => {
                    if (payload?.persist && payload.persist.durable !== true) {
                      throw new Error(
                        payload.persist.error ||
                          "Externe opslag bevestigde de PDF-opslag niet.",
                      );
                    }
                    onPdfStored?.(payload, { blob: file, name: file.name });
                  })
                  .catch((exc) => onError?.(dutchSaveError(exc)))
                  .finally(() => {
                    setReuploadBusy(false);
                    event.target.value = "";
                  });
              }}
            />
          </label>
        ) : null}
        {!canvaUrl && !hasPdfFile && !needsReupload ? (
          <p className="muted">Nog geen Canva-link of opgeslagen PDF voor deze klant.</p>
        ) : null}
      </div>
    </section>
  );
}

function StrategyImportPanel({ clientId, onStaged, onError }) {
  const [canvaUrl, setCanvaUrl] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [localFile, setLocalFile] = useState(null);

  return (
    <section className="card stack">
      <h3>Voorstel inlezen (Canva / PDF)</h3>
      <p className="hint">
        Eerst een preview. Daarna staat het klaar als voorstel — pas na jouw goedkeuring wordt het
        strategie. Bestaande handmatige antwoorden blijven staan.
      </p>
      <div className="row-actions wrap">
        <label style={{ flex: 1, minWidth: "16rem" }}>
          Canva-link
          <input
            value={canvaUrl}
            onChange={(e) => setCanvaUrl(e.target.value)}
            placeholder="https://www.canva.com/design/…"
          />
        </label>
        <button
          className="secondary"
          type="button"
          disabled={busy || !canvaUrl.trim()}
          onClick={() => {
            setBusy(true);
            setLocalFile(null);
            api(`/api/clients/${clientId}/strategy/import/canva-preview`, {
              method: "POST",
              body: { url: canvaUrl.trim() },
            })
              .then(setPreview)
              .catch((exc) => onError(exc.message))
              .finally(() => setBusy(false));
          }}
        >
          Canva-link controleren
        </button>
        <label className="secondary file-btn">
          PDF kiezen
          <input
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              const body = new FormData();
              body.append("file", file);
              setBusy(true);
              setLocalFile(file);
              api(`/api/clients/${clientId}/strategy/import/pdf-preview`, {
                method: "POST",
                body,
                raw: true,
              })
                .then(setPreview)
                .catch((exc) => onError(exc.message))
                .finally(() => {
                  setBusy(false);
                  event.target.value = "";
                });
            }}
          />
        </label>
      </div>
      {preview ? (
        <div className="stack">
          <p className="banner">
            Bron: <strong>{preview.source_kind}</strong>
            {preview.filename ? ` · ${preview.filename}` : ""}
            {preview.canva_url ? (
              <>
                {" "}
                ·{" "}
                <a href={preview.canva_url} target="_blank" rel="noreferrer">
                  Openen in Canva
                </a>
              </>
            ) : null}
          </p>
          {preview.note ? <p className="hint">{preview.note}</p> : null}
          {preview.excerpt ? (
            <pre className="hint" style={{ whiteSpace: "pre-wrap", maxHeight: "12rem", overflow: "auto" }}>
              {preview.excerpt}
            </pre>
          ) : null}
          {(preview.filled_keys || []).length ? (
            <p className="hint">Gevonden velden: {preview.filled_keys.join(", ")}</p>
          ) : null}
          <div className="row-actions">
            <button
              className="primary"
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                api(`/api/clients/${clientId}/strategy/import/apply`, {
                  method: "POST",
                  body: {
                    proposed: preview.proposed || {},
                    preserve_manual: true,
                    stage_only: true,
                    source_kind: preview.source_kind || "",
                    filename: preview.filename || localFile?.name || "",
                    file_ref: preview.file_ref || "",
                  },
                })
                  .then((payload) => {
                    if (payload?.persist && payload.persist.durable !== true) {
                      throw new Error(
                        payload.persist.error || "Externe opslag bevestigde de PDF-import niet.",
                      );
                    }
                    setPreview(null);
                    onStaged(payload, localFile ? { blob: localFile, name: localFile.name } : null);
                  })
                  .catch((exc) => onError(exc.message))
                  .finally(() => setBusy(false));
              }}
            >
              Klaarzetten ter controle
            </button>
            <button className="secondary" type="button" onClick={() => setPreview(null)}>
              Annuleren
            </button>
          </div>
        </div>
      ) : null}
    </section>
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

  if (!overview) return <p className="muted">Figma-planning laden…</p>;

  const items = overview.items || [];
  const connection = overview.connection || {};

  return (
    <div className="stack">
      <section className="card stack">
        <h3>Figma-planning</h3>
        <p className="hint">
          Koppel het Figma-bestand van deze klant. Handmatige classificaties worden niet automatisch
          overschreven.
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
                body: { file_key: fileKey, file_name: "" },
              })
                .then(() => reload())
                .then(() => onNotice("Figma-bestand gekoppeld."))
                .catch((exc) => onError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Bestand koppelen
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
                    `Sync klaar: ${payload.stats?.inserted || 0} nieuw, ${payload.stats?.updated || 0} bijgewerkt.`,
                  );
                })
                .catch((exc) => onError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            Sync vanuit Figma
          </button>
        </div>
        <p className="hint">
          Gekoppeld: {connection.linked ? "ja" : "nee"}
          {connection.source_url ? (
            <>
              {" "}
              ·{" "}
              <a href={connection.source_url} target="_blank" rel="noreferrer">
                Openen in Figma
              </a>
            </>
          ) : null}
        </p>
      </section>

      <section className="card stack">
        <h3>Geïmporteerde planningitems</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Periode</th>
                <th>Code</th>
                <th>Soort</th>
                <th>Format</th>
                <th>Pilaar</th>
                <th>Hook</th>
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
                  <td>{item.format_usable ? item.format_raw : <span className="muted">niet bruikbaar</span>}</td>
                  <td>{item.pillar_usable ? item.pillar_raw : <span className="muted">niet bruikbaar</span>}</td>
                  <td title={item.hook_raw || ""}>
                    {item.hook_usable ? (item.hook_raw || "").slice(0, 48) : <span className="muted">niet bruikbaar</span>}
                  </td>
                  <td>
                    {item.linked_post_id ? `post #${item.linked_post_id}` : item.link_status || "ongelinkt"}
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
        {!items.length ? <p className="hint">Nog geen planningitems voor deze klant.</p> : null}
      </section>

      {selectedItemId ? (
        <section className="card stack">
          <h3>Koppel item #{selectedItemId} aan een post</h3>
          <div className="row-actions wrap">
            <label>
              Post-ID
              <input value={postId} onChange={(e) => setPostId(e.target.value)} placeholder="bijv. 8" />
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
              Wijzigingen bekijken
            </button>
          </div>
          {suggestions.length ? (
            <ul className="plain-list">
              {suggestions.map((s) => (
                <li key={s.post_id}>
                  <button type="button" className="secondary" onClick={() => setPostId(String(s.post_id))}>
                    Gebruik post #{s.post_id}
                  </button>{" "}
                  {s.platform} · {s.published_at || "geen datum"}
                </li>
              ))}
            </ul>
          ) : null}
          {preview ? (
            <div className="stack">
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
                      "Ik bevestig dat Figma en de post een andere contentsoort hebben."}
                  </span>
                </label>
              ) : null}
              <div className="row-actions wrap">
                <button
                  className="primary"
                  type="button"
                  disabled={busy || (preview.content_kind_compare?.mismatch && !acceptKindMismatch)}
                  onClick={() => {
                    setBusy(true);
                    api(`/api/clients/${clientId}/figma-planning/items/${selectedItemId}/link`, {
                      method: "POST",
                      body: {
                        post_id: Number(postId),
                        confirm: true,
                        accept_content_kind_mismatch: Boolean(
                          preview.content_kind_compare?.mismatch && acceptKindMismatch,
                        ),
                      },
                    })
                      .then(() => reload())
                      .then(() => {
                        onNotice(`Item #${selectedItemId} gekoppeld aan post #${postId}.`);
                        setPreview(null);
                        setAcceptKindMismatch(false);
                      })
                      .catch((exc) => onError(exc.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Koppeling bevestigen
                </button>
                <button className="secondary" type="button" onClick={() => setPreview(null)}>
                  Annuleren
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
  const [source, setSource] = useState("handmatig");
  return (
    <div className="row-actions wrap">
      <input type="date" value={measuredAt} onChange={(e) => setMeasuredAt(e.target.value)} title="Gemeten op" />
      <input placeholder="meting" value={value} onChange={(e) => setValue(e.target.value)} />
      <input placeholder="bron" value={source} onChange={(e) => setSource(e.target.value)} />
      <button
        className="secondary"
        type="button"
        onClick={() => {
          if (value === "") {
            onError("Vul een meetwaarde in.");
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
        Meting toevoegen
      </button>
    </div>
  );
}
