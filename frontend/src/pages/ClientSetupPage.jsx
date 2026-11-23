import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import MetaConnectFlow from "../components/MetaConnectFlow.jsx";
import { metaForDisplay } from "../metaLoginDisplay.js";
import { dashboardClientsUrl, notifyMetaOauthResult } from "../oauthBridge.js";
import { useMetaLogin } from "../useMetaLogin.js";

const STEPS = [
  { id: 1, title: "Klantnaam", short: "Naam" },
  { id: 2, title: "Facebook en Instagram", short: "Koppelen" },
  { id: 3, title: "Inhoud en links", short: "Inhoud" },
  { id: 4, title: "Controleren", short: "Afronden" },
];

function statusClass(kind) {
  if (kind === "ready") return "setup-status is-ready";
  if (kind === "review") return "setup-status is-review";
  if (kind === "todo") return "setup-status is-todo";
  if (kind === "optional") return "setup-status is-optional";
  return "setup-status";
}

function StatusPill({ kind, label }) {
  return <span className={statusClass(kind)}>{label}</span>;
}

/** Mirror backend _pending_user_questions required keys for live form state. */
function computeMissingRequired(answers, questions) {
  const missing = [];
  for (const question of questions || []) {
    if (!question.required_for_complete) continue;
    const key = question.key;
    const value = String(answers?.[key] || "").trim();
    if (!value) {
      missing.push(key);
      continue;
    }
    if (key === "geografische_regio") {
      const lowered = value.toLowerCase();
      if (
        lowered.includes("niet expliciet") ||
        lowered.includes("open") ||
        lowered.includes("onbekend")
      ) {
        missing.push(key);
      }
    }
  }
  return missing;
}

function mergeAnswersPreferLocal(serverAnswers, localAnswers) {
  const merged = { ...(serverAnswers || {}) };
  for (const [key, value] of Object.entries(localAnswers || {})) {
    if (String(value || "").trim()) merged[key] = value;
  }
  return merged;
}

function dutchSaveError(exc) {
  const raw = String(exc?.message || exc || "").trim();
  if (!raw) return "Opslaan mislukt. Controleer je verbinding en probeer opnieuw.";
  if (/failed to fetch|networkerror|load failed/i.test(raw)) {
    return "Opslaan mislukt: geen verbinding met de server. Je invoer blijft staan.";
  }
  return raw.startsWith("Opslaan mislukt") ? raw : `Opslaan mislukt: ${raw}`;
}

