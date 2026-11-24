import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { subscribeMetaOauth } from "./oauthBridge.js";
import ClientsPage from "./pages/ClientsPage.jsx";
import ClientSetupPage from "./pages/ClientSetupPage.jsx";
import ComparisonPage from "./pages/ComparisonPage.jsx";
import ReportsAnalysisPage from "./pages/ReportsAnalysisPage.jsx";
import SettingsHubPage from "./pages/SettingsHubPage.jsx";
import SocialPostsPage from "./pages/SocialPostsPage.jsx";
import StrategyPage from "./pages/StrategyPage.jsx";

const APP_NAME = "Bruine Beer";

const NAV_PAGES = [
  ["strategy", "Doelen & Strategie"],
  ["reports_analysis", "Rapporten"],
  ["comparison", "Concurrenten"],
  ["social_posts", "Socialmediaberichten"],
  ["settings", "Instellingen"],
];

const TITLES = {
  strategy: "Doelen & Strategie",
  reports_analysis: "Rapporten",
  comparison: "Concurrenten",
  social_posts: "Socialmediaberichten",
  settings: "Instellingen",
  client_settings: "Alle klanten",
  client_setup: "Klant inrichten",
};

const REPORTS_TABS = new Set(["reports"]);
const SETTINGS_TABS = new Set(["ai", "prompts", "planning", "legend", "backup"]);
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
  if (raw === "prompts" || raw === "prompt_settings" || raw === "prompten") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "prompts",
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
  if (raw === "planning" || raw === "rapportplanning" || raw === "report_planning") {
    return {
      page: "settings",
      reportsTab: "reports",
      settingsTab: "planning",
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
  if (raw === "client_setup" || raw === "klant_inrichten" || raw === "add_client") {
    return {
      page: "client_setup",
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
  const [page, setPage] = useState(() => {
    const saved =
      typeof window !== "undefined" ? window.sessionStorage.getItem("maaike-active-page") : "";
    return resolveRoute(BOOT_PARAMS.get("page") || saved || "").page;
  });
  const [reportsTab, setReportsTab] = useState("reports");
  const [settingsTab, setSettingsTab] = useState("ai");
  const [socialTab, setSocialTab] = useState("all_posts");
  const [strategyTab, setStrategyTab] = useState("specialist");
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
  const [setupIsNew, setSetupIsNew] = useState(false);
  const [totals, setTotals] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncMessage, setLastSyncMessage] = useState("");

  const loadClients = useCallback(async () => {
    const payload = await api("/api/clients");
    setClients(payload.clients || []);
    return payload.clients || [];
  }, []);

  // Do not auto-pick the first client: after delete / empty state the overview must stay open.
  const selected = clients.find((item) => item.id === clientId) || null;

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
      setPage("client_setup");
      setSetupIsNew(false);
      setPopupReturn(false);
      if (data?.ok) {
        setMetaChoice(true);
        setMetaError("");
        setError("");
        setNotice("Inloggen bij Meta gelukt. Kies hieronder de juiste accounts.");
      } else {
        setMetaChoice(false);
        const message = data?.error || "Inloggen bij Meta is geannuleerd of geweigerd.";
        // Keep the message on metaError only; ClientSetupPage shows the attempt result
        // and clears prior banners when a new attempt starts.
        setMetaError(message);
        setError("");
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
    const savedPage =
      typeof window !== "undefined" ? window.sessionStorage.getItem("maaike-active-page") : "";
    const route = resolveRoute(params.get("page") || savedPage || "");
    setPage(route.page);
    setReportsTab(REPORTS_TABS.has(route.reportsTab) ? route.reportsTab : "reports");
    setSettingsTab(SETTINGS_TABS.has(route.settingsTab) ? route.settingsTab : "ai");
    setSocialTab(SOCIAL_TABS.has(route.socialTab) ? route.socialTab : "all_posts");
    if (params.get("meta") === "choose") {
      setMetaChoice(true);
      setPage("client_setup");
      setSetupIsNew(false);
    }
    if (params.get("meta_error")) {
      setMetaError(params.get("meta_error"));
      setError("");
      setPage("client_setup");
      setSetupIsNew(false);
    }
    if (params.get("popup") === "1") {
      setPopupReturn(true);
      setPage("client_setup");
      setSetupIsNew(false);
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
    try {
      if (page && page !== "client_setup") {
        window.sessionStorage.setItem("maaike-active-page", page);
      }
    } catch {
      /* ignore */
    }
  }, [page]);

  useEffect(() => {
    if (!selected) {
      setTotals(null);
      return undefined;
    }
    let cancelled = false;
    const activeClientId = selected.id;
    setTotals(null);
    setLastSyncMessage("");
    api(`/api/clients/${activeClientId}/sync-totals`)
      .then((payload) => {
        if (cancelled) return;
        if (payload?.client_id != null && Number(payload.client_id) !== Number(activeClientId)) {
          return;
        }
        setTotals(payload);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id]);

  function chooseClient(id) {
    if (id == null) {
      setClientId(null);
      window.localStorage.removeItem("maaike-client-id");
    } else {
      setClientId(id);
      window.localStorage.setItem("maaike-client-id", String(id));
    }
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

  function clearMetaAttemptError() {
    setMetaError("");
    setError("");
  }

  function openAddClient() {
    setSetupIsNew(true);
    setPage("client_setup");
    setMenuOpen(false);
    setNotice("");
    setError("");
    setMetaError("");
    setMetaChoice(false);
  }

  function openClientSetup(client = null) {
    if (client?.id) {
      chooseClient(client.id);
    }
    setSetupIsNew(false);
    setPage("client_setup");
    setMenuOpen(false);
    setMetaError("");
    setMetaChoice(false);
  }

  function openClientsOverview() {
    setSetupIsNew(false);
    setPage("client_settings");
    setMenuOpen(false);
    setNotice("");
    setError("");
  }

  function openClientDashboard(client) {
    chooseClient(client.id);
    setSetupIsNew(false);
    setSocialTab("all_posts");
    setPage("social_posts");
  }

  async function syncMeta() {
    if (!selected || syncing) return;
    const targetId = selected.id;
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const payload = await api(`/api/clients/${targetId}/posts/fetch`, { method: "POST", body: {} });
      const msg = "Berichten zijn opgehaald en bijgewerkt.";
      setLastSyncMessage(msg);
      setNotice(msg);
      await loadClients();
      await loadTotals(targetId);
    } catch (exc) {
      setError("Het ophalen van berichten is nog niet gelukt. Controleer de koppeling van deze klant.");
      setLastSyncMessage("Ophalen mislukt.");
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
            <ClientSetupPage
              client={selected}
              isNew={false}
              oauthClientId={clientId}
              chooseClient={chooseClient}
              loadClients={loadClients}
              metaChoice={metaChoice}
              metaError={metaError}
              popupReturn
              onMetaReturnHandled={() => setMetaChoice(true)}
              onNotice={setNotice}
              onError={setError}
              onClearMetaError={clearMetaAttemptError}
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
                Klant
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
              <p className="muted">Nog geen klanten aangemaakt.</p>
            )}
            <button
              className="icon-btn add-client-icon"
              type="button"
              title="Nieuwe klant toevoegen"
              aria-label="Nieuwe klant toevoegen"
              onClick={openAddClient}
            >
              +
            </button>
            <button
              className="icon-btn gear-btn"
              type="button"
              title="Alle klanten"
              aria-label="Alle klanten"
              onClick={openClientsOverview}
            >
              ⚙
            </button>
          </div>
          {selected ? (
            <div className="client-active-row">
              <span className="badge badge-active">Actief</span>
              <span className="client-active-name">{selected.name}</span>
            </div>
          ) : (
            <p className="hint">Geen klant geselecteerd. Open Alle klanten via het tandwiel.</p>
          )}
        </div>

        <div className="sidebar-block sync-block">
          <div className="sidebar-title">Synchronisatie</div>
          {!selected ? <p className="muted">Kies eerst een klant.</p> : null}
          {selected && totals && Number(totals.client_id) === Number(selected.id) ? (
            <div className="sync-stats">
              <div>
                <span>Instagram-berichten</span> <strong>{totals.instagram_posts}</strong>
              </div>
              <div>
                <span>Instagram-reacties</span> <strong>{totals.instagram_comments_label}</strong>
              </div>
              <div>
                <span>Facebook-berichten</span> <strong>{totals.facebook_posts}</strong>
              </div>
              <div>
                <span>Facebook-reacties</span> <strong>{totals.facebook_comments_label}</strong>
              </div>
              <div>
                <span>Laatst opgehaald</span> <strong>{totals.synced_at}</strong>
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
            {syncing ? "Berichten ophalen…" : "Berichten ophalen"}
          </button>
          {selected && !fetchAvailable ? (
            <p className="hint">Koppel eerst Facebook en Instagram voor deze klant.</p>
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
            Gebruik het menu links om van klant te wisselen of berichten op te halen — tik op{" "}
            <strong>Menu</strong> op kleinere schermen.
          </div>
          {notice ? <p className="banner">{notice}</p> : null}
          {error ? <p className="banner error">{error}</p> : null}

          {page === "client_setup" ? (
            <ClientSetupPage
              key={setupIsNew ? "setup-new" : selected ? `setup-${selected.id}` : "setup-none"}
              client={setupIsNew ? null : selected}
              isNew={setupIsNew}
              oauthClientId={setupIsNew ? null : clientId}
              chooseClient={(id) => {
                chooseClient(id);
                setSetupIsNew(false);
              }}
              loadClients={loadClients}
              metaChoice={metaChoice}
              metaError={metaError}
              popupReturn={false}
              onMetaReturnHandled={() => setMetaChoice(true)}
              onNotice={setNotice}
              onError={setError}
              onClearMetaError={clearMetaAttemptError}
              onFinished={() => {
                setSetupIsNew(false);
                setNotice("Inrichting afgerond. Je kunt gegevens later via Alle klanten → Bewerken aanpassen.");
                openClientsOverview();
              }}
              onFetchPosts={async () => {
                await syncMeta();                setSocialTab("all_posts");
                openPage("social_posts");
              }}
            />
          ) : null}

          {page === "client_settings" ? (
            <ClientsPage
              clients={clients}
              selectedClientId={selected?.id || null}
              loadClients={loadClients}
              onOpenClient={openClientDashboard}
              onEditClient={openClientSetup}
              onAddClient={openAddClient}
              onDeletedSelected={() => {
                chooseClient(null);
                setPage("client_settings");
              }}
              onNotice={setNotice}
              onError={setError}
            />
          ) : null}

          {!selected && page !== "settings" && page !== "client_settings" && page !== "client_setup" ? (
            <div className="stack">
              <p className="banner">
                Er is geen klant geselecteerd. Open <strong>Alle klanten</strong> via het tandwiel of
                voeg een nieuwe klant toe.
              </p>
              <div className="row-actions">
                <button className="primary" type="button" onClick={openClientsOverview}>
                  Alle klanten
                </button>
                <button className="secondary" type="button" onClick={openAddClient}>
                  Nieuwe klant toevoegen
                </button>
              </div>
            </div>
          ) : null}

          {page === "strategy" && selected ? (
            <StrategyPage
              key={`strategy-${selected.id}`}
              client={selected}
              initialTab={strategyTab}
            />
          ) : null}
          {page === "reports_analysis" && selected ? (
            <ReportsAnalysisPage
              key={`hub-${selected.id}`}
              client={selected}
              onOpenStrategy={() => {
                setStrategyTab("specialist");
                openPage("strategy");
              }}
              onOpenFigmaPlanning={() => {
                setStrategyTab("figma");
                openPage("strategy");
              }}
              onOpenSocialPosts={() => {
                setSocialTab("all_posts");
                openPage("social_posts");
              }}
              onOpenSettings={(tab = "planning") => {
                setSettingsTab(tab);
                openPage("settings");
              }}
            />
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
              onOpenConnect={() => openClientSetup(selected)}
              onOpenCompetitors={() => openPage("comparison")}
              onSynced={async () => {
                await loadClients();
                await loadTotals(selected.id);
              }}
              periodSelection={socialPeriod}
              onPeriodChange={setSocialPeriod}
            />
          ) : null}
          {page === "comparison" && selected ? (
            <ComparisonPage
              key={`cmp-${selected.id}`}
              client={selected}
              onOpenConnect={() => openClientSetup(selected)}
            />
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

    </div>
  );
}
