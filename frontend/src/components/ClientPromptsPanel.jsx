import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

/** Strategy answer keys that act as this client's AI prompt context. */
export const CLIENT_PROMPT_KEYS = [
  "tone_of_voice",
  "bedrijfsomschrijving",
  "onderscheidend_vermogen",
  "gewenste_socialresultaten",
  "platforms",
];

const CLIENT_PROMPT_KEY_SET = new Set(CLIENT_PROMPT_KEYS);

function dutchSaveError(exc) {
  const raw = String(exc?.message || exc || "").trim();
  if (!raw) return "Opslaan lukte niet";
  if (/failed to fetch|networkerror|load failed/i.test(raw)) return "Opslaan lukte niet";
  return raw || "Opslaan lukte niet";
}

/**
 * Same klantprompts fields/storage as Klant inrichten → Klantprompts.
 */
export default function ClientPromptsPanel({
  client,
  canEdit = true,
  onNotice,
  onError,
}) {
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [missing, setMissing] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState("idle");
  const answersRef = useRef({});
  const timerRef = useRef(null);
  const clientId = client?.id;

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const payload = await api(`/api/clients/${clientId}/strategy`);
      const nextAnswers = { ...(payload.start_answers || {}) };
      answersRef.current = nextAnswers;
      setAnswers(nextAnswers);
      setQuestions(payload.questions || []);
      setMissing(payload.missing_required || []);
    } catch (exc) {
      onError?.(dutchSaveError(exc));
    } finally {
      setLoading(false);
    }
  }, [clientId, onError]);

  useEffect(() => {
    answersRef.current = {};
    setAnswers({});
    setQuestions([]);
    setMissing([]);
    load();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [clientId, load]);

  async function persist(nextAnswers) {
    if (!clientId || !canEdit) return;
    setSaveStatus("saving");
    try {
      const payload = await api(`/api/clients/${clientId}/strategy`, {
        method: "PUT",
        body: { start_answers: nextAnswers },
      });
      const merged = { ...(payload.start_answers || nextAnswers) };
      answersRef.current = merged;
      setAnswers(merged);
      setMissing(payload.missing_required || []);
      setQuestions(payload.questions || questions);
      setSaveStatus("saved");
    } catch (exc) {
      setSaveStatus("error");
      onError?.(dutchSaveError(exc));
    }
  }

  function scheduleSave(nextAnswers) {
    if (!canEdit) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      persist(nextAnswers).catch(() => {});
    }, 700);
  }

  function setAnswer(key, value) {
    const next = { ...answersRef.current, [key]: value };
    answersRef.current = next;
    setAnswers(next);
    scheduleSave(next);
  }

  if (!client) {
    return (
      <p className="banner">
        Kies links een klant om de klantprompts te bekijken of aan te passen.
      </p>
    );
  }

  const promptQuestions = (questions || []).filter((q) => CLIENT_PROMPT_KEY_SET.has(q.key));

  return (
    <section className="card stack" id="settings-client-prompts" aria-label="Klantprompts">
      <div className="setup-block-head">
        <h3 style={{ margin: 0 }}>
          Klantprompts{" "}
          <span className="badge badge-active">Alleen {client.name}</span>
        </h3>
        <span className="hint">
          {saveStatus === "saving"
            ? "Opslaan…"
            : saveStatus === "saved"
              ? "Opgeslagen"
              : saveStatus === "error"
                ? "Opslaan mislukt"
                : canEdit
                  ? "Wijzigingen worden automatisch bewaard"
                  : "Wijzigingen worden automatisch bewaard"}
        </span>
      </div>
      <p className="banner">
        Deze prompts gelden voor <strong>{client.name}</strong>. Wissel links van klant om prompts
        van een andere klant te zien. Algemene AI-prompts (voor alle klanten) staan bij{" "}
        <strong>Technisch beheer → Prompts</strong>.
      </p>
      <p className="hint">
        Zelfde velden en opslag als bij <strong>Klant inrichten → Klantprompts</strong>.
      </p>
      {loading ? <p className="muted">Prompts laden…</p> : null}
      {!loading && !promptQuestions.length ? (
        <p className="muted">Geen promptvelden beschikbaar.</p>
      ) : null}
      {promptQuestions.map((question) => {
        const required = Boolean(question.required_for_complete);
        const open = (missing || []).includes(question.key);
        return (
          <label key={question.key}>
            {question.label}{" "}
            {required ? (
              <span className="required-mark">verplicht</span>
            ) : (
              <span className="muted">optioneel</span>
            )}
            {open ? <span className="setup-inline-todo"> · Nog invullen</span> : null}
            <textarea
              rows={3}
              value={answers[question.key] || ""}
              disabled={!canEdit}
              readOnly={!canEdit}
              onChange={(e) => setAnswer(question.key, e.target.value)}
              onBlur={() => {
                if (canEdit) persist(answersRef.current).catch(() => {});
              }}
              placeholder={question.short_question || ""}
            />
          </label>
        );
      })}
      {canEdit ? null : (
        <p className="hint">Je mag deze prompts niet bewerken met je huidige rol.</p>
      )}
      {onNotice && canEdit ? (
        <p className="hint">Tip: na aanpassen even wachten tot “Opgeslagen” verschijnt, of het veld verlaten.</p>
      ) : null}
    </section>
  );
}