export default function ClientSetupPage({
  client,
  isNew = false,
  oauthClientId,
  chooseClient,
  loadClients,
  metaChoice,
  metaError,
  popupReturn = false,
  onMetaReturnHandled,
  onNotice,
  onError,
  onClearMetaError,
  onFinished,
  onFetchPosts,
}) {
  const [step, setStep] = useState(isNew || !client ? 1 : 1);
  const [name, setName] = useState(client?.name || "");
  const [clientId, setClientId] = useState(client?.id || null);
  const [busy, setBusy] = useState("");
  const [localError, setLocalError] = useState("");
  const [localNotice, setLocalNotice] = useState("");
  const [meta, setMeta] = useState(null);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [popupStuck, setPopupStuck] = useState(false);
  const [strategy, setStrategy] = useState(null);
  const [figma, setFigma] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [canvaUrl, setCanvaUrl] = useState("");
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaKey, setFigmaKey] = useState("");
  const [competitorInput, setCompetitorInput] = useState("");
  const [importPreview, setImportPreview] = useState(null);
  const [importNote, setImportNote] = useState("");
  const [targetDraft, setTargetDraft] = useState({
    metric_name: "",
    target_value: "",
    unit: "",
    platform: "instagram",
    notes: "",
  });
  const nameRef = useRef(null);
  const oauthSettledFromProps = useRef(false);
  const answersDraftRef = useRef({});
  const canvaDraftRef = useRef("");
  const figmaUrlDraftRef = useRef("");
  const figmaKeyDraftRef = useRef("");

  // oauthClientId is only for OAuth return; never reuse the sidebar selection for a new client.
  const activeId = clientId || client?.id || (isNew ? null : oauthClientId) || null;
  const returnHref = dashboardClientsUrl({
    clientId: activeId,
    metaChoose: !metaError,
    error: metaError || "",
  });

  const reportError = useCallback(
    (message) => {
      const text = message || "";
      setLocalError(text);
      onError(text);
    },
    [onError],
  );

  const reportNotice = useCallback(
    (message) => {
      const text = message || "";
      setLocalNotice(text);
      onNotice(text);
    },
    [onNotice],
  );

  const refreshMeta = useCallback(
    async (id = activeId) => {
      if (!id) {
        setMeta(null);
        return null;
      }
      const payload = await api(`/api/clients/${id}/meta`);
      setMeta(payload);
      return payload;
    },
    [activeId],
  );

  const {
    busy: loginBusy,
    sameTabUrl,
    pageIndex,
    setPageIndex,
    linkPhase,
    attemptError,
    startLogin,
    applyOauthReturn,
  } = useMetaLogin({
    clientId: activeId,
    loadClients,
    refreshMeta,
    onMetaReturnHandled,
    onError: reportError,
    onClearMetaError,
    onNotice: reportNotice,
  });

  const actionBusy = loginBusy || busy;

  const reloadContent = useCallback(
    async (id = activeId, { preserveDraft = true } = {}) => {
      if (!id) {
        setStrategy(null);
        setFigma(null);
        setComparison(null);
        return null;
      }
      const [strat, fig, cmp] = await Promise.all([
        api(`/api/clients/${id}/strategy`),
        api(`/api/clients/${id}/figma-planning`),
        api(`/api/clients/${id}/comparison`),
      ]);
      const localAnswers = preserveDraft ? answersDraftRef.current : {};
      const mergedAnswers = preserveDraft
        ? mergeAnswersPreferLocal(strat.start_answers, localAnswers)
        : strat.start_answers || {};
      const nextStrategy = {
        ...strat,
        start_answers: mergedAnswers,
        missing_required: computeMissingRequired(mergedAnswers, strat.questions || []),
      };
      answersDraftRef.current = mergedAnswers;
      setStrategy(nextStrategy);
      setFigma(fig);
      setComparison(cmp);

      const fields = strat.strategy_fields || {};
      const serverCanva = String(fields.canva_strategy_url || fields.canva_url || "").trim();
      const localCanva = preserveDraft ? String(canvaDraftRef.current || "").trim() : "";
      const nextCanva = localCanva || serverCanva;
      canvaDraftRef.current = nextCanva;
      setCanvaUrl(nextCanva);

      const conn = fig.connection || {};
      const serverFigmaUrl = String(conn.source_url || "").trim();
      const serverFigmaKey = String(conn.file_key || "").trim();
      const localFigmaUrl = preserveDraft ? String(figmaUrlDraftRef.current || "").trim() : "";
      const localFigmaKey = preserveDraft ? String(figmaKeyDraftRef.current || "").trim() : "";
      const nextFigmaUrl = localFigmaUrl || serverFigmaUrl;
      const nextFigmaKey = localFigmaKey || serverFigmaKey;
      figmaUrlDraftRef.current = nextFigmaUrl;
      figmaKeyDraftRef.current = nextFigmaKey;
      setFigmaUrl(nextFigmaUrl);
      setFigmaKey(nextFigmaKey);
      return nextStrategy;
    },
    [activeId],
  );

  useEffect(() => {
    if (client?.id && client.id !== clientId) {
      setClientId(client.id);
      setName(client.name || "");
    }
  }, [client?.id, client?.name, clientId]);

  useEffect(() => {
    answersDraftRef.current = {};
    canvaDraftRef.current = "";
    figmaUrlDraftRef.current = "";
    figmaKeyDraftRef.current = "";
    setImportPreview(null);
    setImportNote("");
  }, [activeId]);

  useEffect(() => {
    if (popupReturn) return;
    if (!activeId) {
      setStep(1);
      window.setTimeout(() => nameRef.current?.focus(), 50);
      return;
    }
    refreshMeta()
      .then((payload) => {
        const first = payload?.pages?.selectable?.[0];
        if (first) setPageIndex(first.index);
      })
      .catch((exc) => reportError(exc.message));
    // Drafts are cleared when activeId changes; preserveDraft keeps in-progress
    // answers across Meta OAuth returns (metaChoice) and sibling reloads.
    reloadContent(activeId, { preserveDraft: true }).catch((exc) => reportError(exc.message));
  }, [activeId, metaChoice, popupReturn, refreshMeta, reloadContent, reportError, setPageIndex]);

  useEffect(() => {
    if (!popupReturn) return;
    notifyMetaOauthResult({
      ok: !metaError,
      clientId: activeId,
      error: metaError || null,
    });
    window.setTimeout(() => {
      try {
        window.close();
      } catch {
        // browsers may block close
      }
      window.setTimeout(() => setPopupStuck(true), 250);
    }, 150);
  }, [popupReturn, metaError, activeId]);

  // Apply OAuth result from the opener (BroadcastChannel / query) once per return.
  useEffect(() => {
    if (popupReturn) return;
    if (!metaChoice && !metaError) {
      oauthSettledFromProps.current = false;
      return;
    }
    if (oauthSettledFromProps.current) return;
    oauthSettledFromProps.current = true;
    if (metaChoice) {
      applyOauthReturn({ ok: true });
      setStep(2);
      refreshMeta()
        .then((payload) => {
          const first = payload?.pages?.selectable?.[0];
          if (first) setPageIndex(first.index);
        })
        .catch((exc) => reportError(exc.message));
      return;
    }
    applyOauthReturn({ ok: false, error: metaError });
    setStep(2);
  }, [popupReturn, metaChoice, metaError, applyOauthReturn, refreshMeta, reportError, setPageIndex]);

  const answers = strategy?.start_answers || {};
  const questions = strategy?.questions || [];
  const requiredQuestions = questions.filter((q) => q.required_for_complete);
  const missingRequired = useMemo(
    () => computeMissingRequired(answers, questions),
    [answers, questions],
  );
  const targets = strategy?.targets || [];
  const competitors = (comparison?.competitors || [])
    .map((c) => (typeof c === "string" ? c : c.username || c.name || ""))
    .filter(Boolean);
  const figmaConnected = Boolean(figma?.connection?.file_key);
  const canvaFilled = Boolean(canvaUrl.trim());
  const figmaFilled = Boolean(figmaConnected || figmaUrl.trim() || figmaKey.trim());
  const metaConnected = Boolean(meta?.connected);
  const nameOk = Boolean((name || "").trim()) && Boolean(activeId);
  const strategyReady = Boolean(strategy) && missingRequired.length === 0;

  const checklist = useMemo(() => {
    const items = [
      {
        key: "name",
        label: "Klantnaam",
        required: true,
        kind: nameOk ? "ready" : "todo",
        status: nameOk ? "Klaar" : "Nog invullen",
        detail: nameOk ? name.trim() : "Vul de klantnaam in.",
        editor: "Jij vult de naam in.",
        hamster: "HAMSTER bewaart de klant in de lijst.",
      },
      {
        key: "meta",
        label: "Facebook en Instagram",
        required: true,
        kind: metaConnected ? "ready" : meta?.pages ? "review" : "todo",
        status: metaConnected ? "Klaar" : meta?.pages ? "Controleren" : "Nog koppelen",
        detail: metaConnected
          ? `${meta.page_name || "Facebook"}${meta.ig_username ? ` · @${meta.ig_username}` : ""}`
          : "Nog niet gekoppeld. Selecteren in de zijbalk telt niet als koppeling.",
        editor: "Jij logt in bij Meta en kiest de juiste pagina en Instagram.",
        hamster: "HAMSTER opent de Meta-login en bewaart de koppeling veilig op de server.",
      },
      {
        key: "strategy",
        label: "Strategie (verplichte vragen)",
        required: true,
        kind: strategyReady ? "ready" : "todo",
        status: strategyReady ? "Klaar" : "Nog invullen",
        detail: strategyReady
          ? "Verplichte strategievragen zijn ingevuld."
          : `${missingRequired.length || requiredQuestions.length} verplichte vraag(en) open`,
        editor: "Jij beantwoordt de verplichte vragen over de klant.",
        hamster: "HAMSTER toont de vragenlijst en bewaart concepten tussentijds.",
      },
      {
        key: "targets",
        label: "Doelen",
        required: false,
        kind: targets.length ? "ready" : "optional",
        status: targets.length ? "Klaar" : "Optioneel",
        detail: targets.length ? `${targets.length} doel(en)` : "Nog geen doelen toegevoegd.",
        editor: "Jij zet meetbare doelen (optioneel).",
        hamster: "HAMSTER bewaart doelen bij de klant.",
      },
      {
        key: "canva",
        label: "Canva-link",
        required: false,
        kind: canvaFilled ? "ready" : "optional",
        status: canvaFilled ? "Klaar" : "Optioneel",
        detail: canvaFilled
          ? canvaUrl
          : "Geen Canva-link. Optioneel — blokkeert afronden niet. Alleen de link wordt bewaard; Canva-inhoud wordt niet uitgelezen.",
        editor: "Jij plakt de Canva-link (optioneel).",
        hamster: "HAMSTER bewaart alleen de link. Velden invullen kan via PDF-export.",
      },
      {
        key: "figma",
        label: "Figma-link",
        required: false,
        kind: figmaFilled ? "ready" : "optional",
        status: figmaFilled ? "Klaar" : "Optioneel",
        detail: figmaConnected
          ? figma.connection.file_name || figma.connection.file_key
          : figmaUrl.trim() || figmaKey.trim() || "Geen Figma-koppeling. Optioneel — blokkeert afronden niet.",
        editor: "Jij plakt de Figma-link of file key (optioneel).",
        hamster: "HAMSTER bewaart de Figma-koppeling. Strategievragen worden hier niet automatisch ingevuld.",
      },
      {
        key: "competitors",
        label: "Concurrenten",
        required: false,
        kind: competitors.length ? "ready" : "optional",
        status: competitors.length ? "Klaar" : "Optioneel",
        detail: competitors.length
          ? competitors.map((c) => `@${String(c).replace(/^@/, "")}`).join(", ")
          : "Nog geen concurrenten.",
        editor: "Jij voegt Instagram-concurrenten toe (optioneel).",
        hamster: "HAMSTER bewaart de lijst onder Concurrenten.",
      },
    ];
    return items;
  }, [
    nameOk,
    name,
    metaConnected,
    meta,
    missingRequired,
    requiredQuestions.length,
    strategyReady,
    targets,
    canvaFilled,
    canvaUrl,
    figmaFilled,
    figmaConnected,
    figmaUrl,
    figmaKey,
    figma,
    competitors,
  ]);

  const blocking = checklist.filter((item) => item.required && item.kind !== "ready");
  const canFinish = blocking.length === 0;

  function stepStatus(stepId) {
    if (stepId === 1) return nameOk ? { kind: "ready", label: "Klaar" } : { kind: "todo", label: "Nog invullen" };
    if (stepId === 2) {
      if (metaConnected) return { kind: "ready", label: "Klaar" };
      if (meta?.pages) return { kind: "review", label: "Controleren" };
      return { kind: "todo", label: "Nog koppelen" };
    }
    if (stepId === 3) {
      const open = checklist.filter((i) => ["strategy", "targets", "canva", "figma", "competitors"].includes(i.key) && i.kind !== "ready");
      if (!open.length) return { kind: "ready", label: "Klaar" };
      if (open.some((i) => i.required)) return { kind: "todo", label: "Nog invullen" };
      return { kind: "review", label: "Controleren" };
    }
    return canFinish ? { kind: "ready", label: "Klaar" } : { kind: "review", label: "Controleren" };
  }

  async function saveName(event) {
    event?.preventDefault?.();
    setLocalError("");
    onError("");
    const trimmed = name.trim();
    if (!trimmed) {
      setLocalError("Vul een klantnaam in.");
      return;
    }
    setBusy("name");
    try {
      if (activeId) {
        await api(`/api/clients/${activeId}`, { method: "PATCH", body: { name: trimmed } });
        await loadClients();
        setLocalNotice("Klantnaam opgeslagen.");
        onNotice("Klantnaam opgeslagen.");
      } else {
        const created = await api("/api/clients", { method: "POST", body: { name: trimmed } });
        setClientId(created.id);
        await loadClients();
        chooseClient(created.id);
        setLocalNotice(`Klant “${created.name}” is aangemaakt. Ga verder met koppelen.`);
        onNotice(`Klant “${created.name}” is aangemaakt.`);
        setStep(2);
      }
    } catch (exc) {
      setLocalError(exc.message);
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function confirmPage() {
    if (!activeId) return;
    setBusy("confirm");
    setLocalError("");
    try {
      const payload = await api(`/api/clients/${activeId}/meta/confirm`, {
        method: "POST",
        body: { page_index: Number(pageIndex) },
      });
      await loadClients();
      await refreshMeta();
      setLocalNotice(payload.message || "Gekoppeld.");
      onNotice(payload.message || "Gekoppeld.");
    } catch (exc) {
      setLocalError(exc.message);
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function cancelLogin() {
    if (!activeId) return;
    setBusy("cancel");
    try {
      await api(`/api/clients/${activeId}/meta/cancel`, { method: "POST", body: {} });
      await refreshMeta();
      setLocalNotice("Koppelen geannuleerd. Je kunt het opnieuw proberen. Ingevulde gegevens blijven staan.");
    } catch (exc) {
      setLocalError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function recheck() {
    if (!activeId) return;
    setBusy("recheck");
    try {
      const payload = await api(`/api/clients/${activeId}/meta/recheck`, { method: "POST", body: {} });
      await loadClients();
      await refreshMeta();
      setLocalNotice(payload.message || "Koppeling gecontroleerd.");
    } catch (exc) {
      await loadClients();
      setLocalError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function disconnectMeta() {
    if (!activeId) return;
    setBusy("disconnect");
    try {
      const payload = await api(`/api/clients/${activeId}/meta/disconnect`, { method: "POST", body: {} });
      setDisconnectOpen(false);
      await loadClients();
      await refreshMeta();
      setLocalNotice(payload.message || "Meta ontkoppeld voor deze klant.");
    } catch (exc) {
      setLocalError(exc.message);
    } finally {
      setBusy("");
    }
  }

  function setAnswer(key, value) {
    const start_answers = { ...(strategy?.start_answers || {}), [key]: value };
    answersDraftRef.current = start_answers;
    setStrategy({
      ...strategy,
      start_answers,
      missing_required: computeMissingRequired(start_answers, strategy?.questions || questions),
    });
  }

  async function saveStrategyDraft({
    notice = true,
    busyKey = "strategy",
    markBusy = true,
  } = {}) {
    if (!activeId || !strategy) {
      throw new Error("Er is nog geen klant of strategiestructuur geladen.");
    }
    if (markBusy) setBusy(busyKey);
    setLocalError("");
    try {
      const start_answers = {
        ...(strategy.start_answers || {}),
        ...(answersDraftRef.current || {}),
      };
      const fields = {
        ...(strategy.strategy_fields || {}),
        canva_strategy_url: String(canvaDraftRef.current || canvaUrl || "").trim(),
      };
      const payload = await api(`/api/clients/${activeId}/strategy`, {
        method: "PUT",
        body: {
          account_info: strategy.account_info || {},
          start_answers,
          strategy_fields: fields,
          source_notes: strategy.source_notes || [],
          mark_complete: false,
        },
      });
      const nextAnswers = payload.start_answers || start_answers;
      answersDraftRef.current = nextAnswers;
      canvaDraftRef.current = String(
        payload.strategy_fields?.canva_strategy_url || fields.canva_strategy_url || "",
      ).trim();
      setCanvaUrl(canvaDraftRef.current);
      setStrategy({
        ...payload,
        start_answers: nextAnswers,
        missing_required: computeMissingRequired(nextAnswers, payload.questions || questions),
      });
      if (notice) {
        setLocalNotice("Conceptstrategie opgeslagen. Je kunt later verdergaan, ook als nog niet alles is ingevuld.");
        onNotice("Conceptstrategie opgeslagen.");
      }
      return payload;
    } catch (exc) {
      const message = dutchSaveError(exc);
      setLocalError(message);
      onError(message);
      throw new Error(message);
    } finally {
      if (markBusy) setBusy("");
    }
  }

  async function goToReview() {
    setLocalError("");
    setBusy("review");
    try {
      await saveStrategyDraft({ notice: true, busyKey: "review", markBusy: false });
      setStep(4);
    } catch {
      setStep(3);
    } finally {
      setBusy("");
    }
  }

  async function saveCanva() {
    if (!activeId) return;
    setBusy("canva");
    setLocalError("");
    setImportNote("");
    try {
      await saveStrategyDraft({ notice: false, busyKey: "canva", markBusy: false });
      const url = String(canvaDraftRef.current || canvaUrl || "").trim();
      if (url) {
        try {
          const preview = await api(`/api/clients/${activeId}/strategy/import/canva-preview`, {
            method: "POST",
            body: { url },
          });
          setImportNote(
            preview.note ||
              "Canva-link bewaard. De ontwerpinhoud zelf wordt niet uitgelezen; gebruik een PDF-export om velden voor te stellen.",
          );
        } catch {
          setImportNote(
            "Canva-link bewaard. Inhoud uit Canva kan niet worden ingelezen; vul handmatig of via PDF-export.",
          );
        }
      }
      setLocalNotice("Canva-link opgeslagen (alleen de link, geen automatische velden).");
      onNotice("Canva-link opgeslagen.");
    } catch {
      // error already shown; keep input
    } finally {
      setBusy("");
    }
  }

  async function previewPdfImport(file) {
    if (!activeId || !file) return;
    setBusy("import");
    setLocalError("");
    setImportNote("");
    try {
      const body = new FormData();
      body.append("file", file);
      const preview = await api(`/api/clients/${activeId}/strategy/import/pdf-preview`, {
        method: "POST",
        body,
        raw: true,
      });
      setImportPreview(preview);
      const unreadable = preview.content_extracted
        ? preview.missing || []
        : ["PDF-inhoud kon niet worden gelezen"];
      setImportNote(
        preview.content_extracted
          ? `PDF gelezen. Voorstellen voor lege velden klaar ter controle. Niet gevonden: ${
              (unreadable || []).slice(0, 8).join(" · ") || "geen"
            }.`
          : "Deze bron kon niet worden uitgelezen. Vul handmatig in of exporteer opnieuw als tekst-PDF.",
      );
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
      setImportPreview(null);
    } finally {
      setBusy("");
    }
  }

  function applyImportDraftLocally() {
    if (!importPreview?.proposed) return;
    const proposed = importPreview.proposed.start_answers || {};
    const current = { ...(strategy?.start_answers || {}), ...(answersDraftRef.current || {}) };
    let filled = 0;
    const skipped = [];
    for (const [key, value] of Object.entries(proposed)) {
      const text = String(value || "").trim();
      if (!text) continue;
      if (String(current[key] || "").trim()) {
        skipped.push(key);
        continue;
      }
      current[key] = text;
      filled += 1;
    }
    answersDraftRef.current = current;
    const fields = {
      ...(strategy?.strategy_fields || {}),
      ...(importPreview.proposed.strategy_fields || {}),
    };
    if (fields.canva_strategy_url) {
      canvaDraftRef.current = String(fields.canva_strategy_url).trim();
      setCanvaUrl(canvaDraftRef.current);
    }
    setStrategy({
      ...strategy,
      start_answers: current,
      strategy_fields: fields,
      missing_required: computeMissingRequired(current, strategy?.questions || questions),
    });
    setLocalNotice(
      filled
        ? `${filled} lege veld(en) als concept ingevuld. Controleer de teksten en klik daarna op Strategie opslaan.`
        : "Geen lege velden om te vullen; bestaande antwoorden blijven staan.",
    );
    if (skipped.length) {
      setImportNote(
        `Handmatige antwoorden behouden (${skipped.length}). Brondata die niet paste of al gevuld was, is overgeslagen.`,
      );
    }
    setImportPreview(null);
  }

  async function saveFigma() {
    if (!activeId) return;
    setBusy("figma");
    setLocalError("");
    try {
      // Persist strategy draft first so sibling reload cannot wipe answers.
      try {
        await saveStrategyDraft({ notice: false, busyKey: "figma", markBusy: false });
      } catch {
        setBusy("");
        return;
      }
      let key = String(figmaKeyDraftRef.current || figmaKey || "").trim();
      const url = String(figmaUrlDraftRef.current || figmaUrl || "").trim();
      if (!key && url) {
        const match = url.match(/figma\.com\/(?:file|design)\/([a-zA-Z0-9]+)/);
        key = match ? match[1] : "";
      }
      if (!key) {
        setLocalError("Vul een Figma-link of file key in.");
        setBusy("");
        return;
      }
      const sourceUrl = url || `https://www.figma.com/design/${key}`;
      await api(`/api/clients/${activeId}/figma-planning/connection`, {
        method: "PUT",
        body: {
          file_key: key,
          file_name: "",
          source_url: sourceUrl,
        },
      });
      figmaKeyDraftRef.current = key;
      figmaUrlDraftRef.current = sourceUrl;
      setFigmaKey(key);
      setFigmaUrl(sourceUrl);
      await reloadContent(activeId, { preserveDraft: true });
      setLocalNotice(
        "Figma-link opgeslagen (alleen de koppeling). Strategievragen worden hier niet automatisch ingelezen.",
      );
      setImportNote(
        "Figma-planning kan later worden gesynchroniseerd; dat vult geen strategievragen in.",
      );
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function addTarget() {
    if (!activeId) return;
    if (!targetDraft.metric_name.trim()) {
      setLocalError("Vul een doelnaam in (verplicht voor een doel).");
      return;
    }
    setBusy("target");
    setLocalError("");
    try {
      try {
        await saveStrategyDraft({ notice: false, busyKey: "target", markBusy: false });
      } catch {
        setBusy("");
        return;
      }
      await api(`/api/clients/${activeId}/targets`, {
        method: "POST",
        body: {
          account_key: "",
          platform: targetDraft.platform || "instagram",
          metric_name: targetDraft.metric_name.trim(),
          target_kind: "absolute",
          baseline_value: null,
          target_value: targetDraft.target_value === "" ? null : Number(targetDraft.target_value),
          unit: targetDraft.unit || "",
          period_year: new Date().getFullYear(),
          period_quarter: null,
          notes: targetDraft.notes || "",
        },
      });
      setTargetDraft({ metric_name: "", target_value: "", unit: "", platform: "instagram", notes: "" });
      await reloadContent(activeId, { preserveDraft: true });
      setLocalNotice("Doel opgeslagen.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function addCompetitor() {
    if (!activeId) return;
    setBusy("competitor");
    setLocalError("");
    try {
      try {
        await saveStrategyDraft({ notice: false, busyKey: "competitor", markBusy: false });
      } catch {
        setBusy("");
        return;
      }
      await api(`/api/clients/${activeId}/comparison/competitors`, {
        method: "POST",
        body: { name: competitorInput.trim() },
      });
      setCompetitorInput("");
      await reloadContent(activeId, { preserveDraft: true });
      setLocalNotice("Concurrent toegevoegd.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function finishSetup() {
    if (!canFinish) {
      setLocalError("Rond eerst de verplichte onderdelen af voordat je afrondt.");
      setStep(blocking[0]?.key === "meta" ? 2 : blocking[0]?.key === "name" ? 1 : 3);
      return;
    }
    setBusy("finish");
    setLocalError("");
    try {
      if (strategy) {
        const start_answers = {
          ...(strategy.start_answers || {}),
          ...(answersDraftRef.current || {}),
        };
        const fields = {
          ...(strategy.strategy_fields || {}),
          canva_strategy_url: String(canvaDraftRef.current || canvaUrl || "").trim(),
          setup_finished_at: new Date().toISOString(),
        };
        await api(`/api/clients/${activeId}/strategy`, {
          method: "PUT",
          body: {
            account_info: strategy.account_info || {},
            start_answers,
            strategy_fields: fields,
            source_notes: strategy.source_notes || [],
            mark_complete: true,
          },
        });
      }
      await loadClients();
      await reloadContent(activeId, { preserveDraft: false });
      setLocalNotice("Inrichting afgerond. Je kunt alles later nog aanpassen.");
      onNotice("Inrichting afgerond.");
      onFinished?.();
    } catch (exc) {
      const message = dutchSaveError(exc);
      setLocalError(message);
      onError(message);
      setStep(3);
    } finally {
      setBusy("");
    }
  }

  if (popupReturn) {
    return (
      <div className="stack card meta-step">
        <h2>{popupStuck ? "Ga verder in het dashboard" : "Even geduld…"}</h2>
        <p className="hint">
          {metaError
            ? "Inloggen is niet gelukt. Sluit dit venster of ga terug naar de klantinrichting. Je eerdere gegevens blijven bewaard."
            : popupStuck
              ? "Dit venster kon niet automatisch sluiten. Open de klantinrichting om de Facebook-pagina te kiezen. Pas daarna wordt de status Gekoppeld."
              : "Inloggen gelukt. Dit venster sluit en het dashboard gaat verder."}
        </p>
        <p>
          <a className="primary facebook-login" href={returnHref}>
            Terug naar klantinrichting
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="stack client-setup">
      <div className="page-toolbar">
        <div>
          <h3>
            {activeId
              ? `Klant bewerken · ${name || client?.name || ""}`
              : "Nieuwe klant toevoegen"}
          </h3>
          <p className="hint">
            Werk stap voor stap. Je kunt later terugkomen om gegevens aan te passen. Alleen selecteren
            in de zijbalk is nog geen socialmedia-koppeling.
          </p>
        </div>
      </div>

      <nav className="setup-steps" aria-label="Stappen klantinrichting">
        {STEPS.map((item) => {
          const st = stepStatus(item.id);
          const locked = item.id > 1 && !activeId;
          return (
            <button
              key={item.id}
              type="button"
              className={`setup-step${step === item.id ? " is-active" : ""}${locked ? " is-locked" : ""}`}
              disabled={locked}
              onClick={() => setStep(item.id)}
            >
              <span className="setup-step-num">{item.id}</span>
              <span className="setup-step-body">
                <strong>{item.short}</strong>
                <StatusPill kind={st.kind} label={st.label} />
              </span>
            </button>
          );
        })}
      </nav>

      {localNotice && linkPhase !== "linking" ? <p className="banner">{localNotice}</p> : null}
      {localError && linkPhase !== "linking" && !attemptError ? (
        <p className="banner error">{localError}</p>
      ) : null}

      {step === 1 ? (
        <section className="card stack">
          <h3>1. Klantnaam</h3>
          <p className="hint">
            <strong>Jij doet:</strong> vul de officiële klantnaam in.
            <br />
            <strong>HAMSTER doet:</strong> bewaart de klant in de lijst.
            <br />
            <strong>Nog nodig:</strong> een unieke naam.
          </p>
          <StatusPill kind={nameOk ? "ready" : "todo"} label={nameOk ? "Klaar" : "Nog invullen"} />
          <form className="form-grid" onSubmit={saveName}>
            <label>
              Klantnaam <span className="required-mark">verplicht</span>
              <input
                ref={nameRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={busy === "name"}
                required
                autoComplete="organization"
                placeholder="Bijvoorbeeld BBQube"
              />
            </label>
            <button className="primary" type="submit" disabled={busy === "name" || !name.trim()}>
              {busy === "name" ? "Bezig…" : activeId ? "Naam opslaan" : "Klant aanmaken en verder"}
            </button>
          </form>
          {activeId ? (
            <div className="row-actions">
              <button className="secondary" type="button" onClick={() => setStep(2)}>
                Volgende: koppelen
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {step === 2 ? (
        <section className="stack">
          <div className="card stack">
            <h3>2. Facebook en Instagram koppelen</h3>
            <p className="hint">
              <strong>Jij doet:</strong> inloggen bij Meta en de juiste pagina + Instagram kiezen.
              <br />
              <strong>HAMSTER doet:</strong> de login openen en de koppeling veilig bewaren.
              <br />
              <strong>Nog nodig:</strong> een bevestigde koppeling (niet alleen de klant selecteren).
            </p>
          </div>
          {!activeId ? (
            <p className="banner">Maak eerst de klant aan in stap 1.</p>
          ) : meta ? (
            <MetaConnectFlow
              client={{ id: activeId, name: name || client?.name || "" }}
              meta={metaForDisplay(meta, { linkPhase, attemptError })}
              pageIndex={pageIndex}
              setPageIndex={setPageIndex}
              busy={actionBusy}
              sameTabUrl={sameTabUrl}
              highlightConnect={!meta.connected}
              compact
              linkPhase={linkPhase}
              attemptError={attemptError}
              metaError={linkPhase === "linking" ? "" : metaError}
              onStart={() => {
                oauthSettledFromProps.current = false;
                startLogin({ forceSameTab: false });
              }}
              onSameTab={() => {
                oauthSettledFromProps.current = false;
                startLogin({ forceSameTab: true });
              }}
              onSameTabHref={sameTabUrl}
              onConfirm={confirmPage}
              onCancel={cancelLogin}
              onRecheck={recheck}
              onFetchPosts={onFetchPosts}
              onDisconnect={() => setDisconnectOpen(true)}
            />
          ) : (
            <p className="muted">Koppelstatus laden…</p>
          )}
          <div className="row-actions">
            <button className="secondary" type="button" onClick={() => setStep(1)}>
              Vorige
            </button>
            <button className="secondary" type="button" onClick={() => setStep(3)} disabled={!activeId}>
              Volgende: inhoud
            </button>
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="stack">
          <div className="card stack">
            <h3>3. Doelen, strategie, links en concurrenten</h3>
            <p className="hint">
              Vul in wat je nu weet. Optionele velden (Canva, Figma, doelen, concurrenten) mag je
              overslaan; die blokkeren afronden niet. “Volgende: controleren” bewaart eerst je
              strategieconcept op de server.
            </p>
          </div>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Strategie</h4>
              <StatusPill
                kind={missingRequired.length ? "todo" : "ready"}
                label={missingRequired.length ? "Nog invullen" : "Klaar"}
              />
            </div>
            <p className="hint">
              Verplichte vragen moeten ingevuld zijn om de inrichting af te ronden. Optionele vragen
              mag je overslaan. “Strategie opslaan” bewaart ook een gedeeltelijk concept.
            </p>
            {questions.map((question) => {
              const required = Boolean(question.required_for_complete);
              const open = missingRequired.includes(question.key);
              return (
                <label key={question.key}>
                  {question.label}{" "}
                  {required ? <span className="required-mark">verplicht</span> : <span className="muted">optioneel</span>}
                  {open ? <span className="setup-inline-todo"> · Nog invullen</span> : null}
                  <textarea
                    rows={3}
                    value={answers[question.key] || ""}
                    onChange={(e) => setAnswer(question.key, e.target.value)}
                    placeholder={question.short_question || ""}
                  />
                </label>
              );
            })}
            <button
              className="secondary"
              type="button"
              disabled={busy === "strategy"}
              onClick={() => {
                saveStrategyDraft().catch(() => {});
              }}
            >
              {busy === "strategy" ? "Bezig…" : "Strategie opslaan"}
            </button>
          </section>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Doelen</h4>
              <StatusPill
                kind={targets.length ? "ready" : "optional"}
                label={targets.length ? "Klaar" : "Optioneel"}
              />
            </div>
            <p className="hint">Optioneel. Voorbeeld: bereik, volgers of leads.</p>
            {targets.length ? (
              <ul className="plain-list">
                {targets.map((t) => (
                  <li key={t.id}>
                    <strong>{t.metric_name}</strong>
                    {t.target_value != null ? ` · doel ${t.target_value}${t.unit ? ` ${t.unit}` : ""}` : ""}
                    {t.platform ? ` · ${t.platform}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="form-grid">
              <label>
                Doelnaam
                <input
                  value={targetDraft.metric_name}
                  onChange={(e) => setTargetDraft({ ...targetDraft, metric_name: e.target.value })}
                  placeholder="Bijvoorbeeld bereik"
                />
              </label>
              <label>
                Doelwaarde
                <input
                  value={targetDraft.target_value}
                  onChange={(e) => setTargetDraft({ ...targetDraft, target_value: e.target.value })}
                  placeholder="10000"
                />
              </label>
              <label>
                Eenheid
                <input
                  value={targetDraft.unit}
                  onChange={(e) => setTargetDraft({ ...targetDraft, unit: e.target.value })}
                  placeholder="volgers"
                />
              </label>
              <label>
                Platform
                <select
                  value={targetDraft.platform}
                  onChange={(e) => setTargetDraft({ ...targetDraft, platform: e.target.value })}
                >
                  <option value="instagram">Instagram</option>
                  <option value="facebook">Facebook</option>
                </select>
              </label>
            </div>
            <button className="secondary" type="button" disabled={busy === "target"} onClick={addTarget}>
              {busy === "target" ? "Bezig…" : "Doel toevoegen"}
            </button>
          </section>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Canva-link</h4>
              <StatusPill
                kind={canvaFilled ? "ready" : "optional"}
                label={canvaFilled ? "Klaar" : "Optioneel"}
              />
            </div>
            <p className="hint">
              Optioneel — blokkeert afronden niet. <strong>Canva-link opslaan</strong> bewaart alleen
              de URL. Canva-ontwerpinhoud wordt niet uitgelezen.
            </p>
            <label>
              Canva-URL
              <input
                value={canvaUrl}
                onChange={(e) => {
                  const value = e.target.value;
                  canvaDraftRef.current = value;
                  setCanvaUrl(value);
                }}
                placeholder="https://www.canva.com/design/…"
              />
            </label>
            <button className="secondary" type="button" disabled={busy === "canva" || busy === "strategy"} onClick={saveCanva}>
              {busy === "canva" ? "Bezig…" : "Canva-link opslaan"}
            </button>
          </section>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Voorstellen uit PDF</h4>
              <StatusPill kind="optional" label="Optioneel" />
            </div>
            <p className="hint">
              Dit <strong>leest wel inhoud in</strong> (in tegenstelling tot alleen een link opslaan).
              Voorstellen vullen alleen lege velden als concept; handmatige antwoorden blijven staan.
              Controleer daarna en klik op Strategie opslaan.
            </p>
            <label className="secondary file-btn">
              PDF kiezen voor voorstellen
              <input
                type="file"
                accept="application/pdf,.pdf"
                hidden
                disabled={busy === "import" || !activeId}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) previewPdfImport(file);
                  event.target.value = "";
                }}
              />
            </label>
            {importNote ? <p className="hint">{importNote}</p> : null}
            {importPreview ? (
              <div className="stack">
                <p className="banner">
                  Bron: {importPreview.source_kind}
                  {importPreview.filename ? ` · ${importPreview.filename}` : ""}
                  {(importPreview.filled_keys || []).length
                    ? ` · gevonden: ${(importPreview.filled_keys || []).join(", ")}`
                    : " · geen veldvoorstellen"}
                </p>
                {(importPreview.missing || []).length ? (
                  <p className="banner warn-soft">
                    Niet inleesbaar / niet gevonden: {(importPreview.missing || []).slice(0, 8).join(" · ")}
                    {(importPreview.missing || []).length > 8
                      ? ` · +${(importPreview.missing || []).length - 8}`
                      : ""}
                  </p>
                ) : null}
                <div className="row-actions">
                  <button className="primary" type="button" onClick={applyImportDraftLocally}>
                    Voorstellen in lege velden zetten
                  </button>
                  <button className="secondary" type="button" onClick={() => setImportPreview(null)}>
                    Annuleren
                  </button>
                </div>
              </div>
            ) : null}
          </section>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Figma-link</h4>
              <StatusPill
                kind={figmaFilled ? "ready" : "optional"}
                label={figmaFilled ? "Klaar" : "Optioneel"}
              />
            </div>
            <p className="hint">
              Optioneel — blokkeert afronden niet. <strong>Figma-link opslaan</strong> bewaart alleen
              de koppeling (volledige URL of losse file key). Dat vult geen strategievragen in.
            </p>
            <label>
              Figma-URL
              <input
                value={figmaUrl}
                onChange={(e) => {
                  const value = e.target.value;
                  figmaUrlDraftRef.current = value;
                  setFigmaUrl(value);
                }}
                placeholder="https://www.figma.com/design/…"
              />
            </label>
            <label>
              Of Figma file key
              <input
                value={figmaKey}
                onChange={(e) => {
                  const value = e.target.value;
                  figmaKeyDraftRef.current = value;
                  setFigmaKey(value);
                }}
                placeholder="bestandssleutel"
              />
            </label>
            <button className="secondary" type="button" disabled={busy === "figma"} onClick={saveFigma}>
              {busy === "figma" ? "Bezig…" : "Figma-link opslaan"}
            </button>
          </section>

          <section className="card stack">
            <div className="setup-block-head">
              <h4>Concurrenten</h4>
              <StatusPill
                kind={competitors.length ? "ready" : "optional"}
                label={competitors.length ? "Klaar" : "Optioneel"}
              />
            </div>
            <p className="hint">Optioneel. Instagram-gebruikersnaam van een concurrent.</p>
            {competitors.length ? (
              <ul className="plain-list">
                {competitors.map((c) => (
                  <li key={c}>@{String(c).replace(/^@/, "")}</li>
                ))}
              </ul>
            ) : null}
            <label>
              Instagram-gebruikersnaam
              <input
                value={competitorInput}
                onChange={(e) => setCompetitorInput(e.target.value)}
                placeholder="@concurrent"
              />
            </label>
            <button
              className="secondary"
              type="button"
              disabled={busy === "competitor" || !competitorInput.trim()}
              onClick={addCompetitor}
            >
              {busy === "competitor" ? "Bezig…" : "Concurrent toevoegen"}
            </button>
          </section>

          <div className="row-actions">
            <button className="secondary" type="button" onClick={() => setStep(2)}>
              Vorige
            </button>
            <button
              className="primary"
              type="button"
              disabled={busy === "review" || busy === "strategy"}
              onClick={goToReview}
            >
              {busy === "review" ? "Opslaan…" : "Volgende: controleren"}
            </button>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="card stack">
          <h3>4. Gegevens controleren en afronden</h3>
          <p className="hint">
            Controleer wat jij nog moet doen, wat HAMSTER al klaarzet, en wat nog ontbreekt. Afronden
            kan pas als alle verplichte onderdelen klaar zijn.
          </p>
          <div className="setup-checklist">
            {checklist.map((item) => (
              <article key={item.key} className="setup-check-item">
                <div className="setup-block-head">
                  <h4>
                    {item.label}
                    {item.required ? <span className="required-mark"> verplicht</span> : null}
                  </h4>
                  <StatusPill kind={item.kind} label={item.status} />
                </div>
                <p>{item.detail}</p>
                <p className="hint">
                  {item.editor}
                  <br />
                  {item.hamster}
                </p>
              </article>
            ))}
          </div>
          {!canFinish ? (
            <p className="banner warn-soft">
              Nog niet afronden: {blocking.map((b) => b.label).join(", ")}.
            </p>
          ) : (
            <p className="banner">Alles wat verplicht is, staat klaar. Je kunt afronden.</p>
          )}
          <div className="row-actions">
            <button className="secondary" type="button" onClick={() => setStep(3)}>
              Vorige
            </button>
            <button className="primary" type="button" disabled={!canFinish || busy === "finish"} onClick={finishSetup}>
              {busy === "finish" ? "Bezig…" : "Inrichting afronden"}
            </button>
          </div>
        </section>
      ) : null}

      {disconnectOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDisconnectOpen(false)}>
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="setup-disconnect-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="setup-disconnect-title">Meta ontkoppelen?</h2>
            <p>
              Dit verwijdert alleen de Facebook/Instagram-koppeling voor{" "}
              <strong>{name || client?.name}</strong>. De klant en andere gegevens blijven bewaard.
            </p>
            <div className="row-actions">
              <button className="secondary" type="button" onClick={() => setDisconnectOpen(false)}>
                Annuleren
              </button>
              <button className="primary" type="button" disabled={busy === "disconnect"} onClick={disconnectMeta}>
                {busy === "disconnect" ? "Bezig…" : "Ontkoppelen"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
