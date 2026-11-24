import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import PerformancePage from "./PerformancePage.jsx";
import PostsPage from "./PostsPage.jsx";

const TABS = [
  ["all_posts", "Alle berichten"],
  ["performance", "Resultaten"],
];

function monthBounds(yyyyMm) {
  if (!yyyyMm || !/^\d{4}-\d{2}$/.test(yyyyMm)) return { from: "", to: "" };
  const [y, m] = yyyyMm.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return {
    from: `${yyyyMm}-01`,
    to: `${yyyyMm}-${String(last).padStart(2, "0")}`,
  };
}

/** Default weekly-control window: last two calendar months. */
function twoMonthLogsWindow(now = new Date()) {
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const iso = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { from: iso(start), to: iso(end) };
}

function formatIsoDateNl(iso) {
  if (!iso || typeof iso !== "string") return "—";
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return iso;
  const months = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
  ];
  const day = Number(match[3]);
  const monthName = months[Number(match[2]) - 1] || match[2];
  return `${day} ${monthName} ${match[1]}`;
}

export default function SocialPostsPage({
  client,
  initialTab = "all_posts",
  focusPostId,
  onClearFocus,
  onTabChange,
  onOpenPost,
  onOpenConnect,
  onOpenCompetitors,
  onSynced,
  periodSelection = "",
  onPeriodChange,
}) {
  const [tab, setTab] = useState(initialTab);
  const [period, setPeriod] = useState(periodSelection || "");
  const [skipPeriodFilter, setSkipPeriodFilter] = useState(false);
  const [channelStatus, setChannelStatus] = useState(null);
  const [fetchingTop, setFetchingTop] = useState(false);
  const [topNotice, setTopNotice] = useState("");
  const [topError, setTopError] = useState("");
  const [topAdminDetail, setTopAdminDetail] = useState("");
  const [postsReloadToken, setPostsReloadToken] = useState(0);
  const [missingFilterSignal, setMissingFilterSignal] = useState(0);
  const [internalFocus, setInternalFocus] = useState({ id: null, seq: 0 });

  const [logsWeekly, setLogsWeekly] = useState(null);
  const [weeklyDraft, setWeeklyDraft] = useState(null);
  const [weeklySettingsOpen, setWeeklySettingsOpen] = useState(false);
  const [weeklyBusy, setWeeklyBusy] = useState(false);
  const [completingWeekly, setCompletingWeekly] = useState(false);
  const [weeklyError, setWeeklyError] = useState("");
  const [weeklyNotice, setWeeklyNotice] = useState("");

  const loadChannelAndWeekly = useCallback(async (targetClientId, guard = () => true) => {
    const [totalsRes, weeklyRes] = await Promise.all([
      api(`/api/clients/${targetClientId}/sync-totals`),
      api(`/api/clients/${targetClientId}/logs/weekly-plan`),
    ]);
    if (!guard()) return;
    if (totalsRes?.client_id != null && Number(totalsRes.client_id) !== Number(targetClientId)) {
      return;
    }
    setChannelStatus(totalsRes?.channel_status || null);
    const plan = weeklyRes?.weekly_plan || null;
    setLogsWeekly(plan);
    setWeeklyDraft(
      plan
        ? {
            enabled: Boolean(plan.enabled),
            weekday: Number(plan.weekday ?? 0),
            time: plan.time || "09:00",
            responsible_name: plan.responsible_name || "",
            note: plan.note || "",
          }
        : null,
    );
  }, []);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab, client?.id]);

  useEffect(() => {
    setSkipPeriodFilter(false);
    setPeriod(periodSelection || "");
  }, [client?.id]);

  useEffect(() => {
    setPeriod(periodSelection || "");
  }, [periodSelection]);

  useEffect(() => {
    let active = true;
    const targetId = client.id;
    setChannelStatus(null);
    setLogsWeekly(null);
    setWeeklyDraft(null);
    setTopNotice("");
    setTopError("");
    setTopAdminDetail("");
    setWeeklyError("");
    setWeeklyNotice("");
    setWeeklySettingsOpen(false);

    loadChannelAndWeekly(targetId, () => active).catch((exc) => {
      if (!active) return;
      setTopError("De status van deze klant kon niet worden geladen.");
      setTopAdminDetail(exc.message || "");
    });
    return () => {
      active = false;
    };
  }, [client.id, loadChannelAndWeekly]);

  function selectTab(next, { fromPost = false } = {}) {
    setTab(next);
    if (next === "all_posts") setSkipPeriodFilter(Boolean(fromPost));
    onTabChange?.(next);
  }

  function handlePeriodChange(next) {
    setPeriod(next || "");
    onPeriodChange?.(next || "");
  }

  async function runPrimaryFetch() {
    if (fetchingTop) return;
    const targetId = client.id;
    setFetchingTop(true);
    setTopNotice("");
    setTopError("");
    setTopAdminDetail("");
    try {
      const payload = await api(`/api/clients/${targetId}/posts/fetch`, { method: "POST", body: {} });
      if (payload?.client_id != null && Number(payload.client_id) !== Number(targetId)) return;
      if (payload?.channel_status) {
        setChannelStatus(payload.channel_status);
      }
      const fetchedCount = Array.isArray(payload?.posts) ? payload.posts.length : 0;
      setTopNotice(
        fetchedCount > 0
          ? `Gelukt! Er staan nu ${fetchedCount} berichten klaar om te bekijken.`
          : "Het ophalen is gelukt, maar er zijn nog geen berichten gevonden op de gekoppelde accounts.",
      );
      setPostsReloadToken((n) => n + 1);
      await loadChannelAndWeekly(targetId);
      await onSynced?.();
    } catch (exc) {
      setTopError(
        "Het ophalen van berichten bij Facebook en Instagram is nu niet gelukt. Controleer of de koppeling nog geldig is.",
      );
      setTopAdminDetail(exc.message || "");
      await loadChannelAndWeekly(targetId).catch(() => {});
    } finally {
      setFetchingTop(false);
    }
  }

  async function saveLogsWeekly(event) {
    event?.preventDefault?.();
    if (!weeklyDraft) return;
    const targetId = client.id;
    setWeeklyBusy(true);
    setWeeklyError("");
    setWeeklyNotice("");
    try {
      const data = await api(`/api/clients/${targetId}/logs/weekly-plan`, {
        method: "PUT",
        body: {
          enabled: Boolean(weeklyDraft.enabled),
          weekday: Number(weeklyDraft.weekday || 0),
          time: weeklyDraft.time || "09:00",
          responsible_name: weeklyDraft.responsible_name || "",
          note: weeklyDraft.note || "",
        },
      });
      const plan = data.weekly_plan || null;
      setLogsWeekly(plan);
      setWeeklyDraft(
        plan
          ? {
              enabled: Boolean(plan.enabled),
              weekday: Number(plan.weekday ?? 0),
              time: plan.time || "09:00",
              responsible_name: plan.responsible_name || "",
              note: plan.note || "",
            }
          : null,
      );
      setWeeklyNotice(
        plan?.enabled
          ? `Planning opgeslagen. Volgende controle staat op ${plan.weekday_label} (${formatIsoDateNl(plan.next_check_date)}) om ${plan.time}.`
          : "Instellingen voor de wekelijkse controle zijn opgeslagen.",
      );
      setWeeklySettingsOpen(false);
    } catch (exc) {
      setWeeklyError("Het opslaan van de wekelijkse controle is niet gelukt.");
      setTopAdminDetail(exc.message || "");
    } finally {
      setWeeklyBusy(false);
    }
  }

  async function handleCompleteWeeklyCheck() {
    if (completingWeekly) return;
    const targetId = client.id;
    setCompletingWeekly(true);
    setWeeklyError("");
    setWeeklyNotice("");
    try {
      const data = await api(`/api/clients/${targetId}/logs/weekly-plan/complete`, {
        method: "POST",
        body: {
          completed_by: weeklyDraft?.responsible_name || logsWeekly?.responsible_name || "",
        },
      });
      const plan = data.weekly_plan || null;
      setLogsWeekly(plan);
      if (plan) {
        setWeeklyDraft((cur) =>
          cur
            ? {
                ...cur,
                responsible_name: plan.responsible_name || cur.responsible_name || "",
              }
            : null,
        );
      }
      const who = plan?.last_completed_by ? ` door ${plan.last_completed_by}` : "";
      setWeeklyNotice(`Wekelijkse controle afgerond${who}. Goed bezig!`);
    } catch (exc) {
      setWeeklyError("De wekelijkse controle kon niet worden afgerond.");
      setTopAdminDetail(exc.message || "");
    } finally {
      setCompletingWeekly(false);
    }
  }

  const bounds = monthBounds(period);
  const logsDefault = twoMonthLogsWindow();
  const applyPeriodFilter = Boolean(period) && !skipPeriodFilter;
  const logsFrom = applyPeriodFilter
    ? bounds.from
    : skipPeriodFilter
      ? ""
      : logsWeekly?.window_from || logsDefault.from;
  const logsTo = applyPeriodFilter
    ? bounds.to
    : skipPeriodFilter
      ? ""
      : logsWeekly?.window_to || logsDefault.to;

  const statusTone =
    channelStatus?.state === "ready_to_view"
      ? "rgba(16, 185, 129, 0.14)"
      : channelStatus?.state === "fetch_first_posts"
        ? "rgba(59, 130, 246, 0.16)"
        : "rgba(245, 158, 11, 0.16)";
  const statusBorder =
    channelStatus?.state === "ready_to_view"
      ? "rgba(52, 211, 153, 0.45)"
      : channelStatus?.state === "fetch_first_posts"
        ? "rgba(96, 165, 250, 0.45)"
        : "rgba(251, 191, 36, 0.45)";

  const uncheckedCount = Number(logsWeekly?.unchecked_in_window_count ?? 0);
  const windowTotal = Number(logsWeekly?.posts_in_window_count ?? 0);
  const checkedCount = Number(logsWeekly?.checked_in_window_count ?? 0);
  const uncheckedPosts = logsWeekly?.unchecked_posts || [];
  const adminDetailsCombined = topAdminDetail || channelStatus?.admin_error_detail || "";

  return (
    <div className="stack">
      {/* Bovenste kaart: status per kanaal + belangrijkste actie bovenaan (punt 16 & 17) */}
      <section
        className="card stack"
        aria-label="Koppeling en ophaalstatus"
        style={{
          background: channelStatus ? statusTone : undefined,
          borderColor: channelStatus ? statusBorder : undefined,
          gap: "0.85rem",
        }}
      >
        {!channelStatus ? (
          <p className="muted" style={{ margin: 0 }}>
            Status voor {client.name} laden…
          </p>
        ) : (
          <>
            <div
              className="row-actions wrap"
              style={{ justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}
            >
              <div className="stack" style={{ gap: "0.3rem", maxWidth: "44rem" }}>
                <strong style={{ fontSize: "1.12rem" }}>{channelStatus.headline}</strong>
                <p style={{ margin: 0 }}>{channelStatus.next_action}</p>
              </div>
              <div className="row-actions wrap">
                {channelStatus.action_key === "connect_accounts" ? (
                  <button
                    className="primary"
                    type="button"
                    onClick={() => onOpenConnect?.()}
                  >
                    {channelStatus.action_label || "Accounts koppelen"}
                  </button>
                ) : (
                  <button
                    className="primary"
                    type="button"
                    disabled={fetchingTop}
                    onClick={runPrimaryFetch}
                  >
                    {fetchingTop
                      ? "Berichten ophalen…"
                      : channelStatus.action_label || "Berichten ophalen"}
                  </button>
                )}
                {channelStatus.connected ? (
                  <button className="secondary" type="button" onClick={() => onOpenConnect?.()}>
                    Koppeling bekijken
                  </button>
                ) : null}
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(13.5rem, 1fr))",
                gap: "0.65rem",
              }}
            >
              <div
                style={{
                  background: "rgba(16, 28, 44, 0.65)",
                  border: "1px solid rgba(242, 240, 236, 0.14)",
                  borderRadius: "0.5rem",
                  padding: "0.65rem 0.8rem",
                }}
              >
                <div className="hint" style={{ margin: 0 }}>
                  Facebook
                </div>
                <strong>{channelStatus.facebook?.label || "Niet gekoppeld"}</strong>
              </div>
              <div
                style={{
                  background: "rgba(16, 28, 44, 0.65)",
                  border: "1px solid rgba(242, 240, 236, 0.14)",
                  borderRadius: "0.5rem",
                  padding: "0.65rem 0.8rem",
                }}
              >
                <div className="hint" style={{ margin: 0 }}>
                  Instagram
                </div>
                <strong>{channelStatus.instagram?.label || "Niet gekoppeld"}</strong>
              </div>
              <div
                style={{
                  background: "rgba(16, 28, 44, 0.65)",
                  border: "1px solid rgba(242, 240, 236, 0.14)",
                  borderRadius: "0.5rem",
                  padding: "0.65rem 0.8rem",
                }}
              >
                <div className="hint" style={{ margin: 0 }}>
                  Berichten laatst opgehaald
                </div>
                <strong>{channelStatus.last_fetched_label || "Nog nooit opgehaald"}</strong>
              </div>
            </div>
          </>
        )}

        {topNotice ? <p className="banner" style={{ margin: 0 }}>{topNotice}</p> : null}
        {topError ? <p className="banner error" style={{ margin: 0 }}>{topError}</p> : null}
        {adminDetailsCombined ? (
          <details>
            <summary className="hint" style={{ cursor: "pointer" }}>
              Technische foutdetails (alleen voor beheer)
            </summary>
            <pre
              className="hint"
              style={{
                marginTop: "0.4rem",
                padding: "0.6rem",
                background: "rgba(16, 28, 44, 0.7)",
                border: "1px solid rgba(242, 240, 236, 0.14)",
                borderRadius: "0.4rem",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {adminDetailsCombined}
            </pre>
          </details>
        ) : null}
      </section>

      {/* Subnavigatie: Alle berichten & Resultaten */}
      <div className="subnav-tabs" role="tablist" aria-label="Socialmediaberichten">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "subnav-tab is-active" : "subnav-tab"}
            onClick={() => selectTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "all_posts" ? (
        <>
          {/* Wekelijkse controle (punt 19) */}
          <section className="card stack logs-weekly-card" style={{ gap: "0.85rem" }}>
            <div
              className="row-actions wrap"
              style={{ justifyContent: "space-between", alignItems: "flex-start" }}
            >
              <div className="stack" style={{ gap: "0.25rem" }}>
                <div className="row-actions wrap" style={{ gap: "0.5rem", alignItems: "center" }}>
                  <strong style={{ fontSize: "1.05rem" }}>Wekelijkse controle</strong>
                  {logsWeekly?.has_responsible ? (
                    <span className="badge badge-active">
                      Verantwoordelijke: {logsWeekly.responsible_name}
                    </span>
                  ) : null}
                  {logsWeekly?.enabled ? (
                    <span className="badge">
                      Elke {logsWeekly.weekday_label} om {logsWeekly.time}
                    </span>
                  ) : null}
                </div>
                <p className="hint" style={{ margin: 0 }}>
                  Controleperiode: {formatIsoDateNl(logsFrom || logsWeekly?.window_from)} t/m{" "}
                  {formatIsoDateNl(logsTo || logsWeekly?.window_to)} (eigen berichten van {client.name}).
                  {logsWeekly?.last_completed_label ? (
                    <>
                      {" "}
                      · Laatst afgerond: <strong>{logsWeekly.last_completed_label}</strong>
                      {logsWeekly.last_completed_by ? ` door ${logsWeekly.last_completed_by}` : ""}
                    </>
                  ) : null}
                </p>
              </div>
              <div className="row-actions wrap">
                <button
                  className="primary"
                  type="button"
                  disabled={completingWeekly || !logsWeekly}
                  onClick={handleCompleteWeeklyCheck}
                >
                  {completingWeekly ? "Bezig met afronden…" : "Wekelijkse controle afronden"}
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => setWeeklySettingsOpen((open) => !open)}
                >
                  {weeklySettingsOpen ? "Instellingen sluiten" : "Planning & verantwoordelijke"}
                </button>
              </div>
            </div>

            {weeklyError ? <p className="banner error" style={{ margin: 0 }}>{weeklyError}</p> : null}
            {weeklyNotice ? <p className="banner" style={{ margin: 0 }}>{weeklyNotice}</p> : null}

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(16rem, 1fr))",
                gap: "0.75rem",
              }}
            >
              {/* 1. Welke berichten moeten nog gecontroleerd worden */}
              <div
                className="stack"
                style={{
                  gap: "0.45rem",
                  padding: "0.75rem",
                  borderRadius: "0.5rem",
                  background: "rgba(16, 28, 44, 0.55)",
                  border: "1px solid rgba(242, 240, 236, 0.12)",
                }}
              >
                <strong>1. Welke berichten moet je nog nakijken?</strong>
                {windowTotal === 0 ? (
                  <p className="hint" style={{ margin: 0 }}>
                    Er staan nog geen berichten van {client.name} in deze controleperiode.
                  </p>
                ) : uncheckedCount === 0 ? (
                  <p style={{ margin: 0 }}>
                    Alle <strong>{windowTotal}</strong> berichten in deze periode zijn nagekeken.
                  </p>
                ) : (
                  <>
                    <p style={{ margin: 0 }}>
                      Nog <strong>{uncheckedCount}</strong> van {windowTotal} berichten na te kijken ({checkedCount}{" "}
                      al klaar).
                    </p>
                    <ul className="plain-list" style={{ margin: 0 }}>
                      {uncheckedPosts.slice(0, 5).map((item) => (
                        <li
                          key={item.id}
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: "0.5rem",
                            padding: "0.3rem 0",
                            borderBottom: "1px solid rgba(242, 240, 236, 0.1)",
                          }}
                        >
                          <span style={{ fontSize: "0.9rem" }}>
                            <strong>{item.platform_label}</strong> · {item.caption_preview}{" "}
                            <span className="hint">
                              (mist: {(item.missing_labels || []).join(", ")})
                            </span>
                          </span>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => {
                              selectTab("all_posts", { fromPost: false });
                              setInternalFocus((cur) => ({ id: item.id, seq: cur.seq + 1 }));
                              onOpenPost?.(item.id);
                            }}
                          >
                            Openen
                          </button>
                        </li>
                      ))}
                    </ul>
                    {uncheckedCount > 5 ? (
                      <p className="hint" style={{ margin: 0 }}>
                        En nog {uncheckedCount - 5} bericht(en) eronder.
                      </p>
                    ) : null}
                    <div>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setMissingFilterSignal((n) => n + 1)}
                      >
                        Toon alleen nog na te kijken berichten
                      </button>
                    </div>
                  </>
                )}
              </div>

              {/* 2. Wat moet je per bericht nakijken */}
              <div
                className="stack"
                style={{
                  gap: "0.45rem",
                  padding: "0.75rem",
                  borderRadius: "0.5rem",
                  background: "rgba(16, 28, 44, 0.55)",
                  border: "1px solid rgba(242, 240, 236, 0.12)",
                }}
              >
                <strong>2. Wat kijk je per bericht na?</strong>
                <ol style={{ margin: "0 0 0 1.15rem", padding: 0, display: "grid", gap: "0.25rem" }}>
                  {(
                    logsWeekly?.checklist_items || [
                      "Kies het juiste contentformat uit de legenda.",
                      "Kies de juiste contentpijler uit de legenda.",
                      "Vul de hook in (de openingszin of het haakje van het bericht).",
                      "Controleer of cijfers en een eventuele Figma-link kloppen en klik op Indeling opslaan.",
                    ]
                  ).map((step) => (
                    <li key={step} style={{ fontSize: "0.92rem" }}>
                      {step}
                    </li>
                  ))}
                </ol>
              </div>

              {/* 3. Hoe rond je een controle af */}
              <div
                className="stack"
                style={{
                  gap: "0.45rem",
                  padding: "0.75rem",
                  borderRadius: "0.5rem",
                  background: "rgba(16, 28, 44, 0.55)",
                  border: "1px solid rgba(242, 240, 236, 0.12)",
                }}
              >
                <strong>3. Hoe rond je de controle af?</strong>
                <p style={{ margin: 0, fontSize: "0.92rem" }}>
                  Open elk openstaand bericht via <strong>Bericht nakijken</strong>, vul de ontbrekende
                  velden in en klik op <strong>Indeling opslaan</strong>. Zijn alle berichten bijgewerkt?
                  Klik rechtsboven op <strong>Wekelijkse controle afronden</strong>.
                </p>
                {logsWeekly?.note ? (
                  <p className="hint" style={{ margin: 0 }}>
                    <strong>Werkafspraak:</strong> {logsWeekly.note}
                  </p>
                ) : null}
                {logsWeekly?.enabled ? (
                  <p className="hint" style={{ margin: 0 }}>
                    Volgende geplande controle:{" "}
                    <strong>{formatIsoDateNl(logsWeekly.next_check_date)}</strong> ({logsWeekly.weekday_label}{" "}
                    {logsWeekly.time}).
                  </p>
                ) : null}
              </div>
            </div>

            {weeklySettingsOpen ? (
              <form
                className="stack"
                style={{
                  gap: "0.75rem",
                  paddingTop: "0.75rem",
                  borderTop: "1px solid rgba(242, 240, 236, 0.14)",
                }}
                onSubmit={saveLogsWeekly}
              >
                <strong>Planning &amp; verantwoordelijke instellen</strong>
                <label className="logs-weekly-switch">
                  <input
                    type="checkbox"
                    role="switch"
                    checked={Boolean(weeklyDraft?.enabled)}
                    disabled={weeklyBusy || !weeklyDraft}
                    onChange={(e) =>
                      setWeeklyDraft((cur) => (cur ? { ...cur, enabled: e.target.checked } : cur))
                    }
                  />
                  <span>Vaste wekelijkse controledag inplannen</span>
                </label>
                <div className="logs-weekly-fields">
                  <label>
                    Controledag
                    <select
                      value={String(weeklyDraft?.weekday ?? 0)}
                      disabled={weeklyBusy || !weeklyDraft}
                      onChange={(e) =>
                        setWeeklyDraft((cur) =>
                          cur ? { ...cur, weekday: Number(e.target.value) } : cur,
                        )
                      }
                    >
                      {(logsWeekly?.weekday_options || []).map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Tijdstip
                    <input
                      type="time"
                      value={weeklyDraft?.time || "09:00"}
                      disabled={weeklyBusy || !weeklyDraft}
                      onChange={(e) =>
                        setWeeklyDraft((cur) => (cur ? { ...cur, time: e.target.value } : cur))
                      }
                    />
                  </label>
                  <label>
                    Verantwoordelijke (optioneel, bijv. Jet of Mo)
                    <input
                      type="text"
                      value={weeklyDraft?.responsible_name || ""}
                      disabled={weeklyBusy || !weeklyDraft}
                      placeholder="bijv. Jet"
                      onChange={(e) =>
                        setWeeklyDraft((cur) =>
                          cur ? { ...cur, responsible_name: e.target.value } : cur,
                        )
                      }
                    />
                  </label>
                  <label className="logs-weekly-note">
                    Korte werkafspraak (optioneel)
                    <input
                      type="text"
                      value={weeklyDraft?.note || ""}
                      disabled={weeklyBusy || !weeklyDraft}
                      placeholder="bijv. ook nieuwe Reels van deze week voorzien van hook"
                      onChange={(e) =>
                        setWeeklyDraft((cur) => (cur ? { ...cur, note: e.target.value } : cur))
                      }
                    />
                  </label>
                </div>
                <div className="row-actions wrap">
                  <button className="primary" type="submit" disabled={weeklyBusy || !weeklyDraft}>
                    {weeklyBusy ? "Opslaan…" : "Planning opslaan"}
                  </button>
                </div>
              </form>
            ) : null}
          </section>

          <PostsPage
            key={`all-posts-${client.id}`}
            client={client}
            focusPostId={internalFocus.id ?? focusPostId}
            focusSeq={internalFocus.seq}
            onClearFocus={onClearFocus}
            initialDateFrom={logsFrom}
            initialDateTo={logsTo}
            reloadToken={postsReloadToken}
            missingFilterSignal={missingFilterSignal}
            onOpenConnect={onOpenConnect}
            onPostsChanged={() => loadChannelAndWeekly(client.id)}
            periodHint={
              applyPeriodFilter
                ? `Datumfilter volgt de gekozen maand uit Resultaten (${period}). Je kunt dit hieronder aanpassen.`
                : skipPeriodFilter && period
                  ? `Geopend vanuit Resultaten (${period}); het datumfilter is gewist zodat dit bericht zichtbaar blijft.`
                  : ""
            }
            showImportExportButton
          />
        </>
      ) : null}

      {tab === "performance" ? (
        <PerformancePage
          key={`perf-${client.id}`}
          client={client}
          selection={period}
          onSelectionChange={handlePeriodChange}
          onOpenCompetitors={onOpenCompetitors}
          onOpenConnect={onOpenConnect}
          onOpenPost={(postId) => {
            selectTab("all_posts", { fromPost: true });
            onOpenPost?.(postId);
          }}
          onSynced={async () => {
            await loadChannelAndWeekly(client.id);
            await onSynced?.();
          }}
        />
      ) : null}
    </div>
  );
}
