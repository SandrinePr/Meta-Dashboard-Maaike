function fmtNum(value) {
  if (value == null || value === "") return "—";
  return typeof value === "number" ? value.toLocaleString("en-US") : String(value);
}

function DeltaCell({ delta }) {
  if (!delta) return <span className="hint">—</span>;
  const abs = delta.absolute;
  const label = delta.direction_label || "—";
  let pctText = "no %";
  if (delta.pct_available && delta.pct != null) {
    pctText = `${delta.pct > 0 ? "+" : ""}${delta.pct}%`;
  } else if (delta.pct_note) {
    pctText = delta.pct_note;
  }
  return (
    <span>
      {abs == null ? "—" : `${abs > 0 ? "+" : ""}${fmtNum(abs)}`} · {label}
      <br />
      <span className="hint">{pctText}</span>
    </span>
  );
}

function MetricTotalsTable({ metrics, title }) {
  if (!metrics) return null;
  const totals = metrics.totals || {};
  const averages = metrics.averages || {};
  const available = metrics.available_counts || {};
  const missing = metrics.missing_counts || {};
  const keys = ["reach", "views", "likes", "comments", "shares", "saves", "clicks"];
  return (
    <div className="stack">
      <h4>{title}</h4>
      <p className="hint">
        Posts: {fmtNum(metrics.post_count)} · totals and averages are separate · missing
        values do not count as 0
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Total (known)</th>
              <th>Average (known)</th>
              <th>Known</th>
              <th>Missing</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const tot = totals[key];
              const sum = tot && typeof tot === "object" ? tot.sum : tot;
              const avg =
                averages[key] != null
                  ? averages[key]
                  : tot && typeof tot === "object"
                    ? tot.average_over_known
                    : null;
              const known =
                available[key] != null
                  ? available[key]
                  : tot && typeof tot === "object"
                    ? tot.known_count
                    : null;
              const miss =
                missing[key] != null
                  ? missing[key]
                  : tot && typeof tot === "object"
                    ? tot.missing_count
                    : null;
              return (
                <tr key={key}>
                  <td>{key}</td>
                  <td>{fmtNum(sum)}</td>
                  <td>{fmtNum(avg)}</td>
                  <td>{fmtNum(known)}</td>
                  <td>{fmtNum(miss)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GroupTable({ title, groups, compareRows, unclassified }) {
  return (
    <div className="stack">
      <h4>{title}</h4>
      {unclassified?.count ? (
        <p className="banner error">
          Not yet classified: {unclassified.count} post(s)
          {unclassified.posts?.length ? (
            <span className="hint">
              {" "}
              — e.g. #
              {unclassified.posts
                .slice(0, 5)
                .map((p) => p.post_id)
                .join(", #")}
            </span>
          ) : null}
        </p>
      ) : (
        <p className="hint">All posts in this group are classified.</p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Posts</th>
              <th>Total reach</th>
              <th>Avg. reach</th>
              <th>Reach known / missing</th>
              <th>vs previous (reach sum)</th>
            </tr>
          </thead>
          <tbody>
            {(groups || []).map((g) => {
              const cmp = (compareRows || []).find((r) => r.name === g.name);
              return (
                <tr key={g.name} className={g.is_unclassified ? "is-warning" : undefined}>
                  <td>
                    {g.name}
                    {g.is_unclassified ? " · unclassified" : ""}
                  </td>
                  <td>{g.post_count}</td>
                  <td>{fmtNum(g.reach_sum ?? g.totals?.reach)}</td>
                  <td>{fmtNum(g.reach_avg ?? g.averages?.reach)}</td>
                  <td>
                    {fmtNum(g.known_reach_posts ?? g.available_counts?.reach)} /{" "}
                    {fmtNum(g.missing_counts?.reach)}
                  </td>
                  <td>
                    <DeltaCell delta={cmp?.delta} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ClientReportInspectView({ data }) {
  const period = data.period || {};
  const comparison = data.comparison || {};
  const metrics = data.metrics || {};
  const prompt = data.prompt_input || {};
  const strategy = prompt.strategy || {};
  const legend = prompt.format_legend || {};

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <p className="banner">{data.ai_analysis_banner}</p>

      <h4>Periods</h4>
      <ul className="plain-list">
        <li>
          Primary: <strong>{period.label || `${period.start} to ${period.end}`}</strong> (
          {period.length_days} days
          {period.mode === "calendar_month"
            ? ` · report month ${period.year}-${String(period.month).padStart(2, "0")}`
            : " · custom period"}
          )
        </li>
        <li>
          Comparison: <strong>{period.compare_label || `${period.previous_start} to ${period.previous_end}`}</strong>{" "}
          ({period.compare_length_days} days ·{" "}
          {period.compare_mode === "previous_equal_length"
            ? `default: previous ${period.compare_length_days || period.length_days || "?"} days (not the previous calendar month)`
            : "manual"}
          {period.lengths_equal ? "" : " · note: lengths differ"})
        </li>
      </ul>

      <MetricTotalsTable metrics={metrics} title="Posts — totals & averages (current period)" />
      {metrics.by_platform && Object.keys(metrics.by_platform).length ? (
        <p className="banner">
          Platforms in this report:{" "}
          {Object.entries(metrics.by_platform)
            .map(([name, count]) => `${name} ${count}`)
            .join(" · ")}
          . My Social Feeds only includes Instagram/Facebook; LinkedIn is counted here if it is in
          the period.
        </p>
      ) : null}

      <h4>Change vs comparison period ({comparison.metric || "reach"})</h4>
      <p className="hint">{comparison.note}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>Now</th>
              <th>Previous</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Post count</td>
              <td>{fmtNum(comparison.current_post_count)}</td>
              <td>{fmtNum(comparison.previous_post_count)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.post_count} />
              </td>
            </tr>
            <tr>
              <td>Sum {comparison.metric || "reach"}</td>
              <td>{fmtNum(comparison.current?.sum)}</td>
              <td>{fmtNum(comparison.previous?.sum)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.sum} />
              </td>
            </tr>
            <tr>
              <td>Average {comparison.metric || "reach"} (known)</td>
              <td>{fmtNum(comparison.current?.average_over_known)}</td>
              <td>{fmtNum(comparison.previous?.average_over_known)}</td>
              <td>
                <DeltaCell delta={comparison.deltas?.average_over_known} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <GroupTable
        title="Formats"
        groups={metrics.by_format}
        compareRows={comparison.by_format}
        unclassified={metrics.unclassified?.format}
      />
      <GroupTable
        title="Content pillars"
        groups={metrics.by_pillar}
        compareRows={comparison.by_pillar}
        unclassified={metrics.unclassified?.pillar}
      />
      <GroupTable
        title="Hooks"
        groups={metrics.by_hook}
        compareRows={comparison.by_hook}
        unclassified={metrics.unclassified?.hook}
      />

      {(metrics.caveats || []).length ? (
        <ul className="plain-list">
          {metrics.caveats.map((c) => (
            <li key={c} className="hint">
              {c}
            </li>
          ))}
        </ul>
      ) : null}

      {(data.missing || []).length ? (
        <>
          <h4>Missing / attention</h4>
          <ul className="plain-list">
            {data.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </>
      ) : null}

      <h4>Review view — input for Maaike&apos;s prompt</h4>
      <p className="hint">{prompt.note}</p>
      <div className="table-wrap">
        <table>
          <tbody>
            <tr>
              <th>Strategy present</th>
              <td>
                {(strategy.start_answers && Object.keys(strategy.start_answers).length) ||
                (strategy.strategy_fields && Object.keys(strategy.strategy_fields).length)
                  ? `yes · ${Object.keys(strategy.start_answers || {}).length} start answers · ${
                      (strategy.targets || []).length
                    } targets`
                  : "mostly empty"}
              </td>
            </tr>
            <tr>
              <th>Format legend</th>
              <td>
                {(legend.formats || []).length} formats · {(legend.pillars || []).length} pillars ·{" "}
                {(legend.hooks || []).length} hooks
              </td>
            </tr>
            <tr>
              <th>Post data</th>
              <td>{fmtNum(prompt.post_data?.count)} posts in period (details in aggregation above)</td>
            </tr>
            <tr>
              <th>Periods</th>
              <td>
                {period.label} vs {period.compare_label}
              </td>
            </tr>
            <tr>
              <th>Trend report</th>
              <td>
                {data.linked_trend
                  ? `#${data.linked_trend.id} v${data.linked_trend.version} · ${
                      STATUS_LABEL[data.linked_trend.status] || data.linked_trend.status
                    }${
                      data.linked_trend.is_mock
                        ? " · MOCK sample"
                        : data.linked_trend.status === "prepared" && !data.linked_trend.body_present
                          ? " · no sources/run yet (empty preparation)"
                          : ""
                    }`
                  : "not linked"}
              </td>
            </tr>
            <tr>
              <th>AI analysis</th>
              <td>
                {(() => {
                  const attached =
                    prompt.attached_ai_analysis_ids ||
                    prompt.post_data?.attached_ai_analyses?.analysis_ids ||
                    data.available?.completed_analysis_ids ||
                    [];
                  if (prompt.ai_analysis_executed || attached.length) {
                    return `attached · ids ${attached.length ? attached.join(", ") : "yes"}`;
                  }
                  if (prompt.ai_analysis_status && prompt.ai_analysis_status !== "not_executed") {
                    return prompt.ai_analysis_status;
                  }
                  return "no completed post analyses attached";
                })()}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {(legend.formats || []).length ? (
        <details>
          <summary className="hint">Show format legend</summary>
          <ul className="plain-list">
            {legend.formats.map((f) => (
              <li key={f.id}>
                {f.name}
                {f.explanation ? ` — ${f.explanation}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {strategy.start_answers && Object.keys(strategy.start_answers).length ? (
        <details>
          <summary className="hint">Show strategy start answers</summary>
          <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(strategy.start_answers, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

