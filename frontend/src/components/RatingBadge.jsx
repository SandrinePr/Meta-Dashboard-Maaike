export default function RatingBadge({ rating, showExplanation = false }) {
  if (!rating) {
    return <span className="rating-chip rating-neutral">not rated yet</span>;
  }
  const color = rating.color || "neutral";
  const label = rating.label || "Unable to rate";
  const score =
    rating.score_known && rating.score != null ? ` · score ${Number(rating.score).toLocaleString("en-US")}` : "";
  const provisional = rating.is_provisional ? " (Provisional)" : "";
  return (
    <div className="rating-block">
      <span className={`rating-chip rating-${color}`}>
        {label}
        {provisional}
        {score}
      </span>
      {showExplanation ? (
        <p className="hint rating-explanation">{rating.explanation || rating.reason || ""}</p>
      ) : null}
      {showExplanation && rating.excel_rating ? (
        <p className="hint">
          Excel/import: {rating.excel_rating}
          {rating.excel_source ? ` (${rating.excel_source})` : ""}
        </p>
      ) : null}
    </div>
  );
}
