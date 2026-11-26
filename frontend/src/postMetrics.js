/** Shared with the posts table so chart totals match the filtered rows. */

export function toIsoDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
  const dmy = raw.match(/^(\d{1,2})-(\d{1,2})-(\d{4})/);
  if (dmy) {
    return `${dmy[3]}-${String(dmy[2]).padStart(2, "0")}-${String(dmy[1]).padStart(2, "0")}`;
  }
  return raw.slice(0, 10);
}

export function metricValue(post, name) {
  const metric = post?.metrics?.[name];
  if (metric && typeof metric === "object" && Object.prototype.hasOwnProperty.call(metric, "value")) {
    return metric.value;
  }
  return post?.[name];
}

export function postIso(post) {
  return toIsoDate(post?.published_at || post?.cells?.Publicatiedatum || post?.published_label);
}

export function postPlatform(post) {
  return String(post?.cells?.Platform || post?.platform_label || post?.platform || "").trim();
}

export function postKind(post) {
  const cells = post?.cells || {};
  const raw = String(cells.Contentsoort || cells.Contentformat || post?.content_soort || post?.format || "").trim();
  if (!raw || raw === "not set" || raw === "—" || raw === "-") return "";
  return raw;
}

export function numericMetric(post, name) {
  const value = metricValue(post, name);
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function postInteractions(post) {
  const parts = ["likes", "comments", "shares", "saves"].map((name) => numericMetric(post, name));
  if (parts.every((value) => value == null)) return null;
  return parts.reduce((sum, value) => sum + (value || 0), 0);
}

export function formatCount(value) {
  if (value == null || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString("nl-NL", { maximumFractionDigits: 1 });
}

export function monthKey(iso) {
  return iso && iso.length >= 7 ? iso.slice(0, 7) : "";
}

export function monthBounds(yyyyMm) {
  if (!/^\d{4}-\d{2}$/.test(yyyyMm || "")) return { from: "", to: "" };
  const [y, m] = yyyyMm.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return { from: `${yyyyMm}-01`, to: `${yyyyMm}-${String(last).padStart(2, "0")}` };
}

const MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

export function formatMonthShort(yyyyMm) {
  const [y, m] = String(yyyyMm || "").split("-");
  const name = MONTHS[Number(m) - 1] || m;
  return name ? `${name} ${y}` : yyyyMm;
}

export function weekBuckets(posts, from, to) {
  if (!from || !to) return [];
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  const cursor = new Date(start);
  const day = cursor.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  cursor.setDate(cursor.getDate() + mondayOffset);
  const buckets = [];
  while (cursor <= end) {
    const weekStart = new Date(cursor);
    const weekEnd = new Date(cursor);
    weekEnd.setDate(weekEnd.getDate() + 6);
    const fromIso = isoDay(weekStart < start ? start : weekStart);
    const toIso = isoDay(weekEnd > end ? end : weekEnd);
    const inWeek = posts.filter((post) => {
      const iso = postIso(post);
      return iso && iso >= fromIso && iso <= toIso;
    });
    const reach = inWeek.reduce((sum, post) => sum + (numericMetric(post, "reach") || 0), 0);
    const hasReach = inWeek.some((post) => numericMetric(post, "reach") != null);
    buckets.push({
      label: `${weekStart.getDate()} ${MONTHS[weekStart.getMonth()]}`,
      from: fromIso,
      to: toIso,
      reach: hasReach ? reach : null,
    });
    cursor.setDate(cursor.getDate() + 7);
  }
  return buckets;
}

function isoDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
