import { formatCount } from "../postMetrics.js";

export function StatStrip({ items }) {
  return (
    <div className="stat-grid">
      {items.map((item) => (
        <div className="stat-tile" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

export function LineChart({ title, points, onPick }) {
  const width = 520;
  const height = 180;
  const pad = 28;
  const values = points.map((point) => point.value).filter((value) => value != null);
  const max = Math.max(1, ...values);
  const step = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;
  const coords = points.map((point, index) => {
    const x = pad + index * step;
    const y = point.value == null ? null : height - pad - (point.value / max) * (height - pad * 2);
    return { ...point, x, y };
  });
  const line = coords.filter((point) => point.y != null).map((point) => `${point.x},${point.y}`).join(" ");
  return (
    <section className="card chart-card">
      <h3>{title}</h3>
      <p className="hint">Bereik per week. Klik een punt voor de posts van die week.</p>
      {points.length ? (
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
          <polyline fill="none" stroke="#b87844" strokeWidth="3" points={line} />
          {coords.map((point) =>
            point.y == null ? null : (
              <g key={`${point.from}-${point.label}`}>
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="7"
                  fill="#b87844"
                  style={{ cursor: "pointer" }}
                  onClick={() => onPick?.(point)}
                >
                  <title>{`${point.label}: ${formatCount(point.value)}`}</title>
                </circle>
                <text x={point.x} y={height - 6} textAnchor="middle" fontSize="11" fill="currentColor">
                  {point.label}
                </text>
              </g>
            ),
          )}
        </svg>
      ) : (
        <p className="hint">Geen weken in deze periode.</p>
      )}
    </section>
  );
}

export function BarChart({ title, hint, rows, onPick }) {
  const max = Math.max(1, ...rows.map((row) => (row.value == null ? 0 : row.value)));
  return (
    <section className="card chart-card">
      <h3>{title}</h3>
      {hint ? <p className="hint">{hint}</p> : null}
      {rows.length ? (
        <div className="bar-list">
          {rows.map((row) => {
            const body = (
              <>
                <span>{row.label}</span>
                <span className="bar-track">
                  <span
                    className="bar-fill"
                    style={{ width: row.value == null ? "0%" : `${Math.max(4, (row.value / max) * 100)}%` }}
                  />
                </span>
                <strong>{formatCount(row.value)}</strong>
              </>
            );
            return onPick ? (
              <button key={row.label} type="button" className="bar-row" onClick={() => onPick(row)}>
                {body}
              </button>
            ) : (
              <div key={row.label} className="bar-row">
                {body}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="hint">Nog geen cijfers in deze periode.</p>
      )}
    </section>
  );
}
