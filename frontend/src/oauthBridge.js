/** Same-origin bridge between the Meta popup and the dashboard tab. */

export const META_OAUTH_MESSAGE = "maaike-meta-oauth";

export function dashboardClientsUrl({ clientId, metaChoose = true, error = "" } = {}) {
  const params = new URLSearchParams();
  params.set("page", "client_settings");
  if (clientId) params.set("client", String(clientId));
  if (error) params.set("meta_error", error);
  else if (metaChoose) params.set("meta", "choose");
  return `${window.location.origin}/?${params.toString()}`;
}

export function notifyMetaOauthResult({ ok, clientId, error }) {
  const payload = {
    type: META_OAUTH_MESSAGE,
    ok: Boolean(ok),
    clientId: clientId || null,
    error: error || null,
  };
  try {
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(META_OAUTH_MESSAGE);
      channel.postMessage(payload);
      channel.close();
    }
  } catch {
    // BroadcastChannel may be unavailable; postMessage below still runs.
  }
  const opener = window.opener;
  if (opener && !opener.closed) {
    try {
      opener.postMessage(payload, window.location.origin);
    } catch {
      try {
        opener.postMessage(payload, "*");
      } catch {
        // Parent may be gone or blocked by COOP.
      }
    }
  }
  return Boolean(opener && !opener.closed);
}

export function subscribeMetaOauth(handler) {
  function onWindowMessage(event) {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.type !== META_OAUTH_MESSAGE) return;
    handler(data);
  }

  let channel = null;
  function onChannelMessage(event) {
    const data = event.data;
    if (!data || data.type !== META_OAUTH_MESSAGE) return;
    handler(data);
  }

  window.addEventListener("message", onWindowMessage);
  try {
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(META_OAUTH_MESSAGE);
      channel.addEventListener("message", onChannelMessage);
    }
  } catch {
    channel = null;
  }

  return () => {
    window.removeEventListener("message", onWindowMessage);
    if (channel) {
      channel.removeEventListener("message", onChannelMessage);
      channel.close();
    }
  };
}
