import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const META_MISSING_STEP =
  "Koppel eerst het Facebook- en Instagram-account van deze klant om berichten van concurrenten op te halen.";

function fmt(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString("nl-NL");
  return String(value);
}

function fmtAvg(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("nl-NL", { maximumFractionDigits: 1 });
}

export default function ComparisonPage({ client, onOpenConnect, canEdit = true }) {
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adminErrorDetail, setAdminErrorDetail] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  // Voortgang bij ophalen (punt 23)
  const [fetchProgress, setFetchProgress] = useState(null); // { current, total, currentHandle, label }
  const [fetchOutcome, setFetchOutcome] = useState(null); // { tone: "ok" | "warn" | "error", text: string }

  // Concurrent toevoegen (punt 21)
  const [adding, setAdding] = useState(false);
  const [competitorInput, setCompetitorInput] = useState("");

  // Concurrent verwijderen met bevestiging (punt 22)
  const [pendingDelete, setPendingDelete] = useState(null); // string username

  // Periode & wekelijkse controle (punt 25)
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [weeklyOpen, setWeeklyOpen] = useState(false);

  const activeClientIdRef = useRef(client.id);
  activeClientIdRef.current = client.id;

  const applyPayloadForClient = useCallback((targetClientId, payload) => {
    if (Number(activeClientIdRef.current) !== Number(targetClientId)) return false;
    if (payload?.client_id != null && Number(payload.client_id) !== Number(targetClientId)) {
      return false;
    }
    setState(payload);
    if (payload?.period_start) setCustomStart(payload.period_start);
    if (payload?.period_end) setCustomEnd(payload.period_end);
    return true;
  }, []);

  const reload = useCallback(
    async (targetClientId = client.id, isCurrent = () => true) => {
      const payload = await api(`/api/clients/${targetClientId}/comparison`);
      if (!isCurrent()) return null;
      applyPayloadForClient(targetClientId, payload);
      return payload;
    },
    [applyPayloadForClient, client.id],
  );

  // Schone reset bij wisselen van klant zodat nooit oude concurrenten of cijfers blijven staan
  useEffect(() => {
    let cancelled = false;
    const targetClientId = client.id;
    setLoading(true);
    setState(null);
    setError("");
    setAdminErrorDetail("");
    setNotice("");
    setBusy("");
    setFetchProgress(null);
    setFetchOutcome(null);
    setAdding(false);
    setCompetitorInput("");
    setPendingDelete(null);
    setWeeklyOpen(false);
    setCustomStart("");
    setCustomEnd("");

    reload(targetClientId, () => !cancelled)
      .catch((exc) => {
        if (cancelled) return;
        setError("De concurrentengegevens konden niet worden geladen.");
        setAdminErrorDetail(exc.message || "");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [client.id, reload]);

  async function changePeriod(periodKey) {
    const targetClientId = client.id;
    setBusy("period");
    setError("");
    setAdminErrorDetail("");
    try {
      const body = { period_key: periodKey };
      if (periodKey === "custom") {
        body.custom_start = customStart || null;
        body.custom_end = customEnd || null;
      }
      const payload = await api(`/api/clients/${targetClientId}/comparison/period`, {
        method: "POST",
        body,
      });
      applyPayloadForClient(targetClientId, payload);
    } catch (exc) {
      setError(exc.message || "De periode kon niet worden aangepast.");
    } finally {
      setBusy("");
    }
  }

  async function addCompetitor(event) {
    if (event) event.preventDefault();
    const targetClientId = client.id;
    const cleanHandle = competitorInput.trim().replace(/^@/, "").trim();
    if (!cleanHandle) {
      setError("Vul een Instagram-gebruikersnaam in, bijvoorbeeld @gebruikersnaam.");
      return;
    }
    setBusy("add");
    setError("");
    setAdminErrorDetail("");
    setNotice("");
    try {
      const payload = await api(`/api/clients/${targetClientId}/comparison/competitors`, {
        method: "POST",
        body: { name: cleanHandle },
      });
      if (applyPayloadForClient(targetClientId, payload)) {
        setCompetitorInput("");
        setAdding(false);
        setNotice(`Concurrent @${cleanHandle.toLowerCase()} is toegevoegd aan ${client.name}.`);
      }
    } catch (exc) {
      setError(exc.message || "Concurrent toevoegen is niet gelukt.");
    } finally {
      setBusy("");
    }
  }

  async function confirmRemoveCompetitor() {
    if (!pendingDelete) return;
    const username = pendingDelete;
    const targetClientId = client.id;
    setBusy(`remove-${username}`);
    setError("");
    setAdminErrorDetail("");
    setNotice("");
    try {
      const payload = await api(
        `/api/clients/${targetClientId}/comparison/competitors/${encodeURIComponent(username)}`,
        { method: "DELETE" },
      );
      if (applyPayloadForClient(targetClientId, payload)) {
        setPendingDelete(null);
        setNotice(`Concurrent @${username} is verwijderd uit de lijst van ${client.name}.`);
      }
    } catch (exc) {
      const rawMsg = String(exc?.message || "");
      const isNetworkErr = rawMsg.toLowerCase().includes("failed to fetch");
      setError(
        isNetworkErr
          ? `Verwijderen van @${username} is tijdelijk niet gelukt. Probeer het nog eens.`
          : rawMsg || `Verwijderen van @${username} is niet gelukt.`,
      );
      if (isNetworkErr) setAdminErrorDetail(rawMsg);
    } finally {
      setBusy("");
    }
  }

  async function fetchAllCompetitors() {
    const targetClientId = client.id;
    const handles = state?.competitors || [];
    setError("");
    setAdminErrorDetail("");
    setNotice("");
    setFetchOutcome(null);

    if (!state?.meta_connection?.connected) {
      setError(META_MISSING_STEP);
      return;
    }
    if (!handles.length) {
      setFetchOutcome({
        tone: "warn",
        text: "Er staan nog geen concurrenten op de lijst. Voeg eerst een concurrent toe via ‘Concurrent toevoegen’.",
      });
      return;
    }

    setBusy("refresh");
    const succeeded = [];
    const failed = [];
    const techErrors = [];

    try {
      for (let i = 0; i < handles.length; i += 1) {
        if (Number(activeClientIdRef.current) !== Number(targetClientId)) return;
        const handle = handles[i];
        setFetchProgress({
          current: i + 1,
          total: handles.length,
          currentHandle: handle,
          label: `Bezig met ophalen (${i + 1} van ${handles.length}): @${handle}…`,
        });

        try {
          const res = await api(`/api/clients/${targetClientId}/comparison/competitors/refresh`, {
            method: "POST",
            body: { username: handle, max_accounts: 1 },
          });
          const okItem = (res.crawled || [])[0];
          const errItem = (res.errors || [])[0];
          if (okItem && !errItem) {
            const count = Number(okItem.posts_saved ?? 0);
            succeeded.push(`@${okItem.username} (${count} ${count === 1 ? "bericht" : "berichten"})`);
          } else {
            failed.push(`@${handle}`);
            if (errItem?.error) techErrors.push(`@${handle}: ${errItem.error}`);
          }
        } catch (stepExc) {
          failed.push(`@${handle}`);
          if (stepExc?.message) techErrors.push(`@${handle}: ${stepExc.message}`);
        }
      }

      if (Number(activeClientIdRef.current) !== Number(targetClientId)) return;
      await reload(targetClientId);

      if (succeeded.length && !failed.length) {
        setFetchOutcome({
          tone: "ok",
          text: `Het ophalen is gelukt! Berichten zijn bijgewerkt voor ${succeeded.join(", ")}.`,
        });
      } else if (succeeded.length && failed.length) {
        setFetchOutcome({
          tone: "warn",
          text: `Het ophalen is deels gelukt: bijgewerkt voor ${succeeded.join(", ")}; niet gelukt voor ${failed.join(", ")}. Controleer de melding bij ‘Actie nodig’.`,
        });
        if (techErrors.length) setAdminErrorDetail(techErrors.join(" | "));
      } else {
        setFetchOutcome({
          tone: "error",
          text: `Het ophalen is niet gelukt voor ${failed.join(", ")}. Controleer de gebruikersnaam of probeer het later opnieuw.`,
        });
        if (techErrors.length) setAdminErrorDetail(techErrors.join(" | "));
      }
    } finally {
      if (Number(activeClientIdRef.current) === Number(targetClientId)) {
        setFetchProgress(null);
        setBusy("");
      }
    }
  }

  async function refetchOneCompetitor(username) {
    const target = String(username || "").trim().replace(/^@/, "");
    if (!target) return;
    const targetClientId = client.id;
    setError("");
    setAdminErrorDetail("");
    setNotice("");
    setFetchOutcome(null);

    if (!state?.meta_connection?.connected) {
      setError(META_MISSING_STEP);
      return;
    }

    setBusy(`crawl-${target}`);
    setFetchProgress({
      current: 1,
      total: 1,
      currentHandle: target,
      label: `Bezig met opnieuw ophalen van @${target}…`,
    });

    try {
      const res = await api(`/api/clients/${targetClientId}/comparison/competitors/refresh`, {
        method: "POST",
        body: { username: target, max_accounts: 1 },
      });
      if (Number(activeClientIdRef.current) !== Number(targetClientId)) return;
      await reload(targetClientId);

      const okItem = (res.crawled || [])[0];
      const errItem = (res.errors || [])[0];
      if (okItem && !errItem) {
        const count = Number(okItem.posts_saved ?? 0);
        setFetchOutcome({
          tone: "ok",
          text: `Het opnieuw ophalen van @${target} is gelukt (${count} ${count === 1 ? "bericht" : "berichten"} opgeslagen).`,
        });
      } else {
        setFetchOutcome({
          tone: "error",
          text: `Het opnieuw ophalen van @${target} is niet gelukt. Controleer of @${target} een openbaar zakelijk Instagram-account is.`,
        });
        if (errItem?.error) setAdminErrorDetail(`@${target}: ${errItem.error}`);
      }
    } catch (exc) {
      if (Number(activeClientIdRef.current) !== Number(targetClientId)) return;
      setFetchOutcome({
        tone: "error",
        text: exc.message === META_MISSING_STEP
          ? META_MISSING_STEP
          : `Het opnieuw ophalen van @${target} is niet gelukt.`,
      });
      if (exc?.message && exc.message !== META_MISSING_STEP) {
        setAdminErrorDetail(exc.message);
      }
    } finally {
      if (Number(activeClientIdRef.current) === Number(targetClientId)) {
        setFetchProgress(null);
        setBusy("");
      }
    }
  }

  if (loading && !state) {
    return (
      <p className="muted">
        Concurrenten van <strong>{client.name}</strong> laden…
      </p>
    );
  }

  if (!state) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Geen gegevens beschikbaar.</p>;
  }

  const metaConnected = Boolean(state.meta_connection?.connected);
  const competitorRows = (state.account_rows || []).filter((r) => r.role === "competitor");
  const weeklyPlan = state.weekly_plan || {};
  const isFetchingAny = busy === "refresh" || busy.startsWith("crawl-");

  return (
    <div className="stack comparison-page">
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      {/* Punt 24: Concrete Meta-vervolgstap met directe koppelknop — uitsluitend als koppeling ontbreekt */}
      {!metaConnected ? (
        <section
          className="card stack"
          aria-label="Meta-koppeling vereist"
          style={{
            background: "rgba(245, 158, 11, 0.16)",
            borderColor: "rgba(251, 191, 36, 0.48)",
            gap: "0.75rem",
          }}
        >
          <div
            className="row-actions wrap"
            style={{ justifyContent: "space-between", alignItems: "center", gap: "1rem" }}
          >
            <div className="stack" style={{ gap: "0.25rem", maxWidth: "44rem" }}>
              <strong style={{ fontSize: "1.05rem", color: "#fde68a" }}>
                Accountkoppeling nodig voor {client.name}
              </strong>
              <p style={{ margin: 0 }}>
                {state.meta_connection?.missing_message || META_MISSING_STEP}
              </p>
              <span className="hint" style={{ margin: 0 }}>
                Je kunt hieronder alvast concurrenten op de lijst zetten. Zodra Facebook en Instagram gekoppeld zijn, kun je hun berichten direct ophalen.
              </span>
            </div>
            {onOpenConnect ? (
              <button className="primary" type="button" onClick={() => onOpenConnect()}>
                Facebook en Instagram koppelen
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* Punt 23: Duidelijke hoofdknop met éénzinsuitleg, voortgang & resultaatmelding */}
      <section
        className="card stack"
        aria-label="Berichten van concurrenten ophalen"
        style={{
          background: metaConnected ? "rgba(16, 185, 129, 0.1)" : undefined,
          borderColor: metaConnected ? "rgba(52, 211, 153, 0.35)" : undefined,
          gap: "0.8rem",
        }}
      >
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}
        >
          <div className="stack" style={{ gap: "0.3rem", maxWidth: "44rem" }}>
            <strong style={{ fontSize: "1.1rem" }}>Concurrenten van {client.name}</strong>
            <p style={{ margin: 0 }}>
              {state.refresh?.explanation ||
                "Haalt de nieuwste openbare Instagram-berichten, likes en reacties van je ingestelde concurrenten op."}
            </p>
            <span className="hint" style={{ margin: 0 }}>
              {metaConnected ? (
                <>
                  Gekoppeld account:{" "}
                  <strong>
                    {state.meta_connection?.facebook_page_name || client.name}
                    {state.meta_connection?.instagram_username
                      ? ` (@${state.meta_connection.instagram_username})`
                      : ""}
                  </strong>
                  {state.period_label ? ` · Vergelijkingsperiode: ${state.period_label}` : ""}
                </>
              ) : (
                "Berichten ophalen wordt beschikbaar zodra Facebook en Instagram voor deze klant zijn gekoppeld."
              )}
            </span>
          </div>

          {canEdit ? (
          <button
            className="primary"
            type="button"
            disabled={!metaConnected || isFetchingAny || Boolean(busy)}
            onClick={fetchAllCompetitors}
          >
            {isFetchingAny
              ? "Berichten van concurrenten ophalen…"
              : "Berichten van concurrenten ophalen"}
          </button>
          ) : (
            <p className="hint">Berichten van concurrenten ophalen doet een editor. Jij kunt de lijst bekijken.</p>
          )}
        </div>

        {/* Live voortgang tijdens het ophalen */}
        {fetchProgress ? (
          <div
            className="stack"
            role="status"
            aria-live="polite"
            style={{
              padding: "0.7rem 0.9rem",
              borderRadius: "8px",
              background: "rgba(59, 130, 246, 0.16)",
              border: "1px solid rgba(96, 165, 250, 0.45)",
              gap: "0.45rem",
            }}
          >
            <strong>{fetchProgress.label}</strong>
            <div
              style={{
                width: "100%",
                height: "8px",
                borderRadius: "999px",
                background: "rgba(255, 255, 255, 0.12)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.max(15, Math.round((fetchProgress.current / Math.max(1, fetchProgress.total)) * 100))}%`,
                  height: "100%",
                  background: "#f36f38",
                  transition: "width 0.25s ease",
                }}
              />
            </div>
          </div>
        ) : null}

        {/* Duidelijke terugkoppeling na het ophalen */}
        {fetchOutcome ? (
          <p
            className={
              fetchOutcome.tone === "error"
                ? "banner error"
                : fetchOutcome.tone === "warn"
                  ? "banner warn-soft"
                  : "banner"
            }
            style={{ margin: 0 }}
          >
            {fetchOutcome.text}
          </p>
        ) : null}

        {adminErrorDetail ? (
          <details>
            <summary className="hint" style={{ cursor: "pointer" }}>
              Technische foutdetails (alleen voor beheer)
            </summary>
            <pre
              className="hint"
              style={{
                whiteSpace: "pre-wrap",
                marginTop: "0.4rem",
                padding: "0.6rem",
                background: "rgba(0, 0, 0, 0.28)",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                borderRadius: "6px",
              }}
            >
              {adminErrorDetail}
            </pre>
          </details>
        ) : null}
      </section>

      {/* Punt 21 & 22: Concurrentenlijst, duidelijk toevoegen (@gebruikersnaam), status per concurrent & verwijderbevestiging */}
      <section className="card stack" aria-label="Ingestelde concurrenten">
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "center", gap: "0.75rem" }}
        >
          <div>
            <h3 style={{ margin: 0 }}>
              Ingestelde concurrenten ({state.competitors.length} van maximaal 10)
            </h3>
            <p className="hint" style={{ margin: "0.2rem 0 0" }}>
              Hier zie je voor <strong>{client.name}</strong> per concurrent of er al berichten klaarstaan, wanneer het ophalen voor het laatst is gelukt en of er nog actie nodig is.
            </p>
          </div>
          {canEdit && !adding ? (
            <button
              className="primary"
              type="button"
              disabled={state.competitors.length >= 10 || Boolean(busy)}
              onClick={() => {
                setError("");
                setAdding(true);
              }}
            >
              Concurrent toevoegen
            </button>
          ) : null}
        </div>

        {adding ? (
          <form
            onSubmit={addCompetitor}
            className="stack"
            style={{
              padding: "0.85rem",
              borderRadius: "8px",
              background: "rgba(255, 255, 255, 0.04)",
              border: "1px solid rgba(255, 255, 255, 0.14)",
              gap: "0.65rem",
            }}
          >
            <div className="row-actions wrap" style={{ alignItems: "flex-end", gap: "0.75rem" }}>
              <label style={{ flex: "1 1 260px" }}>
                Instagram-account van concurrent (voorbeeld: @gebruikersnaam)
                <input
                  value={competitorInput}
                  onChange={(e) => setCompetitorInput(e.target.value)}
                  placeholder="@gebruikersnaam"
                  autoFocus
                />
              </label>
              <button className="primary" type="submit" disabled={busy === "add"}>
                {busy === "add" ? "Bezig met toevoegen…" : "Concurrent toevoegen"}
              </button>
              <button
                className="secondary"
                type="button"
                disabled={busy === "add"}
                onClick={() => {
                  setAdding(false);
                  setCompetitorInput("");
                }}
              >
                Annuleren
              </button>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Vul een openbaar zakelijk Instagram-account in, bijvoorbeeld <strong>@gebruikersnaam</strong>.
            </p>
          </form>
        ) : null}

        {!state.competitors.length ? (
          <p className="hint" style={{ margin: 0 }}>
            Er zijn nog geen concurrenten toegevoegd voor <strong>{client.name}</strong>. Klik op{" "}
            <strong>Concurrent toevoegen</strong> en vul bijvoorbeeld <strong>@gebruikersnaam</strong> in.
          </p>
        ) : (
          <div className="report-list stack">
            {state.competitors.map((name) => {
              const row = competitorRows.find((r) => r.username === name) || {};
              const rowNeedsAction = Boolean(row.action_needed);
              const isRowCrawling = busy === `crawl-${name}`;
              const isRowRemoving = busy === `remove-${name}`;
              return (
                <div
                  className="report-list-row"
                  key={name}
                  style={{
                    alignItems: "flex-start",
                    gap: "1rem",
                    borderColor: rowNeedsAction
                      ? "rgba(251, 191, 36, 0.4)"
                      : "rgba(52, 211, 153, 0.3)",
                  }}
                >
                  <div className="report-list-main stack" style={{ gap: "0.4rem", flex: "1 1 320px" }}>
                    <div className="row-actions wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
                      <strong className="report-list-title" style={{ fontSize: "1.02rem" }}>
                        @{name}
                      </strong>
                      <span
                        className="badge"
                        style={{
                          background: rowNeedsAction
                            ? "rgba(245, 158, 11, 0.2)"
                            : "rgba(16, 185, 129, 0.22)",
                          color: rowNeedsAction ? "#fde68a" : "#6ee7b7",
                          border: rowNeedsAction
                            ? "1px solid rgba(251, 191, 36, 0.45)"
                            : "1px solid rgba(52, 211, 153, 0.45)",
                        }}
                      >
                        {rowNeedsAction ? "Actie nodig" : "Klaar"}
                      </span>
                      {row.followers != null ? (
                        <span className="hint">{fmt(row.followers)} volgers</span>
                      ) : null}
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
                        gap: "0.45rem 1rem",
                        fontSize: "0.92rem",
                      }}
                    >
                      <div>
                        <span className="hint">Berichten opgehaald: </span>
                        <strong>{row.posts_fetched_label || "Nog geen berichten opgehaald"}</strong>
                      </div>
                      <div>
                        <span className="hint">Laatst gelukt: </span>
                        <strong>{row.last_succeeded_label || "Nog niet gelukt"}</strong>
                      </div>
                    </div>

                    <p
                      style={{
                        margin: 0,
                        fontSize: "0.9rem",
                        color: rowNeedsAction ? "#fcd34d" : "#a1baca",
                      }}
                    >
                      <strong>{rowNeedsAction ? "Wat je kunt doen: " : "Stand: "}</strong>
                      {row.action_label || "Klik op ‘Opnieuw ophalen’ om berichten te vernieuwen."}
                    </p>

                    {row.admin_error_detail ? (
                      <details>
                        <summary className="hint" style={{ cursor: "pointer" }}>
                          Technische foutdetails voor @{name} (alleen voor beheer)
                        </summary>
                        <pre
                          className="hint"
                          style={{
                            whiteSpace: "pre-wrap",
                            marginTop: "0.3rem",
                            padding: "0.5rem",
                            background: "rgba(0, 0, 0, 0.25)",
                            borderRadius: "6px",
                          }}
                        >
                          {row.admin_error_detail}
                        </pre>
                      </details>
                    ) : null}
                  </div>

                  <div className="report-list-actions" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    {canEdit ? (
                    <>
                    <button
                      className="secondary"
                      type="button"
                      disabled={!metaConnected || Boolean(busy)}
                      title={
                        !metaConnected
                          ? META_MISSING_STEP
                          : `Haal de berichten van @${name} opnieuw op`
                      }
                      onClick={() => refetchOneCompetitor(name)}
                    >
                      {isRowCrawling ? "Bezig met ophalen…" : "Opnieuw ophalen"}
                    </button>
                    <button
                      className="secondary"
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => setPendingDelete(name)}
                    >
                      {isRowRemoving ? "Verwijderen…" : "Concurrent verwijderen"}
                    </button>
                    </>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Punt 25: Begrijpelijke wekelijkse controle (behoudt bestaande planning & automatische uurlijkse uitvoering) */}
      <section className="card stack" aria-label="Wekelijkse controle concurrenten" style={{ gap: "0.85rem" }}>
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}
        >
          <div className="stack" style={{ gap: "0.25rem", maxWidth: "44rem" }}>
            <div className="row-actions wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Wekelijkse controle</h3>
              {weeklyPlan.has_responsible ? (
                <span
                  className="badge"
                  style={{
                    background: "rgba(16, 185, 129, 0.22)",
                    color: "#6ee7b7",
                    border: "1px solid rgba(52, 211, 153, 0.45)",
                  }}
                >
                  Verantwoordelijke: {weeklyPlan.responsible_name}
                </span>
              ) : null}
              <span className="badge">
                {weeklyPlan.enabled
                  ? `Elke ${weeklyPlan.weekday_label || "maandag"} om ${weeklyPlan.time || "09:00"}`
                  : "Nog geen vaste dag ingesteld"}
              </span>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Zo weet Jet of Mo precies wanneer de concurrentencheck voor <strong>{client.name}</strong> gepland staat, wat automatisch op de achtergrond gebeurt en wat je zelf nakijkt.
            </p>
          </div>

          <button
            className="secondary"
            type="button"
            onClick={() => setWeeklyOpen((open) => !open)}
          >
            {weeklyOpen ? "Planning sluiten" : "Planning & verantwoordelijke"}
          </button>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: "0.75rem",
          }}
        >
          <div
            className="stack"
            style={{
              padding: "0.8rem",
              borderRadius: "8px",
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              gap: "0.35rem",
            }}
          >
            <strong>1. Wanneer staat dit gepland?</strong>
            <p style={{ margin: 0, fontSize: "0.92rem" }}>
              {weeklyPlan.schedule_summary ||
                "Nog geen vast controlemoment ingepland. Stel een vaste dag en tijd in via ‘Planning & verantwoordelijke’."}
            </p>
            {weeklyPlan.note ? (
              <p className="hint" style={{ margin: 0 }}>
                Werkafspraak: <strong>{weeklyPlan.note}</strong>
              </p>
            ) : null}
          </div>

          <div
            className="stack"
            style={{
              padding: "0.8rem",
              borderRadius: "8px",
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              gap: "0.35rem",
            }}
          >
            <strong>2. Automatisch of handmatig?</strong>
            <p style={{ margin: 0, fontSize: "0.92rem" }}>
              <strong>Ophalen (automatisch):</strong>{" "}
              {weeklyPlan.background_fetch_summary ||
                "Buiten werktijd (ma–vr na 18:00 en in het weekend) werkt HAMSTER elk uur automatisch één concurrent bij."}
            </p>
            <p className="hint" style={{ margin: 0 }}>
              <strong>De controle zelf (handmatig):</strong>{" "}
              {weeklyPlan.manual_check_summary ||
                "Het bekijken en vergelijken van de cijfers doe je zelf op het geplande moment."}
            </p>
          </div>

          <div
            className="stack"
            style={{
              padding: "0.8rem",
              borderRadius: "8px",
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              gap: "0.35rem",
            }}
          >
            <strong>3. Wat doe je zelf?</strong>
            <ol style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
              {(weeklyPlan.user_steps || [
                "Controleer of bij elke concurrent recente berichten klaarstaan.",
                "Klik zo nodig op ‘Berichten van concurrenten ophalen’.",
                "Vergelijk hieronder bij Prestaties en Contentmix wat opvalt.",
              ]).map((step) => (
                <li key={step} style={{ marginBottom: "0.2rem" }}>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        </div>

        {weeklyOpen ? (
          <WeeklyPlanEditor
            plan={weeklyPlan}
            busy={busy === "weekly"}
            onSave={async (body) => {
              const targetClientId = client.id;
              setBusy("weekly");
              setError("");
              try {
                const updated = await api(`/api/clients/${targetClientId}/comparison/weekly-plan`, {
                  method: "PUT",
                  body,
                });
                if (applyPayloadForClient(targetClientId, updated)) {
                  setNotice("Wekelijkse controle en planning zijn opgeslagen.");
                  setWeeklyOpen(false);
                }
              } catch (exc) {
                setError(exc.message || "De wekelijkse planning kon niet worden opgeslagen.");
              } finally {
                setBusy("");
              }
            }}
          />
        ) : null}
      </section>

      {/* Periodekeuze & vergelijkingstabellen */}
      <section className="card stack" aria-label="Vergelijkingscijfers">
        <div
          className="row-actions wrap"
          style={{ justifyContent: "space-between", alignItems: "flex-end", gap: "1rem" }}
        >
          <div>
            <h3 style={{ margin: 0 }}>Prestaties vergelijken</h3>
            <p className="hint" style={{ margin: "0.2rem 0 0" }}>
              Vergelijk het eigen Instagram-account van <strong>{client.name}</strong> met de opgehaalde berichten van de ingestelde concurrenten.
            </p>
          </div>
          <div className="row-actions wrap" style={{ alignItems: "flex-end" }}>
            <label>
              Periode
              <select
                value={state.period_key}
                disabled={Boolean(busy)}
                onChange={(event) => changePeriod(event.target.value)}
              >
                {(state.period_presets || []).map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            {state.period_key === "custom" ? (
              <>
                <label>
                  Vanaf
                  <input
                    type="date"
                    value={customStart}
                    onChange={(e) => setCustomStart(e.target.value)}
                  />
                </label>
                <label>
                  Tot en met
                  <input
                    type="date"
                    value={customEnd}
                    onChange={(e) => setCustomEnd(e.target.value)}
                  />
                </label>
                <button
                  className="secondary"
                  type="button"
                  disabled={Boolean(busy)}
                  onClick={() => changePeriod("custom")}
                >
                  Periode toepassen
                </button>
              </>
            ) : null}
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Volgers</th>
                <th>Berichten in periode</th>
                <th>Gem. likes</th>
                <th>Gem. reacties</th>
              </tr>
            </thead>
            <tbody>
              {(state.account_rows || []).map((row) => (
                <tr key={`${row.role}-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                    {row.role === "own" ? (
                      <span className="hint" style={{ display: "block" }}>
                        Eigen account van {client.name}
                      </span>
                    ) : null}
                  </td>
                  <td>{row.has_fetched_data ? fmt(row.followers) : "Nog niet opgehaald"}</td>
                  <td>{row.has_fetched_data ? fmt(row.posts_in_period) : "Nog niet opgehaald"}</td>
                  <td>{row.has_fetched_data ? fmtAvg(row.likes_avg) : "—"}</td>
                  <td>{row.has_fetched_data ? fmtAvg(row.comments_avg) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Contentmix in gekozen periode</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Reels</th>
                <th>Afbeeldingen</th>
                <th>Carrousels</th>
                <th>Overige video’s</th>
              </tr>
            </thead>
            <tbody>
              {(state.content_rows || []).map((row) => (
                <tr key={`content-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                  </td>
                  <td>{row.has_fetched_data ? fmt(row.reels) : "Nog niet opgehaald"}</td>
                  <td>{row.has_fetched_data ? fmt(row.images) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.carousels) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.other_videos) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Volgersgroei</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Start van periode</th>
                <th>Eind van periode</th>
                <th>Verschil</th>
              </tr>
            </thead>
            <tbody>
              {(state.growth_rows || []).map((row) => (
                <tr key={`growth-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                  </td>
                  <td>{row.followers_start != null ? fmt(row.followers_start) : "—"}</td>
                  <td>{row.followers_end != null ? fmt(row.followers_end) : "—"}</td>
                  <td>
                    {row.followers_delta != null
                      ? fmt(row.followers_delta)
                      : row.missing_note || "Nog onvoldoende meetmomenten"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Punt 22: Bevestigingsdialoog bij verwijderen concurrent */}
      {pendingDelete ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-competitor-title"
          onClick={(e) => {
            if (e.target === e.currentTarget && !busy) setPendingDelete(null);
          }}
        >
          <div className="modal-card stack">
            <h3 id="delete-competitor-title" style={{ marginTop: 0 }}>
              Concurrent verwijderen
            </h3>
            <p style={{ margin: 0 }}>
              Weet je zeker dat je <strong>@{pendingDelete}</strong> wilt verwijderen uit de concurrenten van{" "}
              <strong>{client.name}</strong>?
            </p>
            <p className="hint" style={{ margin: 0 }}>
              Dit account wordt daarna niet meer meegenomen bij het ophalen en vergelijken van berichten.
            </p>
            <div className="row-actions wrap" style={{ justifyContent: "flex-end" }}>
              <button
                className="secondary"
                type="button"
                disabled={Boolean(busy)}
                onClick={() => setPendingDelete(null)}
              >
                Annuleren
              </button>
              <button
                className="primary"
                type="button"
                disabled={Boolean(busy)}
                onClick={confirmRemoveCompetitor}
              >
                {busy === `remove-${pendingDelete}`
                  ? "Verwijderen…"
                  : `Ja, @${pendingDelete} verwijderen`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function WeeklyPlanEditor({ plan, busy, onSave }) {
  const [enabled, setEnabled] = useState(Boolean(plan?.enabled));
  const [weekday, setWeekday] = useState(String(plan?.weekday ?? 0));
  const [time, setTime] = useState(plan?.time || "09:00");
  const [responsibleName, setResponsibleName] = useState(plan?.responsible_name || "");
  const [note, setNote] = useState(plan?.note || "");

  useEffect(() => {
    setEnabled(Boolean(plan?.enabled));
    setWeekday(String(plan?.weekday ?? 0));
    setTime(plan?.time || "09:00");
    setResponsibleName(plan?.responsible_name || "");
    setNote(plan?.note || "");
  }, [plan?.enabled, plan?.weekday, plan?.time, plan?.responsible_name, plan?.note]);

  return (
    <div
      className="stack"
      style={{
        padding: "0.85rem",
        borderRadius: "8px",
        background: "rgba(0, 0, 0, 0.22)",
        border: "1px solid rgba(255, 255, 255, 0.14)",
      }}
    >
      <label className="row-actions">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Vast wekelijks controlemoment inplannen
      </label>
      <div className="row-actions wrap">
        <label>
          Vaste dag
          <select value={weekday} onChange={(e) => setWeekday(e.target.value)}>
            {(plan?.weekday_options || []).map((opt) => (
              <option key={opt.value} value={String(opt.value)}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tijdstip
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </label>
        <label style={{ flex: "1 1 180px" }}>
          Verantwoordelijke (optioneel)
          <input
            value={responsibleName}
            onChange={(e) => setResponsibleName(e.target.value)}
            placeholder="bijv. Jet of Mo"
          />
        </label>
      </div>
      <label>
        Werkafspraak of aandachtspunt (optioneel)
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="bijv. Let op welke Reels bij concurrenten veel reacties krijgen"
        />
      </label>
      <div className="row-actions">
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() =>
            onSave({
              enabled,
              weekday: Number(weekday),
              time,
              responsible_name: responsibleName,
              note,
            })
          }
        >
          {busy ? "Opslaan…" : "Planning opslaan"}
        </button>
      </div>
    </div>
  );
}
