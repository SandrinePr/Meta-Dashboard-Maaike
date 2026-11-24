import RatingBadge from "./RatingBadge.jsx";

function metricLabel(name) {
  return (
    {
      views: "Weergaven",
      reach: "Bereik",
      likes: "Likes",
      comments: "Reacties",
      shares: "Gedeeld",
      saves: "Opgeslagen",
      clicks: "Klikken",
    }[name] || name
  );
}

function dutchMediaNote(note) {
  if (!note) return "";
  if (note === "No media available for this post.") {
    return "Geen afbeelding of video beschikbaar bij dit bericht.";
  }
  return note;
}

function dutchKindLabel(label) {
  if (!label) return "";
  const map = {
    Post: "Bericht",
    Image: "Afbeelding",
    Carousel: "Carrousel",
    Video: "Video",
    Reel: "Reel",
    Story: "Story",
    "not available": "Onbekend type",
  };
  return map[label] || label;
}

function StatRow({ metrics, platform, highlight }) {
  const order =
    platform === "facebook"
      ? ["views", "likes", "comments", "shares"]
      : ["views", "likes", "comments", "saves", "shares"];
  return (
    <div className="rro-card-stats">
      {order.map((name) => {
        const metric = metrics?.[name];
        const missing =
          !metric ||
          metric.available === false ||
          metric.label === "not available" ||
          metric.label === "niet beschikbaar";
        return (
          <span className="rro-stat" key={name}>
            <span className="rro-stat-label-inline">{metricLabel(name)}</span>
            <span
              className={
                highlight === name
                  ? "rro-stat-value-inline rro-stat-value-inline--highlight"
                  : missing
                    ? "rro-stat-value-inline rro-stat-missing"
                    : "rro-stat-value-inline"
              }
            >
              {missing ? "n.v.t." : metric.label}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function highlightCaption(text, query) {
  const value = text || "Geen berichttekst beschikbaar.";
  const q = (query || "").trim();
  if (!q || q.length < 2) return value;
  try {
    const parts = value.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
    return parts.map((part, index) =>
      part.toLowerCase() === q.toLowerCase() ? <mark key={`${part}-${index}`}>{part}</mark> : part,
    );
  } catch {
    return value;
  }
}

function matchBadges(caption, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return null;
  const text = (caption || "").toLowerCase();
  const badges = [];
  if (text.includes(q)) badges.push(["caption", "Tekst"]);
  if (text.includes(`#${q}`) || (q.startsWith("#") && text.includes(q))) badges.push(["hashtag", "Hashtag"]);
  if (text.includes(`@${q}`) || (q.startsWith("@") && text.includes(q))) badges.push(["tag", "Tag"]);
  if (!badges.length && text.includes(q)) badges.push(["caption", "Tekst"]);
  return badges.map(([cls, label]) => (
    <span key={cls} className={`badge badge-${cls} badge-match`}>
      {label}
    </span>
  ));
}

export default function ResultCard({
  post,
  query = "",
  highlightMetric = null,
  rankBanner = null,
  focused = false,
  detailsOpen = false,
  detailsLabel = "Details",
  detailsOpenLabel = "Sluit details",
  onOpenDetails,
  onOpenLogs,
  onOpenFeed,
  onOpenPost,
  children = null,
}) {
  const openPost = onOpenPost || onOpenLogs || onOpenFeed;
  const cover = post.cover_url;
  const video = (post.media || []).find((item) => item.kind === "video");
  const account = post.account || post.cells?.Account || "";
  const mediaNote = dutchMediaNote(post.media_note);

  return (
    <article className={`rro-result-card${focused ? " is-focused" : ""}`} id={post.dom_id || undefined}>
      {rankBanner}
      <div className="rro-result-row">
        <div className="rro-result-thumb">
          {cover ? (
            <div className="rro-thumb">
              <img
                src={cover}
                alt=""
                loading="lazy"
                referrerPolicy="no-referrer"
                onError={(event) => {
                  const wrap = event.currentTarget.parentElement;
                  event.currentTarget.remove();
                  if (wrap && !wrap.querySelector(".rro-thumb-placeholder")) {
                    const empty = document.createElement("div");
                    empty.className = "rro-thumb-placeholder";
                    empty.textContent = "Geen afbeelding";
                    wrap.replaceWith(empty);
                  }
                }}
              />
            </div>
          ) : video ? (
            <div className="rro-thumb">
              <video src={video.url} muted preload="metadata" referrerPolicy="no-referrer" />
            </div>
          ) : (
            <div className="rro-thumb-placeholder">Geen afbeelding</div>
          )}
        </div>
        <div className="rro-result-body">
          <div className="rro-card-badges">
            <span className={`badge badge-platform badge-${post.platform}`}>{post.platform_label}</span>
            <span className="badge badge-content badge-type">
              {dutchKindLabel(post.content_kind_label || post.content_type_label)}
            </span>
            {(post.match_badges || []).map((badge) => (
              <span key={badge} className={`badge badge-${badge} badge-match`}>
                {badge === "caption"
                  ? "Tekst"
                  : badge === "comment"
                    ? "Reactie"
                    : badge === "hashtag"
                      ? "Hashtag"
                      : badge === "tag"
                        ? "Tag"
                        : badge}
              </span>
            ))}
            {!(post.match_badges || []).length ? matchBadges(post.caption, query) : null}
          </div>
          <div className="rro-card-date">
            {post.published_label && post.published_label !== "not available"
              ? post.published_label
              : "Datum onbekend"}
            {account ? ` · ${account}` : ""}
          </div>
          {post.formula_rating ? <RatingBadge rating={post.formula_rating} /> : null}
          <div className="rro-card-text">{highlightCaption(post.caption, query)}</div>
          {mediaNote ? <p className="hint">{mediaNote}</p> : null}
          {post.formula_rating?.score_known &&
          (post.formula_rating?.explanation || post.formula_rating?.reason) ? (
            <p className="hint rating-explanation">
              {post.formula_rating.explanation || post.formula_rating.reason}
            </p>
          ) : null}
          {post.log_rating || post.log_insight || post.log_action ? (
            <div className="stack" style={{ marginTop: "0.5rem" }}>
              {post.log_rating ? (
                <p className="hint" style={{ margin: 0 }}>
                  <strong>Beoordeling:</strong> {post.log_rating}
                </p>
              ) : null}
              {post.log_insight ? (
                <p className="hint" style={{ margin: 0 }}>
                  <strong>Inzicht:</strong> {post.log_insight}
                </p>
              ) : null}
              {post.log_action ? (
                <p className="hint" style={{ margin: 0 }}>
                  <strong>Vervolgactie:</strong> {post.log_action}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="rro-card-actions">
          {post.permalink ? (
            <a className="rro-btn-link" href={post.permalink} target="_blank" rel="noopener noreferrer">
              Origineel bericht
            </a>
          ) : (
            <div className="rro-btn-disabled">Geen link</div>
          )}
          <div className="row-actions" style={{ marginTop: "0.45rem" }}>
            {onOpenDetails ? (
              <button className="secondary" type="button" onClick={() => onOpenDetails(post)}>
                {detailsOpen ? detailsOpenLabel : detailsLabel}
              </button>
            ) : null}
            {openPost ? (
              <button className="secondary" type="button" onClick={() => openPost(post.id)}>
                Open in Alle berichten
              </button>
            ) : null}
          </div>
        </div>
      </div>
      <StatRow metrics={post.metrics} platform={post.platform} highlight={highlightMetric} />
      {children}
    </article>
  );
}

export { metricLabel };
