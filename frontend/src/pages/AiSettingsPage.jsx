import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AiSettingsPage() {
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
  if (!status) return <p className="muted">Loading…</p>;

  const gemini = status.gemini || {};
  const claude = status.claude || {};
  const prompts = status.analysis_prompts || {};
  const taskProviders = status.task_providers || {};

  return (
    <div className="stack">
      <p className="hint">
        AI Connections: status of API connections (Gemini and Claude). This page does not start an analysis until you
        explicitly click analyse. Key values are not shown.
      </p>

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
        <h3>Gemini API</h3>
        <p className={gemini.configured ? "banner" : "banner error"}>
          {gemini.configured
            ? `Connected · model ${gemini.model} · host ${gemini.base_host || "—"}`
            : "Not fully configured (AI_BASE_URL / AI_API_KEY / AI_MODEL)."}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Setting</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>AI_BASE_URL</td>
                <td>{status.has_base_url ? `present (${status.base_host || "—"})` : "missing"}</td>
              </tr>
              <tr>
                <td>AI_API_KEY</td>
                <td>{status.has_api_key ? "present" : "missing"}</td>
              </tr>
              <tr>
                <td>AI_MODEL</td>
                <td>{status.model || "missing"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3>Claude API</h3>
        <p className={claude.configured ? "banner" : "banner error"}>
          {claude.configured
            ? `Connected · model ${claude.model} · host ${claude.base_host}`
            : `Not connected — set ${claude.missing_setting || "CLAUDE_API_KEY"} in ${claude.env_file_hint || ".env"}.`}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Setting</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Active key variable</td>
                <td>
                  {claude.key_variable
                    ? `${claude.key_variable} (${claude.key_source === "dotenv" ? ".env file" : claude.key_source === "process" ? "process environment" : "unknown"})`
                    : "none"}
                </td>
              </tr>
              <tr>
                <td>CLAUDE_API_KEY / ANTHROPIC_API_KEY</td>
                <td>{claude.has_api_key ? "present" : "missing"}</td>
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
        <h3>Maaike analysis prompts</h3>
        <p className={prompts.ready ? "banner" : "banner error"}>
          {prompts.ready
            ? `Prompt version ${prompts.prompt_version} loaded.`
            : `Missing files: ${(prompts.missing_files || []).join(", ") || "unknown"}`}
        </p>
        <ul className="plain-list">
          {Object.entries(prompts.files || {}).map(([name, meta]) => (
            <li key={name}>
              {name}: {meta.loaded ? `${meta.chars} characters` : "MISSING"}
            </li>
          ))}
        </ul>
        {prompts.data_expectations?.single_post_limitation ? (
          <p className="hint">{prompts.data_expectations.single_post_limitation}</p>
        ) : null}
      </section>

      <EditablePromptsPanel
        onNotice={setNotice}
        onError={setError}
      />

      <section className="card stack">
        <h3>Single Claude post analysis</h3>
        <p className="hint">
          Uses exact Social Agent files + real post data. No automatic retries. The result is
          saved and can be reopened.
        </p>
        <div className="row-actions wrap">
          <label>
            Client
            <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Post ID
            <input value={postId} onChange={(e) => setPostId(e.target.value)} placeholder="e.g. 901" />
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
                    setNotice(`Analysis saved #${payload.analysis?.id}`);
                  } else {
                    setError(
                      payload.analysis?.error_text ||
                        `Analysis #${payload.analysis?.id} failed (${payload.analysis?.status}).`,
                    );
                  }
                  const list = await api(`/api/clients/${clientId}/ai-analyses`);
                  setAnalyses(list.analyses || []);
                })
                .catch((exc) => setError(exc.message))
                .finally(() => setBusy(false));
            }}
          >
            {busy ? "Working…" : "Run Claude analysis"}
          </button>
        </div>
        <h4>Saved analyses</h4>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Post</th>
                <th>Status</th>
                <th>Model</th>
                <th>Rating</th>
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
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!analyses.length ? <p className="hint">No saved Claude analyses for this client yet.</p> : null}
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

function EditablePromptsPanel({ onNotice, onError }) {
  const [data, setData] = useState(null);
  const [busyKey, setBusyKey] = useState("");
  const [drafts, setDrafts] = useState({});

  useEffect(() => {
    api("/api/prompt-settings")
      .then((payload) => {
        setData(payload);
        const next = {};
        for (const p of payload.prompts || []) {
          next[p.prompt_key] = {
            body_text: p.body_text || "",
            version_tag: p.version_tag || "",
          };
        }
        setDrafts(next);
      })
      .catch((exc) => onError(exc.message));
  }, []);

  if (!data) return <p className="muted">Promptinstellingen laden…</p>;

  return (
    <section className="card stack">
      <h3>Bewerkbare prompts (dashboard)</h3>
      <p className="hint">
        Pas postanalyse-, trend- en klantrapportprompts aan. Per gegenereerd rapport blijft de
        gebruikte promptversie bewaard. {data.note}
      </p>
      {(data.prompts || []).map((prompt) => {
        const draft = drafts[prompt.prompt_key] || { body_text: "", version_tag: "" };
        return (
          <article className="card stack" key={prompt.prompt_key}>
            <h4 style={{ marginTop: 0 }}>
              {prompt.label}{" "}
              <span className="hint">
                · {prompt.source} · {prompt.version_tag}
              </span>
            </h4>
            <label>
              Versietag
              <input
                value={draft.version_tag}
                onChange={(e) =>
                  setDrafts((prev) => ({
                    ...prev,
                    [prompt.prompt_key]: { ...draft, version_tag: e.target.value },
                  }))
                }
              />
            </label>
            <label>
              Prompttekst
              <textarea
                rows={8}
                value={draft.body_text}
                onChange={(e) =>
                  setDrafts((prev) => ({
                    ...prev,
                    [prompt.prompt_key]: { ...draft, body_text: e.target.value },
                  }))
                }
              />
            </label>
            <div className="row-actions wrap">
              <button
                className="primary"
                type="button"
                disabled={busyKey === prompt.prompt_key}
                onClick={() => {
                  setBusyKey(prompt.prompt_key);
                  api(`/api/prompt-settings/${prompt.prompt_key}`, {
                    method: "PUT",
                    body: {
                      body_text: draft.body_text,
                      version_tag: draft.version_tag,
                      updated_by: "Maaike",
                    },
                  })
                    .then((payload) => {
                      setData(payload);
                      onNotice(`${prompt.label} opgeslagen.`);
                    })
                    .catch((exc) => onError(exc.message))
                    .finally(() => setBusyKey(""));
                }}
              >
                Opslaan
              </button>
              <button
                className="secondary"
                type="button"
                disabled={busyKey === prompt.prompt_key || prompt.source === "files"}
                onClick={() => {
                  setBusyKey(prompt.prompt_key);
                  api(`/api/prompt-settings/${prompt.prompt_key}`, { method: "DELETE" })
                    .then((payload) => {
                      setData(payload);
                      const restored = (payload.prompts || []).find(
                        (p) => p.prompt_key === prompt.prompt_key,
                      );
                      if (restored) {
                        setDrafts((prev) => ({
                          ...prev,
                          [prompt.prompt_key]: {
                            body_text: restored.body_text || "",
                            version_tag: restored.version_tag || "",
                          },
                        }));
                      }
                      onNotice(`${prompt.label} teruggezet naar bestanden.`);
                    })
                    .catch((exc) => onError(exc.message))
                    .finally(() => setBusyKey(""));
                }}
              >
                Reset naar bestanden
              </button>
            </div>
          </article>
        );
      })}
    </section>
  );
}
