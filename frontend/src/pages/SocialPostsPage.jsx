import { useEffect, useState } from "react";
import { api } from "../api.js";
import PerformancePage from "./PerformancePage.jsx";
import PostsPage from "./PostsPage.jsx";

const TABS = [
  ["all_posts", "All posts"],
  ["performance", "Performance"],
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

/** Default Logs weekly-control window: last two calendar months. */
function twoMonthLogsWindow(now = new Date()) {
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const iso = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { from: iso(start), to: iso(end) };
}

export default function SocialPostsPage({
  client,
  initialTab = "all_posts",
  focusPostId,
  onClearFocus,
  onTabChange,
  onOpenPost,
  onSynced,
  periodSelection = "",
  onPeriodChange,
}) {
  const [tab, setTab] = useState(initialTab);
  const [period, setPeriod] = useState(periodSelection || "");
  const [skipPeriodFilter, setSkipPeriodFilter] = useState(false);
  const [logsWeekly, setLogsWeekly] = useState(null);
  const [weeklyDraft, setWeeklyDraft] = useState(null);
  const [weeklyBusy, setWeeklyBusy] = useState(false);
  const [weeklyError, setWeeklyError] = useState("");
  const [weeklyNotice, setWeeklyNotice] = useState("");

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
    setWeeklyError("");
    setWeeklyNotice("");
    api(`/api/clients/${client.id}/logs/weekly-plan`)
      .then((data) => {
        const plan = data.weekly_plan || null;
        setLogsWeekly(plan);
        setWeeklyDraft(
          plan
            ? {
                enabled: Boolean(plan.enabled),
                weekday: Number(plan.weekday ?? 0),
                time: plan.time || "09:00",
                note: plan.note || "",
              }
            : null,
        );
      })
      .catch((exc) => setWeeklyError(exc.message));
  }, [client.id]);

  function selectTab(next, { fromPost = false } = {}) {
    setTab(next);
    if (next === "all_posts") setSkipPeriodFilter(Boolean(fromPost));
    onTabChange?.(next);
  }

  function handlePeriodChange(next) {
    setPeriod(next || "");
    onPeriodChange?.(next || "");
  }

  async function saveLogsWeekly(event) {
    event?.preventDefault?.();
    if (!weeklyDraft) return;
    setWeeklyBusy(true);
    setWeeklyError("");
    setWeeklyNotice("");
    try {
      const data = await api(`/api/clients/${client.id}/logs/weekly-plan`, {
        method: "PUT",
        body: {
          enabled: Boolean(weeklyDraft.enabled),
          weekday: Number(weeklyDraft.weekday || 0),
          time: weeklyDraft.time || "09:00",
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
              note: plan.note || "",
            }
          : null,
      );
      setWeeklyNotice(
        plan?.enabled
          ? `Opgeslagen. Volgende check ${plan.next_check_date} · venster ${plan.window_from} t/m ${plan.window_to}.`
          : "Opgeslagen. Wekelijkse Logs-controle staat uit.",
      );
    } catch (exc) {
      setWeeklyError(exc.message);
    } finally {
      setWeeklyBusy(false);
    }
  }

  const bounds = monthBounds(period);
  const logsDefault = twoMonthLogsWindow();
  // Opening a top-post must not hide it behind the Performance month filter.
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

  const weeklyHint = logsWeekly?.enabled
    ? `Logs-weekcontrole (niet Competitors): volgende check ${logsWeekly.next_check_date} ${logsWeekly.weekday_label} ${logsWeekly.time}; venster ${logsWeekly.window_from} t/m ${logsWeekly.window_to}. Auto-run uit.`
    : `Logs-weekcontrole: standaard venster van twee maanden (${logsFrom} t/m ${logsTo}). Apart van Competitors. Zet hieronder een weekdag aan om de volgende controledatum te plannen.`;

  return (
    <div className="stack">
      <div className="subnav-tabs" role="tablist" aria-label="Social posts">
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
          <form className="card stack logs-weekly-card" style={{ gap: "0.75rem" }} onSubmit={saveLogsWeekly}>
            <div>
              <strong>Wekelijkse Logs-controle</strong>
              <p className="hint" style={{ margin: "0.25rem 0 0" }}>
                Los van Competitors. Alleen schema + datavenster; geen automatische AI-run. Wijzigingen
                worden pas bewaard als je op Opslaan klikt.
              </p>
            </div>
            {weeklyError ? <p className="banner error">{weeklyError}</p> : null}
            {weeklyNotice ? <p className="banner">{weeklyNotice}</p> : null}
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
              <span>Wekelijkse Logs-controle inschakelen</span>
            </label>
            <div className="logs-weekly-fields">
              <label>
                Dag
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
                Tijd
                <input
                  type="time"
                  value={weeklyDraft?.time || "09:00"}
                  disabled={weeklyBusy || !weeklyDraft}
                  onChange={(e) =>
                    setWeeklyDraft((cur) => (cur ? { ...cur, time: e.target.value } : cur))
                  }
                />
              </label>
              <label className="logs-weekly-note">
                Notitie
                <input
                  type="text"
                  value={weeklyDraft?.note || ""}
                  disabled={weeklyBusy || !weeklyDraft}
                  placeholder="bijv. beoordeling + insight bijwerken"
                  onChange={(e) =>
                    setWeeklyDraft((cur) => (cur ? { ...cur, note: e.target.value } : cur))
                  }
                />
              </label>
            </div>
            {logsWeekly?.enabled ? (
              <p className="hint" style={{ margin: 0 }}>
                Laatst opgeslagen: volgende check <strong>{logsWeekly.next_check_date}</strong> ·
                venster {logsWeekly.window_from} t/m {logsWeekly.window_to}
              </p>
            ) : null}
            <div className="row-actions wrap">
              <button className="primary" type="submit" disabled={weeklyBusy || !weeklyDraft}>
                {weeklyBusy ? "Opslaan…" : "Opslaan"}
              </button>
            </div>
          </form>
          <PostsPage
            key={`all-posts-${client.id}`}
            client={client}
            focusPostId={focusPostId}
            onClearFocus={onClearFocus}
            initialDateFrom={logsFrom}
            initialDateTo={logsTo}
            periodHint={
              applyPeriodFilter
                ? `Filters follow Performance month ${period} (changeable below).`
                : skipPeriodFilter && period
                  ? `Opened from Performance (${period}); date filters cleared so this post stays visible.`
                  : weeklyHint
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
          onOpenPost={(postId) => {
            selectTab("all_posts", { fromPost: true });
            onOpenPost?.(postId);
          }}
          onSynced={onSynced}
        />
      ) : null}
    </div>
  );
}
