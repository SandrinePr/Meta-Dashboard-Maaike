// Production (import.meta.env.PROD): same-origin unless VITE_API_URL is a real URL.
// Local: .env may set https://127.0.0.1:8000 / :8001. Render build uses VITE_API_URL=.
const configured = String(import.meta.env.VITE_API_URL ?? "").trim();
const isLocalhostApi = /^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?$/i.test(
  configured.replace(/\/$/, ""),
);
export const API_URL = (
  import.meta.env.PROD && (!configured || isLocalhostApi)
    ? ""
    : configured || "https://127.0.0.1:8000"
).replace(/\/$/, "");

export function apiUrl(path) {
  if (!API_URL) return path;
  return `${API_URL}${path}`;
}

export function storedAuthHeader() {
  try {
    const token = window.sessionStorage.getItem("hamster-auth");
    return token ? { Authorization: `Basic ${token}` } : {};
  } catch {
    return {};
  }
}

export async function api(path, { method = "GET", body, raw = false } = {}) {
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const headers = { ...storedAuthHeader() };
  if (!(body === undefined || isForm || raw)) headers["Content-Type"] = "application/json";
  const response = await fetch(apiUrl(path), {
    method,
    credentials: "include",
    headers,
    body: body === undefined ? undefined : isForm || raw ? body : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : "De aanvraag is mislukt. Controleer je internetverbinding en probeer het opnieuw.";
    throw new Error(detail);
  }
  return payload;
}
