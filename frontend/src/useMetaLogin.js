import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { META_ABORTED_LABEL, metaForDisplay } from "./metaLoginDisplay.js";

export { metaForDisplay };

/**
 * Shared Meta login attempt state for Klant inrichten (and any future client-settings embed).
 * Hides the previous attempt's error while a new popup/tab login is in progress.
 */
export function useMetaLogin({
  clientId,
  loadClients,
  refreshMeta,
  onMetaReturnHandled,
  onError,
  onClearMetaError,
  onNotice,
}) {
  const [busy, setBusy] = useState("");
  const [sameTabUrl, setSameTabUrl] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [linkPhase, setLinkPhase] = useState("idle"); // idle | linking | aborted
  const [attemptError, setAttemptError] = useState("");
  const popupRef = useRef(null);
  const timerRef = useRef(null);
  const settledRef = useRef(false);
  const linkingRef = useRef(false);
  const detailAtStartRef = useRef("");

  const clearAttemptErrors = useCallback(() => {
    setAttemptError("");
    setLinkPhase("idle");
    onError?.("");
    onClearMetaError?.();
  }, [onError, onClearMetaError]);

  const markSettled = useCallback(() => {
    settledRef.current = true;
    linkingRef.current = false;
  }, []);

  const stopWatching = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => () => stopWatching(), [stopWatching]);

  const finishSuccess = useCallback(
    (notice) => {
      markSettled();
      stopWatching();
      setBusy("");
      setLinkPhase("idle");
      setAttemptError("");
      onClearMetaError?.();
      onError?.("");
      if (notice) onNotice?.(notice);
      onMetaReturnHandled?.();
    },
    [markSettled, stopWatching, onClearMetaError, onError, onNotice, onMetaReturnHandled],
  );

  const finishFailure = useCallback(
    (message) => {
      markSettled();
      stopWatching();
      setBusy("");
      setLinkPhase("idle");
      const text = message || "De koppeling is mislukt. Probeer het opnieuw.";
      setAttemptError(text);
      // Show only in MetaConnectFlow; clear App/page leftovers from the prior attempt.
      onClearMetaError?.();
      onError?.("");
    },
    [markSettled, stopWatching, onClearMetaError, onError],
  );

  const finishAborted = useCallback(() => {
    markSettled();
    stopWatching();
    setBusy("");
    setLinkPhase("aborted");
    setAttemptError(META_ABORTED_LABEL);
    onError?.("");
    onClearMetaError?.();
  }, [markSettled, stopWatching, onError, onClearMetaError]);

  const watchPopup = useCallback(
    (popup) => {
      stopWatching();
      timerRef.current = window.setInterval(() => {
        if (!popup.closed) return;
        stopWatching();
        popupRef.current = null;
        // Give BroadcastChannel / postMessage a moment to settle the attempt.
        window.setTimeout(async () => {
          if (settledRef.current) {
            setBusy("");
            return;
          }
          try {
            await loadClients?.();
            const payload = await refreshMeta?.();
            if (payload?.pages?.selectable?.length) {
              finishSuccess("Inloggen gelukt. Kies hieronder de juiste accounts.");
              return;
            }
            // Only treat status_detail as this attempt's error when it changed since start.
            // Otherwise an aborted popup would revive the previous attempt's message.
            const detail = String(payload?.status_detail || "").trim();
            const prior = String(detailAtStartRef.current || "").trim();
            if (detail && detail !== prior && linkingRef.current) {
              finishFailure(detail);
              return;
            }
            if (!settledRef.current) {
              finishAborted();
            }
          } catch (exc) {
            if (!settledRef.current) {
              finishFailure(exc.message);
            }
          }
        }, 400);
      }, 500);
    },
    [stopWatching, loadClients, refreshMeta, finishSuccess, finishFailure, finishAborted],
  );

  const startLogin = useCallback(
    async ({ forceSameTab = false } = {}) => {
      if (!clientId) return;
      settledRef.current = false;
      linkingRef.current = true;
      setSameTabUrl("");
      setAttemptError("");
      setLinkPhase("linking");
      onError?.("");
      onClearMetaError?.();
      onNotice?.("");
      setBusy("start");
      try {
        // Snapshot prior failure text so a closed popup does not revive it.
        try {
          const current = await refreshMeta?.(clientId);
          detailAtStartRef.current = String(current?.status_detail || "").trim();
        } catch {
          detailAtStartRef.current = "";
        }
        const payload = await api(`/api/clients/${clientId}/meta/start`, {
          method: "POST",
          body: { popup: !forceSameTab },
        });
        const url = payload.login_url || "";
        if (!url) {
          throw new Error("Meta gaf geen login-adres terug.");
        }
        if (forceSameTab) {
          window.location.assign(url);
          return;
        }
        const popup = window.open(url, "maaike-meta-login", "popup=yes,width=720,height=780");
        if (!popup) {
          setSameTabUrl(url);
          setBusy("");
          setLinkPhase("idle");
          linkingRef.current = false;
          setAttemptError(
            "De browser blokkeerde de pop-up. Gebruik de knop om in dit tabblad verder te gaan.",
          );
          return;
        }
        popupRef.current = popup;
        onNotice?.("Log in bij Meta in het geopende venster. Dit scherm werkt verder als je terugkomt.");
        watchPopup(popup);
      } catch (exc) {
        linkingRef.current = false;
        setBusy("");
        setLinkPhase("idle");
        setAttemptError(exc.message);
        onClearMetaError?.();
        onError?.("");
      }
    },
    [clientId, onError, onClearMetaError, onNotice, watchPopup, refreshMeta],
  );

  /** Call when the parent receives an OAuth return (success or error) for this attempt. */
  const applyOauthReturn = useCallback(
    ({ ok, error } = {}) => {
      if (ok) {
        finishSuccess("Inloggen gelukt. Kies hieronder de juiste accounts.");
        return;
      }
      finishFailure(error || "De koppeling is mislukt. Probeer het opnieuw.");
    },
    [finishSuccess, finishFailure],
  );

  return {
    busy,
    setBusy,
    sameTabUrl,
    pageIndex,
    setPageIndex,
    linkPhase,
    attemptError,
    setAttemptError,
    clearAttemptErrors,
    startLogin,
    applyOauthReturn,
    finishSuccess,
    markSettled,
  };
}
