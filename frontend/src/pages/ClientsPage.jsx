import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import AddClientModal from "../components/AddClientModal.jsx";
import { dashboardClientsUrl, notifyMetaOauthResult } from "../oauthBridge.js";

export default function ClientsPage({
  client,
  oauthClientId,
  chooseClient,
  loadClients,
  metaChoice,
  metaError,
  popupReturn,
  settingsMode = false,
  onMetaReturnHandled,
  onNotice,
  onError,
  onOpenAddClient,
  addClientOpen,
  onCloseAddClient,
  onFetchPosts,
}) {
  const [rename, setRename] = useState(client ? client.name : "");
  const [renameClientId, setRenameClientId] = useState(client ? client.id : null);
  const [meta, setMeta] = useState(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [busy, setBusy] = useState("");
  const [sameTabUrl, setSameTabUrl] = useState("");
  const [justCreated, setJustCreated] = useState(false);
  const [popupStuck, setPopupStuck] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const popupRef = useRef(null);

  const returnClientId = client?.id || oauthClientId || null;
  const returnHref = dashboardClientsUrl({
    clientId: returnClientId,
    metaChoose: !metaError,
    error: metaError || "",
  });

  if ((client ? client.id : null) !== renameClientId) {
    setRenameClientId(client ? client.id : null);
    setRename(client ? client.name : "");
    setSameTabUrl("");
    setJustCreated(false);
  }

  async function refreshMeta(clientId = client?.id || oauthClientId) {
    if (!clientId) {
      setMeta(null);
      return null;
    }
    const payload = await api(`/api/clients/${clientId}/meta`);
    setMeta(payload);
    const first = payload.pages?.selectable?.[0];
    setPageIndex(first ? first.index : 0);
    return payload;
  }

  useEffect(() => {
    if (popupReturn) return;
    refreshMeta().catch((exc) => onError(exc.message));
  }, [client, metaChoice, popupReturn, onError]);

  useEffect(() => {
    if (!popupReturn) return;
    const hadOpener = notifyMetaOauthResult({
      ok: !metaError,
      clientId: returnClientId,
      error: metaError || null,
    });
    window.setTimeout(() => {
      try {
        window.close();
      } catch {
        // Browsers often block close after a cross-site OAuth redirect.
      }
      window.setTimeout(() => setPopupStuck(true), 250);
    }, 150);
    if (!hadOpener) {
      setPopupStuck(true);
    }
  }, [popupReturn, metaError, returnClientId]);

  async function saveName(event) {
    event.preventDefault();
    if (!client) return;
    onError("");
    setBusy("rename");
    try {
      await api(`/api/clients/${client.id}`, { method: "PATCH", body: { name: rename } });
      await loadClients();
      onNotice("Name saved.");
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function startLogin({ forceSameTab = false } = {}) {
    if (!client) return;
    onError("");
    setBusy("start");
    setSameTabUrl("");
    try {
      const payload = await api(`/api/clients/${client.id}/meta/start`, {
        method: "POST",
        body: { popup: !forceSameTab },
      });
      const url = payload.login_url || "";
      if (!url) {
        throw new Error("Meta did not return a login URL.");
      }
      if (forceSameTab) {
        window.location.assign(url);
        return;
      }
      const popup = window.open(url, "maaike-meta-login", "popup=yes,width=720,height=780");
      if (!popup) {
        setSameTabUrl(url);
        onError("The browser blocked the popup. Use the button below to continue in this tab.");
        setBusy("");
        return;
      }
      popupRef.current = popup;
      onNotice("Log in to Meta in the opened window. This screen updates when you return.");
      const timer = window.setInterval(() => {
        if (popup.closed) {
          window.clearInterval(timer);
          popupRef.current = null;
          setBusy("");
          loadClients()
            .then(() => refreshMeta())
            .then((payload) => {
              if (payload?.pages?.selectable?.length) {
                onNotice("Meta login succeeded. Choose the correct accounts below.");
                onError("");
                onMetaReturnHandled?.();
              }
            })
            .catch((exc) => onError(exc.message));
        }
      }, 800);
    } catch (exc) {
      onError(exc.message);
      setBusy("");
    }
  }

  async function confirmPage() {
    if (!client) return;
    onError("");
    setBusy("confirm");
    try {
      const payload = await api(`/api/clients/${client.id}/meta/confirm`, {
        method: "POST",
        body: { page_index: Number(pageIndex) },
      });
      await loadClients();
      const fresh = await refreshMeta();
      onNotice(payload.message || "Connected.");
      setJustCreated(false);
      return fresh;
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function cancelLogin() {
    if (!client) return;
    setBusy("cancel");
    try {
      await api(`/api/clients/${client.id}/meta/cancel`, { method: "POST", body: {} });
      await refreshMeta();
      onNotice("Connecting cancelled. You can try again.");
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function recheck() {
    if (!client) return;
    onError("");
    setBusy("recheck");
    try {
      const payload = await api(`/api/clients/${client.id}/meta/recheck`, { method: "POST", body: {} });
      await loadClients();
      await refreshMeta();
      onNotice(payload.message || "Connection checked.");
    } catch (exc) {
      await loadClients();
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function disconnectMeta() {
    if (!client) return;
    setBusy("disconnect");
    onError("");
    try {
      const payload = await api(`/api/clients/${client.id}/meta/disconnect`, { method: "POST", body: {} });
      setDisconnectOpen(false);
      await loadClients();
      await refreshMeta();
      onNotice(payload.message || "Meta disconnected for this client.");
    } catch (exc) {
      onError(exc.message);
    } finally {
      setBusy("");
    }
  }

  if (popupReturn) {
    return (
      <div className="stack card meta-step">
        <h2>{popupStuck ? "Continue in the dashboard" : "One moment…"}</h2>
        <p className="hint">
          {metaError
            ? "Login did not succeed. Close this window or return to client settings."
            : popupStuck
              ? "This window could not close automatically. Open client settings to choose a Facebook page and confirm. Only then will the status show Connected."
              : "Login succeeded. This window will close and the dashboard will update."}
        </p>
        <p>
          <a className="primary facebook-login" href={returnHref}>
            Back to client settings
          </a>
        </p>
        <p className="muted">
          Button not working? Open <a href={returnHref}>{returnHref}</a>
        </p>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="page-toolbar">
        <div>
          <div className="search-form-header">
            <h3>{settingsMode ? "Client settings" : "Clients"}</h3>
          </div>
          <p className="hint">
            Rename this client and connect Meta here. Active in the sidebar only means selected —
            Connected is a separate Meta status. Competitor crawling stays under Competitors.
          </p>
        </div>
        {!settingsMode ? (
          <button className="primary" type="button" onClick={onOpenAddClient}>
            + Add client
          </button>
        ) : null}
      </div>

      <AddClientModal
        open={addClientOpen}
        onClose={onCloseAddClient}
        onError={onError}
        onCreated={(created) => {
          loadClients().then(() => {
            chooseClient(created.id);
            setJustCreated(true);
            onNotice(`Client “${created.name}” was added. Connect Facebook and Instagram next.`);
          });
        }}
      />

      {!client ? (
        <p className="banner">
          No client selected. Use <strong>+</strong> in the sidebar or pick an existing client.
        </p>
      ) : (
        <>
          <form className="form-grid card" onSubmit={saveName}>
            <label>
              Client name
              <input value={rename} onChange={(event) => setRename(event.target.value)} disabled={busy === "rename"} />
            </label>
            <button className="secondary" type="submit" disabled={busy === "rename"}>
              {busy === "rename" ? "Saving…" : "Save name"}
            </button>
          </form>

          {meta ? (
            <MetaConnectFlow
              client={client}
              meta={meta}
              pageIndex={pageIndex}
              setPageIndex={setPageIndex}
              busy={busy}
              sameTabUrl={sameTabUrl}
              highlightConnect={justCreated || !meta.connected}
              onStart={() => startLogin({ forceSameTab: false })}
              onSameTab={() => startLogin({ forceSameTab: true })}
              onSameTabHref={sameTabUrl}
              onConfirm={confirmPage}
              onCancel={cancelLogin}
              onRecheck={recheck}
              onFetchPosts={onFetchPosts}
              onDisconnect={() => setDisconnectOpen(true)}
            />
          ) : (
            <p className="muted">Loading connection status…</p>
          )}

          {disconnectOpen ? (
            <div className="modal-backdrop" role="presentation" onClick={() => setDisconnectOpen(false)}>
              <div
                className="modal-card"
                role="dialog"
                aria-modal="true"
                aria-labelledby="disconnect-title"
                onClick={(event) => event.stopPropagation()}
              >
                <h2 id="disconnect-title">Disconnect Meta?</h2>
                <p>
                  This removes the <strong>Meta (Facebook/Instagram) connection for {client.name} only</strong>.
                  Other clients are not changed. The client itself is not deleted.
                </p>
                <p className="hint">
                  Saved posts, strategy, legends and reports stay in the database. You can reconnect later.
                </p>
                {(meta?.page_name || meta?.ig_username) && (
                  <p>
                    Current link: {meta.page_name || "Facebook page"}
                    {meta.ig_username ? ` · @${meta.ig_username}` : ""}
                  </p>
                )}
                <div className="row-actions">
                  <button className="secondary" type="button" onClick={() => setDisconnectOpen(false)} disabled={busy === "disconnect"}>
                    Cancel
                  </button>
                  <button className="primary" type="button" onClick={disconnectMeta} disabled={busy === "disconnect"}>
                    {busy === "disconnect" ? "Disconnecting…" : "Disconnect Meta"}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function MetaConnectFlow({
  client,
  meta,
  pageIndex,
  setPageIndex,
  busy,
  sameTabUrl,
  highlightConnect,
  onStart,
  onSameTab,
  onSameTabHref,
  onConfirm,
  onCancel,
  onRecheck,
  onFetchPosts,
  onDisconnect,
}) {
  const pages = meta.pages;
  const choosing = Boolean(pages);
  const connected = Boolean(meta.connected);

  if (connected && !choosing) {
    return (
      <section className="card stack meta-step">
        <p className="step-label">Step 3 — Done</p>
        <h3>Connected</h3>
        <p className="status">Connected</p>
        {meta.page_name ? (
          <p>
            <strong>Facebook page:</strong> {meta.page_name}
            {meta.ig_username ? (
              <>
                <br />
                <strong>Instagram:</strong> @{meta.ig_username}
              </>
            ) : null}
          </p>
        ) : null}
        {(meta.notes || []).map((note) => (
          <p key={note} className="hint">
            {note}
          </p>
        ))}
        <div className="row-actions">
          <button className="primary" type="button" onClick={onFetchPosts}>
            Fetch posts and open Search
          </button>
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onRecheck}>
            {busy === "recheck" ? "Checking…" : "Recheck connection"}
          </button>
          <button className="secondary" type="button" disabled={!meta.ready || Boolean(busy)} onClick={onStart}>
            Reconnect
          </button>
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onDisconnect}>
            Disconnect Meta
          </button>
        </div>
        <p className="hint">
          “Fetch posts” syncs via Meta and then opens Search. If sync fails (permissions/token), you
          will see an error with the next step.
        </p>
      </section>
    );
  }

  if (choosing) {
    const selectable = pages.selectable || [];
    const blocked = pages.blocked || [];
    return (
      <section className="card stack meta-step">
        <p className="step-label">Step 2 — Choose accounts</p>
        <h3>Choose accounts for {client.name}</h3>
        <p className="hint">
          Pick the Facebook page with the professional Instagram account for this client. Other
          clients are left unchanged.
        </p>
        {pages.empty ? (
          <p className="banner">Meta returned no Facebook page this account can manage.</p>
        ) : null}
        {!selectable.length && !pages.empty ? (
          <p className="banner">
            No pages with a professional Instagram account. Check permissions in Meta Business Suite.
          </p>
        ) : null}
        {selectable.length ? (
          <div className="account-grid">
            {selectable.map((page) => (
              <label key={page.index} className={`account-card${pageIndex === page.index ? " is-selected" : ""}`}>
                <input
                  type="radio"
                  name="meta-page"
                  checked={pageIndex === page.index}
                  onChange={() => setPageIndex(page.index)}
                />
                <span className="account-avatar" aria-hidden="true">
                  {(page.page_name || "?").slice(0, 1).toUpperCase()}
                </span>
                <span>
                  <strong>{page.page_name}</strong>
                  <span className="muted">{page.ig_username ? `@${page.ig_username}` : "Instagram account"}</span>
                </span>
              </label>
            ))}
          </div>
        ) : null}
        {blocked.length ? (
          <div className="banner">
            <strong>Not available</strong>
            <ul>
              {blocked.map((item) => (
                <li key={typeof item === "string" ? item : item.page_name}>
                  {typeof item === "string" ? item : `${item.page_name} — ${item.reason}`}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="row-actions">
          <button className="primary" type="button" disabled={!selectable.length || busy === "confirm"} onClick={onConfirm}>
            {busy === "confirm" ? "Checking…" : "Confirm this connection"}
          </button>
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className={`card stack meta-step${highlightConnect ? " is-highlight" : ""}`}>
      <p className="step-label">Step 1 — Connect</p>
      <h3>Connect Facebook and Instagram</h3>
      {meta.status_label ? (
        <p className={meta.connected ? "status" : "banner error"}>
          Status: {meta.connected ? "Connected" : "Not connected / reconnect required"}
          {meta.status_detail ? ` — ${meta.status_detail}` : ""}
        </p>
      ) : null}
      {(meta.page_name || meta.ig_username) && !meta.connected ? (
        <p>
          <strong>Last linked:</strong> {meta.page_name || "Facebook page"}
          {meta.ig_username ? <> · Instagram @{meta.ig_username}</> : null}
        </p>
      ) : null}
      <p>
        Log in to Meta and choose the accounts for <strong>{client.name}</strong>. You grant permission
        to fetch posts and stats.
      </p>
      <p className="hint">
        This dashboard never asks for your Facebook password or tokens. Login happens on the official
        Meta/Facebook site.
      </p>
      {(meta.missing || []).map((item) => (
        <p key={item} className="banner error">
          {item}
        </p>
      ))}
      {!meta.ready ? (
        <p className="banner warn-soft">
          Meta login is not ready yet (missing app settings). Ask an admin to configure the Meta app
          and restart the API. You can still import Excel and edit existing posts locally.
        </p>
      ) : null}
      {(meta.notes || []).map((note) => (
        <p key={note} className="hint">
          {note}
        </p>
      ))}
      <div className="row-actions">
        <button className="facebook-login" type="button" disabled={!meta.ready || Boolean(busy)} onClick={onStart}>
          <span className="facebook-f" aria-hidden="true">
            f
          </span>
          <span>{busy === "start" ? "Working…" : "Continue with Facebook"}</span>
        </button>
        {(meta.page_name || meta.ig_username || meta.connected) && (
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onDisconnect}>
            Disconnect Meta
          </button>
        )}
      </div>
      {sameTabUrl || onSameTabHref ? (
        <div className="banner">
          <p>Popup blocked? Continue in this tab.</p>
          <button className="secondary" type="button" onClick={onSameTab}>
            Continue in this tab
          </button>
        </div>
      ) : null}
    </section>
  );
}
