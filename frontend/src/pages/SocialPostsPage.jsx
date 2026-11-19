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
  const [weeklyBusy, setWeeklyBusy] = useState(false);
  const [weeklyError, setWeeklyError] = useState("");

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
    api(`/api/clients/${client.id}/logs/weekly-plan`)
      .then((data) => setLogsWeekly(data.weekly_plan || null))
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

  async function saveLogsWeekly(patch) {
    setWeeklyBusy(true);
    setWeeklyError("");
    try {
      const next = { ...(logsWeekly || {}), ...patch };
      const data = await api(`/api/clients/${client.id}/logs/weekly-plan`, {
        method: "PUT",
        body: {
          enabled: Boolean(next.enabled),
          weekday: Number(next.weekday || 0),
          time: next.time || "09:00",
          note: next.note || "",
        },
      });
      setLogsWeekly(data.weekly_plan || null);
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
          <div className="card stack" style={{ gap: "0.6rem" }}>
            <strong>Wekelijkse Logs-controle</strong>
            <p className="hint" style={{ margin: 0 }}>
              Los van Competitors. Alleen schema + datavenster; geen automatische AI-run.
            </p>
            {weeklyError ? <p className="banner error">{weeklyError}</p> : null}
            <div className="filters" style={{ alignItems: "end" }}>
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(logsWeekly?.enabled)}
                  disabled={weeklyBusy || !logsWeekly}
                  onChange={(e) => saveLogsWeekly({ enabled: e.target.checked })}
                />{" "}
                Actief
              </label>
              <label>
                Dag
                <select
                  value={String(logsWeekly?.weekday ?? 0)}
                  disabled={weeklyBusy || !logsWeekly}
                  onChange={(e) => saveLogsWeekly({ weekday: Number(e.target.value) })}
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
                  value={logsWeekly?.time || "09:00"}
                  disabled={weeklyBusy || !logsWeekly}
                  onChange={(e) => saveLogsWeekly({ time: e.target.value })}
                />
              </label>
              <label>
                Notitie
                <input
                  type="text"
                  value={logsWeekly?.note || ""}
                  disabled={weeklyBusy || !logsWeekly}
                  placeholder="bijv. beoordeling + insight bijwerken"
                  onBlur={(e) => {
                    if ((logsWeekly?.note || "") !== e.target.value) {
                      saveLogsWeekly({ note: e.target.value });
                    }
                  }}
                  onChange={(e) =>
                    setLogsWeekly((cur) => (cur ? { ...cur, note: e.target.value } : cur))
                  }
                />
              </label>
            </div>
            {logsWeekly?.enabled ? (
              <p className="hint" style={{ margin: 0 }}>
                Volgende check: <strong>{logsWeekly.next_check_date}</strong> · venster{" "}
                {logsWeekly.window_from} t/m {logsWeekly.window_to}
              </p>
            ) : null}
          </div>
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
