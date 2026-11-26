import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { BarChart, LineChart, StatStrip } from "../components/SimpleCharts.jsx";
import {
  formatCount,
  formatMonthShort,
  monthBounds,
  monthKey,
  numericMetric,
  postInteractions,
  postIso,
  postPlatform,
  weekBuckets,
} from "../postMetrics.js";

export default function StartPage({ client, onOpenPosts }) {
  const [posts, setPosts] = useState(null);
  const [error, setError] = useState("");
  const [month, setMonth] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPosts(null);
    setError("");
    api(`/api/clients/${client.id}/posts`)
      .then((payload) => {
        if (cancelled) return;
        const rows = payload?.posts || [];
        setPosts(rows);
        const months = [...new Set(rows.map((post) => monthKey(postIso(post))).filter(Boolean))].sort();
        setMonth(months.at(-1) || "");
      })
      .catch(() => {
        if (!cancelled) setError("De cijfers konden niet worden geladen.");
      });
    return () => {
      cancelled = true;
    };
  }, [client.id]);

  const months = useMemo(() => {
    if (!posts) return [];
    return [...new Set(posts.map((post) => monthKey(postIso(post))).filter(Boolean))].sort();
  }, [posts]);

  const bounds = monthBounds(month);
  const inPeriod = (posts || []).filter((post) => {
    const iso = postIso(post);
    return iso && bounds.from && iso >= bounds.from && iso <= bounds.to;
  });

  const reachValues = inPeriod.map((post) => numericMetric(post, "reach")).filter((value) => value != null);
  const interactionValues = inPeriod.map(postInteractions).filter((value) => value != null);
  const interactionSum = interactionValues.reduce((sum, value) => sum + value, 0);
  const channels = [...new Set(inPeriod.map(postPlatform).filter(Boolean))];
  const weeks = weekBuckets(inPeriod, bounds.from, bounds.to);

  function openChannel(row) {
    onOpenPosts?.({ platform: row.label, from: bounds.from, to: bounds.to, q: "" });
  }

  function openWeek(point) {
    onOpenPosts?.({ platform: "", from: point.from, to: point.to, q: "" });
  }

  return (
    <div className="stack">
      {error ? <p className="banner error">{error}</p> : null}
      {!posts && !error ? <p className="muted">Cijfers van {client.name} laden…</p> : null}
      {posts ? (
        <>
          <div className="filter-chips" aria-label="Periode">
            {months.length ? (
              months.slice(-4).map((key) => (
                <button
                  key={key}
                  type="button"
                  className={key === month ? "chip is-on" : "chip"}
                  onClick={() => setMonth(key)}
                >
                  {formatMonthShort(key)}
                </button>
              ))
            ) : (
              <span className="hint">Nog geen posts voor {client.name}.</span>
            )}
          </div>
          <StatStrip
            items={[
              { label: "Posts", value: formatCount(inPeriod.length) },
              { label: "Bereik", value: reachValues.length ? formatCount(reachValues.reduce((a, b) => a + b, 0)) : "–" },
              { label: "Interacties", value: interactionValues.length ? formatCount(interactionSum) : "–" },
              {
                label: "Gemiddelde interacties per post",
                value: interactionValues.length ? formatCount(interactionSum / interactionValues.length) : "–",
              },
            ]}
          />
          <div className="chart-grid">
            <LineChart
              title="Bereik per week"
              points={weeks.map((week) => ({ ...week, value: week.reach }))}
              onPick={openWeek}
            />
            <BarChart
              title="Bereik per kanaal"
              hint="Klik een kanaal om die posts te openen."
              rows={channels.map((label) => {
                const rows = inPeriod.filter((post) => postPlatform(post) === label);
                const known = rows.map((post) => numericMetric(post, "reach")).filter((value) => value != null);
                return { label, value: known.length ? known.reduce((a, b) => a + b, 0) : null };
              })}
              onPick={openChannel}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}
