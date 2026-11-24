import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AiSettingsPage({ onOpenPrompts }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [postId, setPostId] = useState("");
  const [analyses, setAnalyses] = useState([]);
  const [openAnalysis, setOpenAnalysis] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/ai-status")
      .then(setStatus)
      .catch((exc) => setError(exc.message));
    api("/api/clients")
      .then((payload) => {
        const list = payload.clients || [];
        setClients(list);
        if (list[0]) setClientId(String(list[0].id));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!clientId) return;
    api(`/api/clients/${clientId}/ai-analyses`)
      .then((payload) => setAnalyses(payload.analyses || []))
      .catch(() => setAnalyses([]));
  }, [clientId]);

  if (error && !status) return <p className="banner error">{error}</p>;
  if (!status) return <p className="muted">Laden…</p>;

  const gemini = status.gemini || {};
  const claude = status.claude || {};
  const prompts = status.analysis_prompts || {};
  const taskProviders = status.task_providers || {};

  return (
    <div className="stack">
      <p className="hint">
        AI-koppelingen: Claude voor postfeedback; Gemini voor klantrapport en trendrapport.
        Bewerkbare prompts hieronder. Deze pagina start geen AI-aanvraag. Key values worden niet getoond.
      </p>

      {status.active_provider ? (
        <p className="banner">Actieve configuratie: {status.active_provider}</p>
      ) : (
        <p className="banner error">
          Geen actieve AI-configuratie (zet CLAUDE_API_KEY voor postfeedback en AI_* voor rapporten).
        </p>
      )}

      {status.persist ? (
        <section className="card stack">
          <h3>Blijvende opslag (Render Free)</h3>
          <p className={status.persist.enabled ? "banner" : "banner"}>
            {status.persist.enabled
              ? `Remote backup actief${status.persist.url_host ? ` · ${status.persist.url_host}` : ""}${
                  status.persist.last_pushed_at ? ` · laatste push ${status.persist.last_pushed_at}` : ""
                }`
              : status.persist.free_tier_note ||
                "Remote persist uit. Zonder disk verdwijnen prompts/posts bij herstart."}
          </p>
          {(status.persist.missing || []).length ? (
            <p className="hint">Nog nodig: {(status.persist.missing || []).join(", ")}</p>
          ) : null}
          {status.oauth_redirect_uri ? (
            <p className="hint">Meta OAuth-callback: {status.oauth_redirect_uri}</p>
          ) : null}
        </section>
      ) : null}

      {taskProviders.post_analysis || taskProviders.client_report ? (
        <section className="card stack">
          <h3>Aanbieder per taak</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Taak</th>
                  <th>Aanbieder</th>
                  <th>Model</th>
                </tr>
              </thead>
              <tbody>
                {["post_analysis", "client_report", "trend_report"].map((key) => {
                  const item = taskProviders[key] || {};
                  const primary = item.primary || {};
                  return (
                    <tr key={key}>
                      <td>{item.label || key}</td>
                      <td>{primary.provider || "—"}</td>
                      <td>{primary.model || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="card stack">
        <h3>Gemini API (rapporten)</h3>
        <p className={gemini.configured ? "banner" : "banner error"}>
          {gemini.configured
            ? `Gekoppeld · model ${gemini.model} · host ${gemini.base_host || "—"}`
            : "Nog niet volledig ingesteld (AI_BASE_URL / AI_API_KEY / AI_MODEL). Vraag een beheerder om de serverinstellingen te controleren."}
        </p>
        {(gemini.used_for || []).length ? (
          <ul className="plain-list">
            {gemini.used_for.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Instelling</th>
                <th>Stand</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>AI_BASE_URL</td>
                <td>{status.has_base_url ? `aanwezig (${status.base_host || "—"})` : "ontbreekt"}</td>
              </tr>
              <tr>
                <td>AI_API_KEY</td>
                <td>{status.has_api_key ? "aanwezig" : "ontbreekt"}</td>
              </tr>
              <tr>
                <td>AI_MODEL</td>
                <td>{status.model || "ontbreekt"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3>Claude API (postfeedback)</h3>
        <p className={claude.configured ? "banner" : "banner error"}>
          {claude.configured
            ? `Gekoppeld · model ${claude.model} · host ${claude.base_host}`
            : `Vereist voor postfeedback. Zet ${claude.missing_setting || "CLAUDE_API_KEY"} server-side (${claude.env_file_hint || "Render env / .env"}). Gemini-rapporten werken zonder Claude.`}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Instelling</th>
                <th>Stand</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Actieve sleutelvariabele</td>
                <td>
                  {claude.key_variable
                    ? `${claude.key_variable} (${claude.key_source === "dotenv" ? ".env-bestand" : claude.key_source === "process" ? "procesomgeving" : "onbekend"})`
                    : "geen"}
                </td>
              </tr>
              <tr>
                <td>CLAUDE_API_KEY / ANTHROPIC_API_KEY</td>
                <td>{claude.has_api_key ? "aanwezig" : "ontbreekt"}</td>
              </tr>
              <tr>
                <td>CLAUDE_MODEL</td>
                <td>{claude.model || "claude-sonnet-4-5 (default)"}</td>
              </tr>
            </tbody>
          </table>
        </div>
        {(claude.notes || []).map((note) => (
          <p className="hint" key={note}>
            {note}
          </p>
        ))}
      </section>

      <section className="card stack">
        <h3>Maaike-analyseprompts</h3>
        <p className={prompts.ready ? "banner" : "banner error"}>
          {prompts.ready
            ? `Promptversie ${prompts.prompt_version} geladen${prompts.root ? ` · ${prompts.root}` : ""}.`
            : `Ontbrekende bestanden: ${(prompts.missing_files || []).join(", ") || "onbekend"}`}
        </p>
        <ul className="plain-list">
          {Object.entries(prompts.files || {}).map(([name, meta]) => (
            <li key={name}>
              {name}: {meta.loaded ? `${meta.chars} tekens` : "ONTBREEKT"}
            </li>
          ))}
        </ul>
        {prompts.data_expectations?.single_post_limitation ? (
          <p className="hint">{prompts.data_expectations.single_post_limitation}</p>
        ) : null}
      </section>

      <section className="card stack">
        <h3>Prompts voor alle klanten</h3>
        <p className="hint">
          Postfeedback, performance-analyse, algemene instructies, kwaliteitsstandaard,
          trend- en klantrapporten bewerk je op de centrale Prompts-pagina. Opgeslagen tekst
          geldt voor elke klant; klantstrategie en cijfers blijven aparte context.
        </p>
        {onOpenPrompts ? (
          <button className="primary" type="button" onClick={onOpenPrompts}>
            Prompts openen
          </button>
        ) : (
          <p className="hint">Ga naar Instellingen → Prompts.</p>
        )}
      </section>

      <section className="card stack">
        <h3>Losse Claude-berichtanalyse</h3>
        <p className="hint">
          Gebruikt de Social Agent-bestanden plus echte berichtgegevens. Geen automatische
          herhalingen. Het resultaat wordt opgeslagen en kun je opnieuw openen.
        </p>
        <div className="row-actions wrap">
          <label>
            Klant
            <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Bericht-ID
            <input value={postId} onChange={(e) => setPostId(e.target.value)} placeholder="bijv. 901" />
          </label>
          <button
            className="primary"
            type="button"
            disabled={busy || !clientId || !postId}
            onClick={() => {
              setBusy(true);
              setError("");
              setNotice("");
              api(`/api/clients/${clientId}/posts/${postId}/claude-analyze`, { method: "POST", body: {} })
                .then(async (payload) => {
                  setOpenAnalysis(payload.analysis);
                  if (payload.analysis?.status === "completed") {
                    setNotice(`Analyse opgeslagen #${payload.analysis?.id}`);
                  } else {
                    setError(
                      payload.analysis?.error_text ||
                        `Analyse #${payload.analysis?.id} is mislukt (${payload.analysis?.status}). Controleer de Claude-sleutel of kies een ander bericht.`,
                    );
                  }
                  const list = await api(`/api/clients/${clientId}/ai-analyses`);
                  setAnalyses(list.analyses || []);
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            {busy ? "Bezig…" : "Claude-analyse starten"}
          </button>
        </div>
        <h4>Opgeslagen analyses</h4>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Bericht</th>
                <th>Stand</th>
                <th>Model</th>
                <th>Beoordeling</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {analyses.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>{a.post_id}</td>
                  <td>{a.status}</td>
                  <td>{a.model}</td>
                  <td>{a.rating_text || "—"}</td>
                  <td>
                    <button
                      className="secondary"
                      type="button"
                      onClick={() => {
                        api(`/api/clients/${clientId}/ai-analyses/${a.id}`)
                          .then((payload) => setOpenAnalysis(payload.analysis))
                          .catch((exc) => setError(exc.message));
                      }}
                    >
                      Openen
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!analyses.length ? <p className="hint">Nog geen opgeslagen Claude-analyses voor deze klant.</p> : null}
        {openAnalysis ? (
          <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(
              {
                id: openAnalysis.id,
                status: openAnalysis.status,
                model: openAnalysis.model,
                prompt_version: openAnalysis.prompt_version,
                rating_text: openAnalysis.rating_text,
                insight_text: openAnalysis.insight_text,
                action_text: openAnalysis.action_text,
                usage: openAnalysis.usage,
                started_at: openAnalysis.started_at,
                finished_at: openAnalysis.finished_at,
                error_text: openAnalysis.error_text,
              },
              null,
              2,
            )}
          </pre>
        ) : null}
      </section>

      {(status.notes || []).map((note) => (
        <p key={note} className="hint">
          {note}
        </p>
      ))}
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
    </div>
  );
}

