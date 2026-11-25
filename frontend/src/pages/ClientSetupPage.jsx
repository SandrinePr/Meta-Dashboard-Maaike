import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import MetaConnectFlow from "../components/MetaConnectFlow.jsx";
import { metaForDisplay } from "../metaLoginDisplay.js";
import { dashboardClientsUrl, notifyMetaOauthResult } from "../oauthBridge.js";
import { useMetaLogin } from "../useMetaLogin.js";

const STEPS = [
  { id: 1, title: "Klantnaam", short: "Naam" },
  { id: 2, title: "Facebook en Instagram", short: "Koppelen" },
  { id: 3, title: "Inrichting per klant", short: "Inrichting" },
  { id: 4, title: "Controleren", short: "Afronden" },
];

/** Strategy answers that feed AI as this client's prompt context. */
const CLIENT_PROMPT_KEYS = new Set([
  "tone_of_voice",
  "bedrijfsomschrijving",
  "onderscheidend_vermogen",
  "gewenste_socialresultaten",
  "platforms",
]);

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
  if (!raw) return "Opslaan lukte niet";
  if (/failed to fetch|networkerror|load failed/i.test(raw)) {
    return "Opslaan lukte niet";
  }
  return "Opslaan lukte niet";
}

const AUTOSAVE_DELAY_MS = 800;
const DRAFT_STORAGE_PREFIX = "maaike.setup.draft.v1:";

function draftStorageKey(clientId) {
  return `${DRAFT_STORAGE_PREFIX}${clientId}`;
}

