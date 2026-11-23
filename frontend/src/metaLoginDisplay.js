/** Pure helpers for Meta login attempt status (shared by Klant inrichten / MetaConnectFlow). */

export const META_LINKING_LABEL = "Bezig met koppelen…";
export const META_ABORTED_LABEL = "Koppeling afgebroken";

/**
 * Decide which status banner to show for the current Meta attempt.
 * While linking, previous status_detail / metaError must not be shown.
 */
export function metaAttemptBanner({
  linkPhase = "idle",
  attemptError = "",
  metaError = "",
  statusDetail = "",
  statusLabel = "",
  connected = false,
} = {}) {
  if (linkPhase === "linking") {
    return { kind: "progress", text: META_LINKING_LABEL };
  }
  const attempt = String(attemptError || "").trim();
  if (attempt) {
    return { kind: "error", text: attempt };
  }
  if (linkPhase === "aborted") {
    return { kind: "error", text: META_ABORTED_LABEL };
  }
  const fromOauth = String(metaError || "").trim();
  if (fromOauth) {
    return { kind: "error", text: fromOauth };
  }
  const detail = String(statusDetail || "").trim();
  if (detail && !connected) {
    const label = String(statusLabel || "").trim();
    return {
      kind: "error",
      text: label
        ? `Status: Nog niet gekoppeld — ${detail}`
        : detail,
    };
  }
  if (statusLabel) {
    return {
      kind: connected ? "ok" : "error",
      text: connected ? "Status: Gekoppeld" : "Status: Nog niet gekoppeld",
    };
  }
  return null;
}

/** Strip stored previous-attempt detail from meta while a new attempt is active. */
export function metaForDisplay(meta, { linkPhase, attemptError } = {}) {
  if (!meta) return meta;
  if (linkPhase === "linking" || linkPhase === "aborted" || attemptError) {
    return { ...meta, status_detail: null };
  }
  return meta;
}
