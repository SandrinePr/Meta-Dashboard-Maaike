import { useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * Global prompts for all clients — view/edit/save/cancel with confirmation.
 */
export default function PromptsPage({ onNotice, onError }) {
  const [data, setData] = useState(null);
  const [editingKey, setEditingKey] = useState("");
  const [draft, setDraft] = useState({ body_text: "", version_tag: "" });
  const [busyKey, setBusyKey] = useState("");
  const [localNotice, setLocalNotice] = useState("");
  const [localError, setLocalError] = useState("");

  function load() {
    return api("/api/prompt-settings").then((payload) => {
      setData(payload);
      return payload;
    });
  }

  useEffect(() => {
    load().catch((exc) => {
      setLocalError(exc.message);
      onError?.(exc.message);
    });
  }, []);

  function beginEdit(prompt) {
    setEditingKey(prompt.prompt_key);
    setDraft({
      body_text: prompt.body_text || "",
      version_tag: prompt.version_tag || "",
    });
    setLocalNotice("");
    setLocalError("");
  }

  function cancelEdit() {
    setEditingKey("");
    setDraft({ body_text: "", version_tag: "" });
  }

  if (localError && !data) return <p className="banner error">{localError}</p>;
  if (!data) return <p className="muted">Prompts laden…</p>;

  return (
    <div className="stack prompts-page">
      <p className="hint">
        Centrale prompts voor <strong>alle klanten</strong>. Klantprompts (tone of voice en
        strategiecontext) regel je per klant in <strong>Klant inrichten</strong>; die blijven
        klantspecifieke context bij elke analyse of rapport. {data.note}
      </p>
      {(data.conflicts || []).length ? (
        <div className="banner warn-soft">
          {(data.conflicts || []).map((line) => (
            <p key={line} style={{ margin: "0.25rem 0" }}>
              {line}
            </p>
          ))}
        </div>
      ) : null}
      {localNotice ? <p className="banner">{localNotice}</p> : null}
      {localError ? <p className="banner error">{localError}</p> : null}

      {(data.prompts || []).map((prompt) => {
        const isEditing = editingKey === prompt.prompt_key;
        return (
          <article className="card stack prompt-card" key={prompt.prompt_key}>
            <div>
              <h3 style={{ margin: 0 }}>{prompt.label}</h3>
              <p className="hint" style={{ margin: "0.35rem 0 0" }}>
                {prompt.description}
              </p>
              <p className="hint" style={{ margin: "0.25rem 0 0" }}>
                Gebruik: {prompt.used_for || "—"} · bron {prompt.source}
                {prompt.file_name ? ` · bestand ${prompt.file_name}` : ""}
                {prompt.updated_at
                  ? ` · laatste wijziging ${prompt.updated_at}${
                      prompt.updated_by ? ` door ${prompt.updated_by}` : ""
                    }`
                  : " · nog geen dashboard-override"}
              </p>
            </div>

            {isEditing ? (
              <>
                <label>
                  Versietag
                  <input
                    value={draft.version_tag}
                    onChange={(e) => setDraft((cur) => ({ ...cur, version_tag: e.target.value }))}
                  />
                </label>
                <label>
                  Volledige prompttekst
                  <textarea
                    className="prompt-textarea"
                    rows={16}
                    value={draft.body_text}
                    onChange={(e) => setDraft((cur) => ({ ...cur, body_text: e.target.value }))}
                  />
                </label>
                <div className="row-actions wrap">
                  <button
                    className="primary"
                    type="button"
                    disabled={busyKey === prompt.prompt_key}
                    onClick={() => {
                      setBusyKey(prompt.prompt_key);
                      setLocalError("");
                      api(`/api/prompt-settings/${prompt.prompt_key}`, {
                        method: "PUT",
                        body: {
                          body_text: draft.body_text,
                          version_tag: draft.version_tag,
                          updated_by: "Maaike",
                        },
                      })
                        .then(async (payload) => {
                          setData(payload);
                          const saved = (payload.prompts || []).find(
                            (p) => p.prompt_key === prompt.prompt_key,
                          );
                          const msg =
                            `${prompt.label} opgeslagen` +
                            (saved?.updated_at ? ` · ${saved.updated_at}` : "") +
                            (payload.persist?.pushed ? " · remote backup bijgewerkt" : "");
                          setLocalNotice(msg);
                          onNotice?.(msg);
                          cancelEdit();
                        })
                        .catch((exc) => {
                          setLocalError(exc.message);
                          onError?.(exc.message);
                        })
                        .finally(() => setBusyKey(""));
                    }}
                  >
                    {busyKey === prompt.prompt_key ? "Opslaan…" : "Opslaan"}
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busyKey === prompt.prompt_key}
                    onClick={cancelEdit}
                  >
                    Annuleren
                  </button>
                </div>
              </>
            ) : (
              <>
                <pre className="prompt-preview">{prompt.body_text || "(leeg)"}</pre>
                <div className="row-actions wrap">
                  <button className="primary" type="button" onClick={() => beginEdit(prompt)}>
                    Bewerken
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busyKey === prompt.prompt_key || prompt.source === "files" || prompt.source === "files_composed"}
                    title={
                      prompt.source === "dashboard_override"
                        ? "Terug naar bestands-/standaardtekst"
                        : "Geen override om te resetten"
                    }
                    onClick={() => {
                      setBusyKey(prompt.prompt_key);
                      setLocalError("");
                      api(`/api/prompt-settings/${prompt.prompt_key}`, { method: "DELETE" })
                        .then((payload) => {
                          setData(payload);
                          const msg = `${prompt.label} teruggezet naar standaard.`;
                          setLocalNotice(msg);
                          onNotice?.(msg);
                        })
                        .catch((exc) => {
                          setLocalError(exc.message);
                          onError?.(exc.message);
                        })
                        .finally(() => setBusyKey(""));
                    }}
                  >
                    Reset naar standaard
                  </button>
                </div>
              </>
            )}
          </article>
        );
      })}
    </div>
  );
}
