import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { subscribeMetaOauth } from "./oauthBridge.js";
import AddClientModal from "./components/AddClientModal.jsx";
import ClientsPage from "./pages/ClientsPage.jsx";
import ComparisonPage from "./pages/ComparisonPage.jsx";
import ReportsAnalysisPage from "./pages/ReportsAnalysisPage.jsx";
import SettingsHubPage from "./pages/SettingsHubPage.jsx";
import SocialPostsPage from "./pages/SocialPostsPage.jsx";
import StrategyPage from "./pages/StrategyPage.jsx";

const APP_NAME = "Bruine Beer";

const NAV_PAGES = [
  ["strategy", "Targets & Strategy"],
  ["reports_analysis", "Rapporten"],
  ["comparison", "Competitors"],
  ["social_posts", "Social posts"],
  ["settings", "Settings"],
];

const TITLES = {
  strategy: "Targets & Strategy",
  reports_analysis: "Rapporten",
  comparison: "Competitors",
  social_posts: "Social posts",
  settings: "Settings",
  client_settings: "Client settings",
};

const REPORTS_TABS = new Set(["reports"]);
const SETTINGS_TABS = new Set(["ai", "legend", "backup"]);
const SOCIAL_TABS = new Set(["all_posts", "performance"]);

// Capture deep-link query once at module load so React StrictMode remounts still
// see ?page=/client=/post= after the first effect clears the address bar.
const BOOT_PARAMS =
  typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();