function readStoredDraft(clientId) {
  if (!clientId) return null;
  try {
    const raw = localStorage.getItem(draftStorageKey(clientId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredDraft(clientId, draft) {
  if (!clientId) return;
  try {
    localStorage.setItem(
      draftStorageKey(clientId),
      JSON.stringify({ ...draft, dirty: true, updatedAt: Date.now() }),
    );
  } catch {
    // private mode / quota
  }
}

function clearStoredDraft(clientId) {
  if (!clientId) return;
  try {
    localStorage.removeItem(draftStorageKey(clientId));
  } catch {
    // ignore
  }
}

function resolveFigma(urlValue, keyValue) {
  let key = String(keyValue || "").trim();
  const url = String(urlValue || "").trim();
  if (!key && url) {
    const match = url.match(/figma\.com\/(?:file|design)\/([a-zA-Z0-9]+)/);
    key = match ? match[1] : "";
  }
  return {
    key,
    url: url || (key ? `https://www.figma.com/design/${key}` : ""),
  };
}

function snapshotEquals(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
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
  // Existing clients open on inrichting (prompts/doelen/links/concurrenten), not the name step.
  const [step, setStep] = useState(isNew || !client ? 1 : 3);
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
  const [proposalDraft, setProposalDraft] = useState(null);
  const [canvaImportHint, setCanvaImportHint] = useState("");
  const pdfInputRef = useRef(null);
  const [saveStatus, setSaveStatus] = useState("idle"); // idle | saving | saved | error
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
  const nameDraftRef = useRef(client?.name || "");
  const autosaveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const lastSyncedRef = useRef(null);
  const strategyRef = useRef(null);
  const dirtyRef = useRef(false);

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
        strategyRef.current = null;
        setFigma(null);
        setComparison(null);
        return null;
      }
      const [strat, fig, cmp] = await Promise.all([
        api(`/api/clients/${id}/strategy`),
        api(`/api/clients/${id}/figma-planning`),
        api(`/api/clients/${id}/comparison`),
      ]);
      const stored = preserveDraft ? readStoredDraft(id) : null;
      const memoryAnswers = preserveDraft ? answersDraftRef.current : {};
      const draftAnswers = stored?.start_answers || {};
      const mergedAnswers = preserveDraft
        ? mergeAnswersPreferLocal(
            mergeAnswersPreferLocal(strat.start_answers, draftAnswers),
            memoryAnswers,
          )
        : strat.start_answers || {};
      const nextStrategy = {
        ...strat,
        start_answers: mergedAnswers,
        missing_required: computeMissingRequired(mergedAnswers, strat.questions || []),
      };
      answersDraftRef.current = mergedAnswers;
      strategyRef.current = nextStrategy;
      setStrategy(nextStrategy);
      setProposalDraft(strat.pending_proposal || null);
      setFigma(fig);
      setComparison(cmp);

      const fields = strat.strategy_fields || {};
      const serverCanva = String(fields.canva_strategy_url || fields.canva_url || "").trim();
      const draftCanva = preserveDraft
        ? String(stored?.canvaUrl || canvaDraftRef.current || "").trim()
        : "";
      const nextCanva = draftCanva || serverCanva;
      canvaDraftRef.current = nextCanva;
      setCanvaUrl(nextCanva);

      const conn = fig.connection || {};
      const serverFigmaUrl = String(conn.source_url || "").trim();
      const serverFigmaKey = String(conn.file_key || "").trim();
      const draftFigmaUrl = preserveDraft
        ? String(stored?.figmaUrl || figmaUrlDraftRef.current || "").trim()
        : "";
      const draftFigmaKey = preserveDraft
        ? String(stored?.figmaKey || figmaKeyDraftRef.current || "").trim()
        : "";
      const nextFigmaUrl = draftFigmaUrl || serverFigmaUrl;
      const nextFigmaKey = draftFigmaKey || serverFigmaKey;
      figmaUrlDraftRef.current = nextFigmaUrl;
      figmaKeyDraftRef.current = nextFigmaKey;
      setFigmaUrl(nextFigmaUrl);
      setFigmaKey(nextFigmaKey);

      lastSyncedRef.current = {
        name: nameDraftRef.current || "",
        start_answers: strat.start_answers || {},
        canvaUrl: serverCanva,
        figmaUrl: serverFigmaUrl,
        figmaKey: serverFigmaKey,
      };
      return nextStrategy;
    },
    [activeId],
  );

  useEffect(() => {
    if (client?.id && client.id !== clientId) {
      setClientId(client.id);
      setName(client.name || "");
      nameDraftRef.current = client.name || "";
    }
  }, [client?.id, client?.name, clientId]);

  useEffect(() => {
    setImportPreview(null);
    setImportNote("");
    setSaveStatus("idle");
    dirtyRef.current = false;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
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
        label: "Klantprompts & strategie",
        required: true,
        kind: strategyReady ? "ready" : "todo",
        status: strategyReady ? "Klaar" : "Nog invullen",
        detail: strategyReady
          ? "Verplichte klantprompts en strategievragen zijn ingevuld."
          : `${missingRequired.length || requiredQuestions.length} verplichte vraag(en) open`,
        editor: "Jij vult de context in die bij deze klant hoort (o.a. tone of voice).",
        hamster: "HAMSTER bewaart dit als klantcontext voor AI — niet als algemene prompt.",
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
        hamster:
          "HAMSTER bewaart de Figma-koppeling. Je kunt voorstellen ophalen voor lege velden uit tekst/planning in Figma.",
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

  function currentDraftPayload() {
    return {
      name: String(nameDraftRef.current || "").trim(),
      start_answers: {
        ...((strategyRef.current || strategy)?.start_answers || {}),
        ...(answersDraftRef.current || {}),
      },
      canvaUrl: String(canvaDraftRef.current || "").trim(),
      figmaUrl: String(figmaUrlDraftRef.current || "").trim(),
      figmaKey: String(figmaKeyDraftRef.current || "").trim(),
    };
  }

  function persistClientDraft(id = activeId) {
    if (!id) return;
    writeStoredDraft(id, currentDraftPayload());
  }

  function markDirtyAndSchedule() {
    if (!activeId) return;
    dirtyRef.current = true;
    persistClientDraft(activeId);
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = window.setTimeout(() => {
      flushAutosave().catch(() => {});
    }, AUTOSAVE_DELAY_MS);
  }

  async function flushAutosave() {
    if (!activeId) return true;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    const run = async () => {
      const draft = currentDraftPayload();
      const previous = lastSyncedRef.current;
      const needsName =
        draft.name && (!previous || draft.name !== String(previous.name || "").trim());
      const needsStrategy =
        !previous ||
        !snapshotEquals(draft.start_answers, previous.start_answers || {}) ||
        draft.canvaUrl !== String(previous.canvaUrl || "").trim();
      const figmaResolved = resolveFigma(draft.figmaUrl, draft.figmaKey);
      const prevFigma = resolveFigma(previous?.figmaUrl, previous?.figmaKey);
      const needsFigma =
        Boolean(figmaResolved.key) &&
        (!previous ||
          figmaResolved.key !== prevFigma.key ||
          figmaResolved.url !== prevFigma.url);

      if (!needsName && !needsStrategy && !needsFigma) {
        dirtyRef.current = false;
        if (previous) setSaveStatus("saved");
        return true;
      }

      setSaveStatus("saving");
      setLocalError("");
      try {
        let lastPersist = null;
        if (needsName) {
          const renamed = await api(`/api/clients/${activeId}`, {
            method: "PATCH",
            body: { name: draft.name },
          });
          lastPersist = renamed?.persist || lastPersist;
          await loadClients();
        }

        if (needsStrategy) {
          const strat = strategyRef.current || strategy || {
            account_info: {},
            strategy_fields: {},
            source_notes: [],
            questions: [],
          };
          const fields = {
            ...(strat.strategy_fields || {}),
            canva_strategy_url: draft.canvaUrl,
          };
          const payload = await api(`/api/clients/${activeId}/strategy`, {
            method: "PUT",
            body: {
              account_info: strat.account_info || {},
              start_answers: draft.start_answers,
              strategy_fields: fields,
              source_notes: strat.source_notes || [],
              mark_complete: false,
            },
          });
          lastPersist = payload?.persist || lastPersist;
          const nextAnswers = payload.start_answers || draft.start_answers;
          answersDraftRef.current = nextAnswers;
          const nextStrategy = {
            ...payload,
            start_answers: nextAnswers,
            missing_required: computeMissingRequired(nextAnswers, payload.questions || []),
          };
          strategyRef.current = nextStrategy;
          setStrategy(nextStrategy);
          canvaDraftRef.current = String(
            payload.strategy_fields?.canva_strategy_url || draft.canvaUrl || "",
          ).trim();
          setCanvaUrl(canvaDraftRef.current);
        }

        if (needsFigma) {
          const figmaSaved = await api(`/api/clients/${activeId}/figma-planning/connection`, {
            method: "PUT",
            body: {
              file_key: figmaResolved.key,
              file_name: "",
              source_url: figmaResolved.url,
            },
          });
          lastPersist = figmaSaved?.persist || lastPersist;
          figmaKeyDraftRef.current = figmaResolved.key;
          figmaUrlDraftRef.current = figmaResolved.url;
          setFigmaKey(figmaResolved.key);
          setFigmaUrl(figmaResolved.url);
          const fig = await api(`/api/clients/${activeId}/figma-planning`);
          setFigma(fig);
        }

        if (lastPersist && lastPersist.durable !== true) {
          const err = new Error(
            lastPersist.error || "Externe opslag bevestigde de wijziging niet.",
          );
          dirtyRef.current = true;
          persistClientDraft(activeId);
          setSaveStatus("error");
          setLocalError(dutchSaveError(err));
          throw err;
        }

        lastSyncedRef.current = {
          name: draft.name,
          start_answers: draft.start_answers,
          canvaUrl: draft.canvaUrl,
          figmaUrl: figmaResolved.url || draft.figmaUrl,
          figmaKey: figmaResolved.key || draft.figmaKey,
        };
        dirtyRef.current = false;
        clearStoredDraft(activeId);
        setSaveStatus("saved");
        return true;
      } catch (exc) {
        dirtyRef.current = true;
        persistClientDraft(activeId);
        setSaveStatus("error");
        setLocalError(dutchSaveError(exc));
        throw exc;
      }
    };

    const queued = saveChainRef.current.then(run, run);
    saveChainRef.current = queued.catch(() => {});
    return queued;
  }

  async function createClient(event) {
    event?.preventDefault?.();
    setLocalError("");
    onError("");
    const trimmed = String(nameDraftRef.current || name || "").trim();
    if (!trimmed) {
      setLocalError("Vul een klantnaam in.");
      return;
    }
    if (activeId) {
      markDirtyAndSchedule();
      await flushAutosave().catch(() => {});
      return;
    }
    setBusy("name");
    try {
      const created = await api("/api/clients", { method: "POST", body: { name: trimmed } });
      setClientId(created.id);
      nameDraftRef.current = created.name;
      setName(created.name);
      await loadClients();
      chooseClient(created.id);
      setStep(2);
      if (created?.persist && created.persist.durable !== true) {
        dirtyRef.current = true;
        persistClientDraft(created.id);
        setSaveStatus("error");
        const msg =
          created.persist.error ||
          "Klant staat lokaal, maar externe opslag bevestigde niet. Probeer opnieuw op te slaan.";
        setLocalError(msg);
        onError(msg);
        return;
      }
      setSaveStatus("saved");
      setLocalNotice(`Klant “${created.name}” is aangemaakt. Gegevens worden automatisch bewaard.`);
      onNotice(`Klant “${created.name}” is aangemaakt.`);
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
      onError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function goToStep(nextStep) {
    try {
      if (activeId) await flushAutosave();
      setStep(nextStep);
    } catch {
      // stay on current step; status shows error + retry
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
    const next = {
      ...strategy,
      start_answers,
      missing_required: computeMissingRequired(start_answers, strategy?.questions || questions),
    };
    strategyRef.current = next;
    setStrategy(next);
    markDirtyAndSchedule();
  }

  async function previewPdfImport(file) {
    if (!activeId || !file) return;
    setBusy("import");
    setLocalError("");
    setImportNote("");
    setCanvaImportHint("");
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

  async function stageImportProposal() {
    if (!activeId || !importPreview?.proposed) return;
    setBusy("import");
    setLocalError("");
    try {
      await flushAutosave().catch(() => {});
      const payload = await api(`/api/clients/${activeId}/strategy/import/apply`, {
        method: "POST",
        body: {
          proposed: importPreview.proposed,
          preserve_manual: true,
          stage_only: true,
          source_kind: importPreview.source_kind || "strategy_pdf",
          filename: importPreview.filename || "",
          file_ref: importPreview.file_ref || "",
        },
      });
      const next = {
        ...payload,
        start_answers: mergeAnswersPreferLocal(
          payload.start_answers || {},
          answersDraftRef.current || {},
        ),
      };
      answersDraftRef.current = next.start_answers;
      strategyRef.current = next;
      setStrategy(next);
      setProposalDraft(payload.pending_proposal || null);
      setImportPreview(null);
      setLocalNotice(
        payload.pending_proposal
          ? "Voorstellen klaargezet ter controle. Handmatige antwoorden blijven staan tot je goedkeurt."
          : "Bron bewaard. Geen nieuwe voorstellen — lege of al gevulde velden leverden niets nieuws op.",
      );
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function previewFigmaProposals() {
    if (!activeId) return;
    setBusy("figma-import");
    setLocalError("");
    setImportNote("");
    try {
      await flushAutosave().catch(() => {});
      const preview = await api(`/api/clients/${activeId}/strategy/import/figma-preview`, {
        method: "POST",
        body: {},
      });
      setImportPreview(preview);
      setImportNote(
        preview.note ||
          (preview.filled_keys?.length
            ? `Figma gelezen. Gevonden: ${preview.filled_keys.join(", ")}.`
            : "Geen strategie-informatie in dit Figma-bestand."),
      );
    } catch (exc) {
      setLocalError(exc.message || dutchSaveError(exc));
      setImportPreview(null);
    } finally {
      setBusy("");
    }
  }

  async function previewCanvaProposals() {
    if (!activeId) return;
    const url = String(canvaDraftRef.current || canvaUrl || "").trim();
    setBusy("canva-import");
    setLocalError("");
    setImportNote("");
    setCanvaImportHint("");
    try {
      await flushAutosave().catch(() => {});
      if (!url) {
        setCanvaImportHint(
          "Plak eerst een Canva-link. Zonder Canva Connect-token blijft de PDF-route beschikbaar.",
        );
        document.getElementById("setup-pdf-import")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
        pdfInputRef.current?.focus?.();
        return;
      }
      const preview = await api(`/api/clients/${activeId}/strategy/import/canva-preview`, {
        method: "POST",
        body: { url },
      });
      if (preview.content_extracted && (preview.filled_keys || []).length) {
        setImportPreview(preview);
        setCanvaImportHint("");
        setImportNote(
          preview.note ||
            `Canva gelezen. Gevonden: ${(preview.filled_keys || []).join(", ")}.`,
        );
        return;
      }
      // No Connect access or no strategy text — keep PDF path available.
      setImportPreview(null);
      setCanvaImportHint(
        preview.note ||
          preview.access?.requirements_nl ||
          "Canva-link kon niet worden uitgelezen. PDF-import blijft beschikbaar.",
      );
      setImportNote(
        "Canva-link bewaard als bron. Voor veldvoorstellen zonder Connect-toegang: exporteer als tekst-PDF en kies ‘Voorstellen ophalen via PDF’.",
      );
      try {
        document.getElementById("setup-pdf-import")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      } catch {
        /* ignore */
      }
      pdfInputRef.current?.focus?.();
    } catch (exc) {
      const message = exc.message || dutchSaveError(exc);
      setLocalError(message);
      setImportPreview(null);
      setCanvaImportHint(
        `${message} PDF-import blijft beschikbaar onder ‘Voorstellen ophalen via PDF’.`,
      );
      try {
        document.getElementById("setup-pdf-import")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      } catch {
        /* ignore */
      }
    } finally {
      setBusy("");
    }
  }

  function setProposalAnswer(key, value) {
    setProposalDraft((cur) => {
      if (!cur) return cur;
      return {
        ...cur,
        start_answers: { ...(cur.start_answers || {}), [key]: value },
      };
    });
  }

  function setProposalField(key, value) {
    setProposalDraft((cur) => {
      if (!cur) return cur;
      return {
        ...cur,
        strategy_fields: { ...(cur.strategy_fields || {}), [key]: value },
      };
    });
  }

  async function approveProposal() {
    if (!activeId || !proposalDraft) return;
    setBusy("proposal");
    setLocalError("");
    try {
      const payload = await api(`/api/clients/${activeId}/strategy/proposal/approve`, {
        method: "POST",
        body: { proposal: proposalDraft },
      });
      const next = {
        ...payload,
        start_answers: mergeAnswersPreferLocal(
          payload.start_answers || {},
          answersDraftRef.current || {},
        ),
      };
      answersDraftRef.current = next.start_answers;
      strategyRef.current = next;
      setStrategy(next);
      setProposalDraft(null);
      writeStoredDraft(activeId, {
        start_answers: next.start_answers,
        canvaUrl: canvaDraftRef.current,
        figmaUrl: figmaUrlDraftRef.current,
        figmaKey: figmaKeyDraftRef.current,
      });
      setLocalNotice("Voorstel goedgekeurd. Alleen eerder lege velden zijn bijgewerkt.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  async function discardProposal() {
    if (!activeId) return;
    setBusy("proposal");
    setLocalError("");
    try {
      const payload = await api(`/api/clients/${activeId}/strategy/proposal/discard`, {
        method: "POST",
        body: {},
      });
      setStrategy((cur) => ({ ...(cur || {}), ...payload, start_answers: answersDraftRef.current }));
      setProposalDraft(null);
      setLocalNotice("Voorstel verworpen. Handmatige antwoorden ongewijzigd.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
    } finally {
      setBusy("");
    }
  }

  function applyImportDraftLocally() {
    // Kept as alias for the staged approval flow (point 9).
    return stageImportProposal();
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
      await flushAutosave();
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
      setLocalNotice("Doel toegevoegd.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
      setSaveStatus("error");
    } finally {
      setBusy("");
    }
  }

  async function addCompetitor() {
    if (!activeId) return;
    setBusy("competitor");
    setLocalError("");
    try {
      await flushAutosave();
      await api(`/api/clients/${activeId}/comparison/competitors`, {
        method: "POST",
        body: { name: competitorInput.trim() },
      });
      setCompetitorInput("");
      await reloadContent(activeId, { preserveDraft: true });
      setLocalNotice("Concurrent toegevoegd.");
    } catch (exc) {
      setLocalError(dutchSaveError(exc));
      setSaveStatus("error");
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
      await flushAutosave();
      const strat = strategyRef.current || strategy;
      if (strat) {
        const start_answers = {
          ...(strat.start_answers || {}),
          ...(answersDraftRef.current || {}),
        };
        const fields = {
          ...(strat.strategy_fields || {}),
          canva_strategy_url: String(canvaDraftRef.current || canvaUrl || "").trim(),
          setup_finished_at: new Date().toISOString(),
        };
        await api(`/api/clients/${activeId}/strategy`, {
          method: "PUT",
          body: {
            account_info: strat.account_info || {},
            start_answers,
            strategy_fields: fields,
            source_notes: strat.source_notes || [],
            mark_complete: true,
          },
        });
      }
      clearStoredDraft(activeId);
      await loadClients();
      await reloadContent(activeId, { preserveDraft: false });
      setLocalNotice("Inrichting afgerond. Je kunt alles later nog aanpassen.");
      onNotice("Inrichting afgerond.");
      onFinished?.();
    } catch (exc) {
      setSaveStatus("error");
      setLocalError(dutchSaveError(exc));
      onError(dutchSaveError(exc));
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
            Dit is de <strong>enige plek</strong> voor de inrichting per klant: doelen, strategie,
            links, concurrenten en de prompts die bij deze klant horen. Alleen selecteren in de
            zijbalk is nog geen socialmedia-koppeling. Algemene prompts blijven bij Technisch beheer.
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
              onClick={() => goToStep(item.id)}
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

      {activeId ? (
        <div className="setup-save-status" aria-live="polite">
          {saveStatus === "saving" ? <span className="setup-save-saving">Bezig met opslaan…</span> : null}
          {saveStatus === "saved" ? <span className="setup-save-ok">Opgeslagen</span> : null}
          {saveStatus === "error" ? (
            <span className="setup-save-error">
              Opslaan lukte niet{" "}
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  flushAutosave().catch(() => {});
                }}
              >
                Opnieuw proberen
              </button>
            </span>
          ) : null}
        </div>
      ) : null}

      {localNotice && linkPhase !== "linking" ? <p className="banner">{localNotice}</p> : null}
      {localError && linkPhase !== "linking" && !attemptError && saveStatus !== "error" ? (
        <p className="banner error">{localError}</p>
      ) : null}

      {step === 1 ? (
        <section className="card stack">
          <h3>1. Klantnaam</h3>
          <p className="hint">
            <strong>Jij doet:</strong> vul de officiële klantnaam in.
            <br />
            <strong>HAMSTER doet:</strong> bewaart de naam automatisch zodra je stopt met typen.
            <br />
            <strong>Nog nodig:</strong> een unieke naam.
          </p>
          <StatusPill kind={nameOk ? "ready" : "todo"} label={nameOk ? "Klaar" : "Nog invullen"} />
          <form className="form-grid" onSubmit={createClient}>
            <label>
              Klantnaam <span className="required-mark">verplicht</span>
              <input
                ref={nameRef}
                value={name}
                onChange={(e) => {
                  const value = e.target.value;
                  nameDraftRef.current = value;
                  setName(value);
                  if (activeId) markDirtyAndSchedule();
                }}
                onBlur={() => {
                  if (activeId) flushAutosave().catch(() => {});
                }}
                disabled={busy === "name"}
                required
                autoComplete="organization"
                placeholder="Bijvoorbeeld BBQube"
              />
            </label>
            {!activeId ? (
              <button className="primary" type="submit" disabled={busy === "name" || !name.trim()}>
                {busy === "name" ? "Bezig…" : "Klant aanmaken en verder"}
              </button>
            ) : null}
          </form>
          {activeId ? (
            <div className="row-actions">
              <button className="secondary" type="button" onClick={() => goToStep(2)}>
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
            <button className="secondary" type="button" onClick={() => goToStep(1)}>
              Vorige
            </button>
            <button className="secondary" type="button" onClick={() => goToStep(3)} disabled={!activeId}>
              Volgende: inhoud
            </button>
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="stack">
          <div className="card stack">
            <h3>3. Inrichting voor {name || client?.name || "deze klant"}</h3>
            <p className="hint">
              Hier regel je alles wat bij <strong>deze klant</strong> hoort: doelen, strategie,
              links, concurrenten en klantprompts. Wijzigingen worden automatisch bewaard.
              Optionele velden (Canva, Figma, doelen, concurrenten) mag je overslaan; die
              blokkeren afronden niet.
            </p>
            <p className="banner">
              <strong>Klantprompts</strong> hieronder gelden alleen voor{" "}
              <strong>{name || client?.name || "deze klant"}</strong>. Algemene AI-prompts
              (voor alle klanten) staan bij <strong>Technisch beheer</strong> en horen niet hier.
            </p>
            <nav className="row-actions wrap" aria-label="Onderdelen inrichting">
              <a className="secondary" href="#setup-client-prompts" style={{ textDecoration: "none" }}>
                Klantprompts
              </a>
              <a className="secondary" href="#setup-strategy" style={{ textDecoration: "none" }}>
                Strategie
              </a>
              <a className="secondary" href="#setup-targets" style={{ textDecoration: "none" }}>
                Doelen
              </a>
              <a className="secondary" href="#setup-links" style={{ textDecoration: "none" }}>
                Links
              </a>
              <a className="secondary" href="#setup-competitors" style={{ textDecoration: "none" }}>
                Concurrenten
              </a>
            </nav>
          </div>

          <section className="card stack" id="setup-client-prompts">
            <div className="setup-block-head">
              <h4>
                Klantprompts{" "}
                <span className="badge badge-active">
                  Alleen {name || client?.name || "deze klant"}
                </span>
              </h4>
              <StatusPill
                kind={
                  questions
                    .filter((q) => CLIENT_PROMPT_KEYS.has(q.key) && q.required_for_complete)
                    .some((q) => missingRequired.includes(q.key))
                    ? "todo"
                    : "ready"
                }
                label={
                  questions
                    .filter((q) => CLIENT_PROMPT_KEYS.has(q.key) && q.required_for_complete)
                    .some((q) => missingRequired.includes(q.key))
                    ? "Nog invullen"
                    : "Klaar"
                }
              />
            </div>
            <p className="hint">
              Tone of voice en kernbeschrijvingen die HAMSTER meeneemt als context bij AI voor
              deze klant. Dit is geen systeemprompt — die blijven centraal bij Technisch beheer.
            </p>
            {questions
              .filter((question) => CLIENT_PROMPT_KEYS.has(question.key))
              .map((question) => {
                const required = Boolean(question.required_for_complete);
                const open = missingRequired.includes(question.key);
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
                      onChange={(e) => setAnswer(question.key, e.target.value)}
                      onBlur={() => {
                        flushAutosave().catch(() => {});
                      }}
                      placeholder={question.short_question || ""}
                    />
                  </label>
                );
              })}
          </section>

          <section className="card stack" id="setup-strategy">
            <div className="setup-block-head">
              <h4>Overige strategievragen</h4>
              <StatusPill
                kind={
                  questions
                    .filter((q) => !CLIENT_PROMPT_KEYS.has(q.key) && q.required_for_complete)
                    .some((q) => missingRequired.includes(q.key))
                    ? "todo"
                    : missingRequired.length
                      ? "todo"
                      : "ready"
                }
                label={
                  questions
                    .filter((q) => !CLIENT_PROMPT_KEYS.has(q.key) && q.required_for_complete)
                    .some((q) => missingRequired.includes(q.key))
                    ? "Nog invullen"
                    : "Klaar"
                }
              />
            </div>
            <p className="hint">
              Verplichte vragen moeten ingevuld zijn om de inrichting af te ronden. Optionele
              vragen mag je overslaan. Ook een gedeeltelijk concept wordt automatisch bewaard.
            </p>
            {questions
              .filter((question) => !CLIENT_PROMPT_KEYS.has(question.key))
              .map((question) => {
                const required = Boolean(question.required_for_complete);
                const open = missingRequired.includes(question.key);
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
                      onChange={(e) => setAnswer(question.key, e.target.value)}
                      onBlur={() => {
                        flushAutosave().catch(() => {});
                      }}
                      placeholder={question.short_question || ""}
                    />
                  </label>
                );
              })}
          </section>

          <section className="card stack" id="setup-targets">
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

          <section className="card stack" id="setup-links">
            <div className="setup-block-head">
              <h4>Canva-link</h4>
              <StatusPill
                kind={canvaFilled ? "ready" : "optional"}
                label={canvaFilled ? "Klaar" : "Optioneel"}
              />
            </div>
            <p className="hint">
              Optioneel — blokkeert afronden niet. Met Canva Connect (scope{" "}
              <code>design:content:read</code>) haalt HAMSTER voorstellen uit het ontwerp; anders
              blijft PDF-import hieronder beschikbaar.
            </p>
            <label>
              Canva-URL
              <input
                value={canvaUrl}
                onChange={(e) => {
                  const value = e.target.value;
                  canvaDraftRef.current = value;
                  setCanvaUrl(value);
                  markDirtyAndSchedule();
                }}
                onBlur={() => {
                  flushAutosave().catch(() => {});
                }}
                placeholder="https://www.canva.com/design/…"
              />
            </label>
            <button
              className="secondary"
              type="button"
              disabled={!activeId || busy === "canva-import"}
              onClick={previewCanvaProposals}
            >
              {busy === "canva-import" ? "Canva lezen…" : "Voorstellen ophalen uit Canva"}
            </button>
            {canvaImportHint ? <p className="banner warn-soft">{canvaImportHint}</p> : null}
            {importNote && importPreview?.source_kind === "canva" ? (
              <p className="hint">{importNote}</p>
            ) : null}
            {importPreview?.source_kind === "canva" ? (
              <div className="stack">
                <p className="banner">
                  Bron: Canva
                  {importPreview.canva_url ? ` · ${importPreview.canva_url}` : ""}
                  {(importPreview.filled_keys || []).length
                    ? ` · gevonden: ${(importPreview.filled_keys || []).join(", ")}`
                    : " · geen veldvoorstellen"}
                </p>
                {(importPreview.filled_keys || []).length ? (
                  <ul className="plain-list">
                    {(importPreview.filled_keys || []).map((key) => (
                      <li key={`canva-src-${key}`}>
                        {key}
                        <span className="hint">
                          {" "}
                          · bron:{" "}
                          {(importPreview.proposed?.field_sources || {})[key] || "Canva Connect"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div className="row-actions">
                  <button
                    className="primary"
                    type="button"
                    disabled={busy === "import" || !(importPreview.filled_keys || []).length}
                    onClick={stageImportProposal}
                  >
                    Voorstellen klaarzetten ter controle
                  </button>
                  <button className="secondary" type="button" onClick={() => setImportPreview(null)}>
                    Annuleren
                  </button>
                </div>
              </div>
            ) : null}
          </section>

          <section className="card stack" id="setup-pdf-import">
            <div className="setup-block-head">
              <h4>Voorstellen ophalen via PDF</h4>
              <StatusPill kind="optional" label="Optioneel" />
            </div>
            <p className="hint">
              Gebruik dit voor een Canva-strategie-PDF (of een andere tekst-PDF). Alleen informatie
              die in de PDF staat, wordt voorgesteld. Handmatige antwoorden blijven staan tot je
              goedkeurt.
            </p>
            <label className="secondary file-btn">
              {busy === "import" ? "PDF lezen…" : "PDF kiezen / Voorstellen ophalen via PDF"}
              <input
                ref={pdfInputRef}
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
            {importNote &&
            importPreview?.source_kind !== "figma" &&
            importPreview?.source_kind !== "canva" ? (
              <p className="hint">{importNote}</p>
            ) : null}
            {importPreview &&
            importPreview.source_kind !== "figma" &&
            importPreview.source_kind !== "canva" ? (
              <div className="stack">
                <p className="banner">
                  Bron: {importPreview.source_kind}
                  {importPreview.filename ? ` · ${importPreview.filename}` : ""}
                  {(importPreview.filled_keys || []).length
                    ? ` · gevonden: ${(importPreview.filled_keys || []).join(", ")}`
                    : " · geen veldvoorstellen"}
                </p>
                {(importPreview.filled_keys || []).length ? (
                  <ul className="plain-list">
                    {(importPreview.filled_keys || []).map((key) => (
                      <li key={`pdf-src-${key}`}>
                        {key}
                        <span className="hint">
                          {" "}
                          · bron:{" "}
                          {(importPreview.proposed?.field_sources || {})[key] ||
                            importPreview.source_kind ||
                            "PDF"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {(importPreview.missing || []).length ? (
                  <p className="banner warn-soft">
                    Niet inleesbaar / niet gevonden: {(importPreview.missing || []).slice(0, 8).join(" · ")}
                    {(importPreview.missing || []).length > 8
                      ? ` · +${(importPreview.missing || []).length - 8}`
                      : ""}
                  </p>
                ) : null}
                <div className="row-actions">
                  <button
                    className="primary"
                    type="button"
                    disabled={busy === "import"}
                    onClick={stageImportProposal}
                  >
                    Voorstellen klaarzetten ter controle
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
              Optioneel — blokkeert afronden niet. Plak een volledige URL of alleen de file key; de
              koppeling wordt automatisch bewaard. Voorstellen komen alleen uit tekst of
              planninglabels die aantoonbaar in Figma staan (geen verzonnen doelgroep).
            </p>
            <label>
              Figma-URL
              <input
                value={figmaUrl}
                onChange={(e) => {
                  const value = e.target.value;
                  figmaUrlDraftRef.current = value;
                  setFigmaUrl(value);
                  markDirtyAndSchedule();
                }}
                onBlur={() => {
                  flushAutosave().catch(() => {});
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
                  markDirtyAndSchedule();
                }}
                onBlur={() => {
                  flushAutosave().catch(() => {});
                }}
                placeholder="bestandssleutel"
              />
            </label>
            {figmaFilled ? (
              <button
                className="secondary"
                type="button"
                disabled={!activeId || busy === "figma-import"}
                onClick={previewFigmaProposals}
              >
                {busy === "figma-import" ? "Figma lezen…" : "Voorstellen ophalen uit Figma"}
              </button>
            ) : (
              <p className="hint">Bewaar eerst een Figma-URL of file key om voorstellen op te halen.</p>
            )}
            {importNote && importPreview?.source_kind === "figma" ? (
              <p className="hint">{importNote}</p>
            ) : null}
            {importPreview?.source_kind === "figma" ? (
              <div className="stack">
                <p className="banner">
                  Bron: Figma
                  {importPreview.source_url ? ` · ${importPreview.source_url}` : ""}
                  {(importPreview.filled_keys || []).length
                    ? ` · gevonden: ${(importPreview.filled_keys || []).join(", ")}`
                    : " · geen veldvoorstellen"}
                </p>
                {(importPreview.filled_keys || []).length ? (
                  <ul className="plain-list">
                    {(importPreview.filled_keys || []).map((key) => (
                      <li key={`figma-src-${key}`}>
                        {key}
                        <span className="hint">
                          {" "}
                          · bron:{" "}
                          {(importPreview.proposed?.field_sources || {})[key] || "Figma"}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">
                    Geen strategie-informatie gevonden. Handmatige invoer blijft beschikbaar.
                  </p>
                )}
                <div className="row-actions">
                  <button
                    className="primary"
                    type="button"
                    disabled={busy === "import" || !(importPreview.filled_keys || []).length}
                    onClick={stageImportProposal}
                  >
                    Voorstellen klaarzetten ter controle
                  </button>
                  <button className="secondary" type="button" onClick={() => setImportPreview(null)}>
                    Annuleren
                  </button>
                </div>
              </div>
            ) : null}
          </section>

          {proposalDraft ? (
            <section className="card stack" aria-label="Voorstel ter controle">
              <div className="setup-block-head">
                <h4>Voorstel ter controle</h4>
                <StatusPill kind="review" label="Te controleren" />
              </div>
              <p className="hint">
                Pas voorstellen aan en keur goed. Alleen lege velden worden overgenomen.
                Bron: {proposalDraft.source_kind || "import"}
                {proposalDraft.filename ? ` · ${proposalDraft.filename}` : ""}.
              </p>
              {Object.keys(proposalDraft.start_answers || {}).length ? (
                <div className="stack">
                  {questions
                    .filter((q) => (proposalDraft.start_answers || {})[q.key])
                    .map((question) => (
                      <label key={`prop-${question.key}`}>
                        {question.label}
                        <span className="hint">
                          {" "}
                          · bron:{" "}
                          {(proposalDraft.field_sources || {})[question.key] ||
                            proposalDraft.source_kind ||
                            "import"}
                        </span>
                        <textarea
                          rows={3}
                          value={(proposalDraft.start_answers || {})[question.key] || ""}
                          onChange={(e) => setProposalAnswer(question.key, e.target.value)}
                        />
                      </label>
                    ))}
                </div>
              ) : null}
              {Object.entries(proposalDraft.strategy_fields || {})
                .filter(([key]) => !["canva_strategy_url", "canva_url"].includes(key))
                .map(([key, value]) => (
                  <label key={`prop-field-${key}`}>
                    {key}
                    <span className="hint">
                      {" "}
                      · bron: {(proposalDraft.field_sources || {})[key] || proposalDraft.source_kind || "import"}
                    </span>
                    <textarea
                      rows={3}
                      value={value || ""}
                      onChange={(e) => setProposalField(key, e.target.value)}
                    />
                  </label>
                ))}
              {!Object.keys(proposalDraft.start_answers || {}).length &&
              !Object.keys(proposalDraft.strategy_fields || {}).length ? (
                <p className="muted">Geen nieuwe voorstellen (velden waren al gevuld).</p>
              ) : null}
              <div className="row-actions wrap">
                <button
                  className="primary"
                  type="button"
                  disabled={busy === "proposal"}
                  onClick={approveProposal}
                >
                  Voorstel goedkeuren
                </button>
                <button
                  className="secondary"
                  type="button"
                  disabled={busy === "proposal"}
                  onClick={discardProposal}
                >
                  Voorstel verwerpen
                </button>
              </div>
            </section>
          ) : null}

          <section className="card stack" id="setup-competitors">
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
            <button className="secondary" type="button" onClick={() => goToStep(2)}>
              Vorige
            </button>
            <button
              className="primary"
              type="button"
              disabled={saveStatus === "saving"}
              onClick={() => goToStep(4)}
            >
              {saveStatus === "saving" ? "Bezig met opslaan…" : "Volgende: controleren"}
            </button>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="card stack">
          <h3>4. Gegevens controleren en afronden</h3>
          <p className="hint">
            Controleer wat jij nog moet doen, wat HAMSTER al klaarzet, en wat nog ontbreekt. Afronden
            kan pas als alle verplichte onderdelen klaar zijn. Canva en Figma zijn optioneel.
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
            <button className="secondary" type="button" onClick={() => goToStep(3)}>
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
