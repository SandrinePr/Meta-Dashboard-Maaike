function dutchRatingLabel(label) {
  if (!label) return "Nog niet beoordeeld";
  const clean = String(label).trim();
  const map = {
    "not rated yet": "Nog niet beoordeeld",
    "Rating pending": "Nog niet beoordeeld",
    "Unable to rate": "Nog geen score",
    Good: "Goed",
    Average: "Gemiddeld",
    Low: "Aandacht nodig",
  };
  return map[clean] || clean;
}

export default function RatingBadge({ rating, showExplanation = false }) {
  if (!rating) {
    return <span className="rating-chip rating-neutral">Nog niet beoordeeld</span>;
  }
  // Hide provisional empty "not rated yet" chip on cards unless a formula is active or Excel rating exists.
  if (!rating.score_known && !rating.excel_rating && !showExplanation) {
    const raw = String(rating.label || "").toLowerCase();
    if (!raw || raw.includes("pending") || raw.includes("not rated") || raw.includes("unable")) {
      return null;
    }
  }
  const color = rating.color || "neutral";
  const label = dutchRatingLabel(rating.label);
  const score =
    rating.score_known && rating.score != null
      ? ` · score ${Number(rating.score).toLocaleString("nl-NL")}`
      : "";
  const provisional = rating.is_provisional && rating.score_known ? " (voorlopig)" : "";
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
          Beoordeling uit Excel: {rating.excel_rating}
          {rating.excel_source ? ` (${rating.excel_source})` : ""}
        </p>
      ) : null}
    </div>
  );
}
