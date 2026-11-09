export const API_URL = (import.meta.env.VITE_API_URL || "https://127.0.0.1:8000").replace(/\/$/, "");

export function apiUrl(path) {
  return `${API_URL}${path}`;
}

export async function api(path, { method = "GET", body, raw = false } = {}) {
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const response = await fetch(apiUrl(path), {
    method,
    credentials: "include",
    headers: body === undefined || isForm || raw ? undefined : { "Content-Type": "application/json" },
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
    const detail = payload && typeof payload.detail === "string" ? payload.detail : "Request failed.";
    throw new Error(detail);
  }
  return payload;
}