function resolveRoute(requestedPage) {
  const raw = requestedPage || "";
  if (
    raw === "posts" ||
    raw === "overview" ||
    raw === "zoeken" ||
    raw === "feeds" ||
    raw === "search" ||
    raw === "logs"
  ) {
    return {
      page: "social_posts",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "performance") {
    return {
      page: "social_posts",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "performance",
    };
  }
  if (raw === "weekly" || raw === "rapporten" || raw === "reports") {
    return {
      page: "reports_analysis",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "data" || raw === "export" || raw === "import") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "backup",
      socialTab: "all_posts",
    };
  }
  if (raw === "image_test" || raw === "images" || raw === "beeldtest") {
    // Images hub removed — keep bookmark working by landing on Reports.
    return {
      page: "reports_analysis",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "ai_trial" || raw === "ai-proef") {
    // AI Trial moved under Settings → AI Connections.
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "ai" || raw === "ai_connections") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "legend" || raw === "legenda") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "legend",
      socialTab: "all_posts",
    };
  }
  if (raw === "backup" || raw === "backup_restore") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "backup",
      socialTab: "all_posts",
    };
  }
  if (raw === "clients" || raw === "client_settings") {
    return {
      page: "client_settings",
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  if (raw === "comparison" || raw === "strategy" || raw === "social_posts") {
    return {
      page: raw,
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: raw === "social_posts" ? "all_posts" : "all_posts",
    };
  }
  if (raw === "reports_analysis" || raw === "settings") {
    return {
      page: raw,
      reportsTab: "reports",
      settingsTab: "ai",
      socialTab: "all_posts",
    };
  }
  return {
    page: "social_posts",
    reportsTab: "reports",
    settingsTab: "ai",
    socialTab: "all_posts",
  };
}

export default function App() {
  const [page, setPage] = useState("social_posts");
  const [reportsTab, setReportsTab] = useState("reports");
  const [settingsTab, setSettingsTab] = useState("ai");
  const [socialTab, setSocialTab] = useState("all_posts");
  const [socialPeriod, setSocialPeriod] = useState("");
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [metaChoice, setMetaChoice] = useState(false);
  const [metaError, setMetaError] = useState("");
  const [popupReturn, setPopupReturn] = useState(false);
  const [focusPostId, setFocusPostId] = useState(null);
  const [addClientOpen, setAddClientOpen] = useState(false);
  const [totals, setTotals] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncMessage, setLastSyncMessage] = useState("");

  const loadClients = useCallback(async () => {
    const payload = await api("/api/clients");
    setClients(payload.clients || []);
    return payload.clients || [];
  }, []);

  const selected = clients.find((item) => item.id === clientId) || clients[0] || null;

  const loadTotals = useCallback(async (id) => {
    if (!id) {
      setTotals(null);
      return null;
    }
    const payload = await api(`/api/clients/${id}/sync-totals`);
    setTotals(payload);
    return payload;
  }, []);

  const handleMetaOauthReturn = useCallback(
    (data) => {
      const returnedId = Number(data?.clientId);
      if (Number.isInteger(returnedId) && returnedId > 0) {
        setClientId(returnedId);
        window.localStorage.setItem("maaike-client-id", String(returnedId));
      }
      setPage("client_settings");
      setPopupReturn(false);
      if (data?.ok) {
        setMetaChoice(true);
        setMetaError("");
        setError("");
        setNotice("Meta login succeeded. Choose the correct accounts below.");
      } else {
        setMetaChoice(false);
        const message = data?.error || "Meta login was cancelled or denied.";
        setMetaError(message);
        setError(message);
        setNotice("");
      }
      loadClients().catch((exc) => setError(exc.message));
    },
    [loadClients],
  );

  useEffect(() => {
    document.title = APP_NAME;
    const params = BOOT_PARAMS;
    const requestedClient = Number(params.get("client"));
    const requestedPost = Number(params.get("post"));
    const route = resolveRoute(params.get("page"));
    setPage(route.page);
    setReportsTab(REPORTS_TABS.has(route.reportsTab) ? route.reportsTab : "reports");
    setSettingsTab(SETTINGS_TABS.has(route.settingsTab) ? route.settingsTab : "ai");
    setSocialTab(SOCIAL_TABS.has(route.socialTab) ? route.socialTab : "all_posts");
    if (params.get("meta") === "choose") {
      setMetaChoice(true);
      setPage("client_settings");
    }
    if (params.get("meta_error")) {
      setMetaError(params.get("meta_error"));
      setError(params.get("meta_error"));
      setPage("client_settings");
    }
    if (params.get("popup") === "1") {
      setPopupReturn(true);
      setPage("client_settings");
    }
    if (Number.isInteger(requestedClient) && requestedClient > 0) {
      setClientId(requestedClient);
      window.localStorage.setItem("maaike-client-id", String(requestedClient));
    } else {
      const stored = Number(window.localStorage.getItem("maaike-client-id"));
      if (Number.isInteger(stored) && stored > 0) {
        setClientId(stored);
      }
    }
    if (Number.isInteger(requestedPost) && requestedPost > 0) {
      setFocusPostId(requestedPost);
      if (!params.get("page") || params.get("page") === "logs" || params.get("page") === "search") {
        setPage("social_posts");
        setSocialTab("all_posts");
      }
    }
    window.history.replaceState({}, "", window.location.pathname);
    loadClients().catch((exc) => setError(exc.message));
  }, [loadClients]);

  useEffect(() => {
    if (popupReturn) return undefined;
    return subscribeMetaOauth(handleMetaOauthReturn);
  }, [popupReturn, handleMetaOauthReturn]);

  useEffect(() => {
    if (!selected) {
      setTotals(null);
      return;
    }
    setTotals(null);
    setLastSyncMessage("");
    loadTotals(selected.id).catch((exc) => setError(exc.message));
  }, [selected?.id, loadTotals]);

  function chooseClient(id) {
    setClientId(id);
    window.localStorage.setItem("maaike-client-id", String(id));
    setFocusPostId(null);
    setSocialPeriod("");
    setNotice("");
    setError("");
    setLastSyncMessage("");
    setTotals(null);
    setMenuOpen(false);
  }

  function openPage(next, postId = null) {
    setPage(next);
    setFocusPostId(postId);
    setMenuOpen(false);
  }

  function openSocialPost(postId) {
    setSocialTab("all_posts");
    openPage("social_posts", postId);
  }

  function openAddClient() {
    setAddClientOpen(true);
    setMenuOpen(false);
  }

  function openClientSettings() {
    setPage("client_settings");
    setMenuOpen(false);
  }

  async function syncMeta() {
    if (!selected || syncing) return;
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const payload = await api(`/api/clients/${selected.id}/posts/fetch`, { method: "POST", body: {} });
      setLastSyncMessage(payload.fetch_message || "Synchronisation finished.");
      setNotice(payload.fetch_message || "Synchronisation finished.");
      await loadClients();
      await loadTotals(selected.id);
    } catch (exc) {
      setError(exc.message);
      setLastSyncMessage(exc.message);
    } finally {
      setSyncing(false);
    }
  }

  const fetchAvailable = Boolean(selected?.connected);
  const pageTitle = TITLES[page] || APP_NAME;

  if (popupReturn) {
    return (
      <div className="shell popup-return-shell">
        <main className="main">
          <section className="panel">
            <h1 className="rro-page-title">{APP_NAME}</h1>
            <ClientsPage
              client={selected}
              oauthClientId={clientId}
              chooseClient={chooseClient}
              loadClients={loadClients}
              metaChoice={metaChoice}
              metaError={metaError}
              popupReturn
              settingsMode
              onMetaReturnHandled={() => setMetaChoice(true)}
              addClientOpen={false}
              onOpenAddClient={() => {}}
              onCloseAddClient={() => {}}
              onNotice={setNotice}
              onError={setError}
              onFetchPosts={async () => {}}
            />
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="shell">
      <button type="button" className="menu-toggle primary" onClick={() => setMenuOpen((open) => !open)}>
        Menu
      </button>
      <aside className={menuOpen ? "sidebar is-open" : "sidebar"}>
        <h2 className="app-brand">{APP_NAME}</h2>

        <div className="client-picker">
          <div className="client-picker-row">
            {clients.length ? (
              <label className="client-select-label">
                Client
                <select
                  value={selected ? String(selected.id) : ""}
                  onChange={(event) => chooseClient(Number(event.target.value))}
                >
                  {clients.map((item) => (
                    <option key={item.id} value={String(item.id)}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="muted">No clients yet.</p>
            )}
            <button
              className="icon-btn add-client-icon"
              type="button"
              title="Add client"
              aria-label="Add client"
              onClick={openAddClient}
            >
              +
            </button>
          </div>
          {selected ? (
            <div className="client-active-row">
              <span className="badge badge-active">Active</span>
              <span className="client-active-name">{selected.name}</span>
              <button
                className="icon-btn gear-btn"
                type="button"
                title="Client settings"
                aria-label="Client settings"
                onClick={openClientSettings}
              >
                ⚙
              </button>
            </div>
          ) : null}
        </div>

        <div className="sidebar-block sync-block">
          <div className="sidebar-title">Synchronisation</div>
          {!selected ? <p className="muted">Select a client to sync.</p> : null}
          {selected && totals ? (
            <div className="sync-stats">
              <div>
                <span>Instagram posts</span> <strong>{totals.instagram_posts}</strong>
              </div>
              <div>
                <span>Instagram comments</span> <strong>{totals.instagram_comments_label}</strong>
              </div>
              <div>
                <span>Facebook posts</span> <strong>{totals.facebook_posts}</strong>
              </div>
              <div>
                <span>Facebook comments</span> <strong>{totals.facebook_comments_label}</strong>
              </div>
              <div>
                <span>Last sync</span> <strong>{totals.synced_at}</strong>
              </div>
            </div>
          ) : null}
          {lastSyncMessage ? <p className="hint">{lastSyncMessage}</p> : null}
          <button
            className="primary"
            type="button"
            style={{ width: "100%" }}
            disabled={!selected || !fetchAvailable || syncing}
            onClick={syncMeta}
          >
            {syncing ? "Bezig met synchroniseren…" : "Synchroniseer Meta"}
          </button>
          {selected && !fetchAvailable ? (
            <p className="hint">Connect Meta in client settings first.</p>
          ) : null}
        </div>

        <hr className="sidebar-rule" />

        <nav className="nav">
          {NAV_PAGES.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={page === id ? "nav-button is-active" : "nav-button"}
              onClick={() => openPage(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <section className="panel">
          <h1 className="rro-page-title">
            {selected ? `${selected.name} · ${pageTitle}` : pageTitle}
          </h1>
          <div className="rro-mobile-sync-hint">
            Use the sidebar for client switching and synchronisation — tap <strong>Menu</strong> on
            small screens.
          </div>
          {notice ? <p className="banner">{notice}</p> : null}
          {error && page !== "client_settings" ? <p className="banner error">{error}</p> : null}
          {error && page === "client_settings" ? <p className="banner error">{error}</p> : null}

          {page === "client_settings" ? (
            <ClientsPage
              key={selected ? `client-${selected.id}` : "none"}
              client={selected}
              oauthClientId={clientId}
              chooseClient={chooseClient}
              loadClients={loadClients}
              metaChoice={metaChoice}
              metaError={metaError}
              popupReturn={false}
              settingsMode
              onMetaReturnHandled={() => setMetaChoice(true)}
              addClientOpen={false}
              onOpenAddClient={openAddClient}
              onCloseAddClient={() => {}}
              onNotice={setNotice}
              onError={setError}
              onFetchPosts={async () => {
                await syncMeta();
                setSocialTab("all_posts");
                openPage("social_posts");
              }}
            />
          ) : null}

          {!selected && page !== "settings" && page !== "client_settings" ? (
            <div className="stack">
              <p className="banner">
                Select a client in the sidebar or add one with <strong>+</strong>. Then open client
                settings (gear) to connect Meta.
              </p>
              <button className="primary" type="button" onClick={openAddClient}>
                + Add client
              </button>
            </div>
          ) : null}

          {page === "strategy" && selected ? (
            <StrategyPage key={`strategy-${selected.id}`} client={selected} />
          ) : null}
          {page === "reports_analysis" && selected ? (
            <ReportsAnalysisPage key={`hub-${selected.id}`} client={selected} />
          ) : null}
          {page === "social_posts" && selected ? (
            <SocialPostsPage
              key={`social-${selected.id}`}
              client={selected}
              initialTab={socialTab}
              focusPostId={focusPostId}
              onClearFocus={() => setFocusPostId(null)}
              onTabChange={setSocialTab}
              onOpenPost={openSocialPost}
              onSynced={() => loadTotals(selected.id)}
              periodSelection={socialPeriod}
              onPeriodChange={setSocialPeriod}
            />
          ) : null}
          {page === "comparison" && selected ? (
            <ComparisonPage key={`cmp-${selected.id}`} client={selected} />
          ) : null}
          {page === "settings" ? (
            <SettingsHubPage
              client={selected}
              initialTab={settingsTab}
              onNotice={setNotice}
              onError={setError}
              onTabChange={setSettingsTab}
            />
          ) : null}
        </section>
      </main>

      <AddClientModal
        open={addClientOpen}
        onClose={() => setAddClientOpen(false)}
        onError={setError}
        onCreated={(created) => {
          loadClients().then(() => {
            chooseClient(created.id);
            setPage("client_settings");
            setNotice(`Client “${created.name}” was added. Connect Facebook and Instagram next.`);
          });
        }}
      />
    </div>
  );
}
