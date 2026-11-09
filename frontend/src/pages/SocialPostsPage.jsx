import { useEffect, useState } from "react";
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

  function selectTab(next, { fromPost = false } = {}) {
    setTab(next);
    if (next === "all_posts") setSkipPeriodFilter(Boolean(fromPost));
    onTabChange?.(next);
  }

  function handlePeriodChange(next) {
    setPeriod(next || "");
    onPeriodChange?.(next || "");
  }

  const bounds = monthBounds(period);
  // Opening a top-post must not hide it behind the Performance month filter.
  const applyPeriodFilter = Boolean(period) && !skipPeriodFilter;

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
        <PostsPage
          key={`all-posts-${client.id}`}
          client={client}
          focusPostId={focusPostId}
          onClearFocus={onClearFocus}
          initialDateFrom={applyPeriodFilter ? bounds.from : ""}
          initialDateTo={applyPeriodFilter ? bounds.to : ""}
          periodHint={
            applyPeriodFilter
              ? `Filters follow Performance month ${period} (changeable below).`
              : skipPeriodFilter && period
                ? `Opened from Performance (${period}); date filters cleared so this post stays visible.`
                : ""
          }
          showImportExportButton
        />
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
