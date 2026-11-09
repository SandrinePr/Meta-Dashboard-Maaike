/** Compact English Meta connection labels. Active client ≠ Connected. */

export function metaConnectionLabel(client) {
  if (!client) return "Not connected";
  if (client.connected) return "Connected";
  const status = String(client.status_label || "").toLowerCase();
  const raw = String(client.meta_status || client.status || "").toLowerCase();
  if (
    raw === "revoked" ||
    raw === "expired" ||
    raw === "error" ||
    status.includes("revoked") ||
    status.includes("expired") ||
    status.includes("failed") ||
    status.includes("ingetrokken") ||
    status.includes("verlopen") ||
    status.includes("mislukt") ||
    status.includes("reconnect")
  ) {
    return "Reconnect required";
  }
  if (client.page_name || client.ig_username || client.meta_page_name || client.meta_ig_username) {
    return "Reconnect required";
  }
  return "Not connected";
}

export function metaConnectionHint(client) {
  if (!client) return "";
  if (client.connected) {
    const page = client.page_name || client.meta_page_name || "";
    const ig = client.ig_username || client.meta_ig_username || "";
    if (page && ig) return `${page} (@${ig})`;
    return page || (ig ? `@${ig}` : "Meta linked");
  }
  return metaConnectionLabel(client);
}
