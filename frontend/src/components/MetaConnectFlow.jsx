/** Facebook/Instagram-koppeling voor klantinrichting en klantinstellingen. */

import { META_LINKING_LABEL, metaAttemptBanner } from "../metaLoginDisplay.js";

export default function MetaConnectFlow({
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
  compact = false,
  linkPhase = "idle",
  attemptError = "",
  metaError = "",
}) {
  const pages = meta.pages;
  const choosing = Boolean(pages);
  const connected = Boolean(meta.connected);
  const linking = linkPhase === "linking" || busy === "start";
  const banner = metaAttemptBanner({
    linkPhase: linking ? "linking" : linkPhase,
    attemptError,
    metaError: linking ? "" : metaError,
    statusDetail: linking || attemptError ? "" : meta.status_detail,
    statusLabel: meta.status_label,
    connected,
  });

  if (connected && !choosing) {
    return (
      <section className="card stack meta-step">
        {!compact ? <p className="step-label">Stand</p> : null}
        <h3>Gekoppeld</h3>
        <p className="status setup-status is-ready">Klaar</p>
        {meta.page_name ? (
          <p>
            <strong>Facebook-pagina:</strong> {meta.page_name}
            {meta.ig_username ? (
              <>
                <br />
                <strong>Instagram:</strong> @{meta.ig_username}
              </>
            ) : null}
          </p>
        ) : null}
        <p className="hint">
          De accounts zijn echt gekoppeld. Alleen een klant selecteren in de zijbalk is nog geen
          koppeling.
        </p>
        <div className="row-actions">
          {onFetchPosts ? (
            <button className="primary" type="button" onClick={onFetchPosts}>
              Berichten ophalen
            </button>
          ) : null}
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onRecheck}>
            {busy === "recheck" ? "Bezig…" : "Koppeling controleren"}
          </button>
          <button className="secondary" type="button" disabled={!meta.ready || Boolean(busy)} onClick={onStart}>
            Opnieuw koppelen
          </button>
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onDisconnect}>
            Ontkoppelen
          </button>
        </div>
      </section>
    );
  }

  if (choosing) {
    const selectable = pages.selectable || [];
    const blocked = pages.blocked || [];
    return (
      <section className="card stack meta-step">
        {!compact ? <p className="step-label">Accounts kiezen</p> : null}
        <h3>Kies de accounts voor {client.name}</h3>
        <p className="hint">
          Kies de Facebook-pagina met het professionele Instagram-account van deze klant. Andere
          klanten blijven ongewijzigd.
        </p>
        <p className="setup-status is-review">Controleren</p>
        {pages.empty ? (
          <p className="banner">Meta gaf geen Facebook-pagina terug die dit account mag beheren.</p>
        ) : null}
        {!selectable.length && !pages.empty ? (
          <p className="banner">
            Geen pagina met een professioneel Instagram-account. Controleer de rechten in Meta
            Business Suite en probeer opnieuw.
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
                <span className="account-card-text">
                  <strong className="account-card-name">{page.page_name}</strong>
                  <span className="muted account-card-handle">
                    {page.ig_username ? `@${page.ig_username}` : "Instagram-account"}
                  </span>
                </span>
              </label>
            ))}
          </div>
        ) : null}
        {blocked.length ? (
          <div className="banner">
            <strong>Niet beschikbaar</strong>
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
            {busy === "confirm" ? "Bezig…" : "Deze koppeling bevestigen"}
          </button>
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onCancel}>
            Annuleren
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className={`card stack meta-step${highlightConnect ? " is-highlight" : ""}`}>
      {!compact ? <p className="step-label">Koppelen</p> : null}
      <h3>Facebook en Instagram koppelen</h3>
      <p className={`setup-status ${linking ? "is-review" : "is-todo"}`}>
        {linking ? "Bezig met koppelen" : "Nog koppelen"}
      </p>
      {banner ? (
        <p className={banner.kind === "progress" ? "banner" : banner.kind === "ok" ? "status" : "banner error"}>
          {banner.text}
        </p>
      ) : null}
      {(meta.page_name || meta.ig_username) && !meta.connected && !linking ? (
        <p>
          <strong>Laatst gekoppeld:</strong> {meta.page_name || "Facebook-pagina"}
          {meta.ig_username ? <> · Instagram @{meta.ig_username}</> : null}
        </p>
      ) : null}
      <p>
        Log in bij Meta en kies de accounts voor <strong>{client.name}</strong>. Zo mag HAMSTER posts
        en statistieken ophalen.
      </p>
      <p className="hint">
        HAMSTER vraagt nooit om je Facebook-wachtwoord. Het inloggen gebeurt op de site van Meta.
      </p>
      {!linking
        ? (meta.missing || []).map((item) => (
            <p key={item} className="banner error">
              {item}
            </p>
          ))
        : null}
      {!meta.ready ? (
        <p className="banner warn-soft">
          Meta-login is nog niet klaar (app-instellingen ontbreken). Controleer de technische
          Meta-instellingen. Je kunt wel al de klantnaam en andere gegevens invullen.
        </p>
      ) : null}
      <div className="row-actions">
        <button className="facebook-login" type="button" disabled={!meta.ready || Boolean(busy)} onClick={onStart}>
          <span className="facebook-f" aria-hidden="true">
            f
          </span>
          <span>{linking ? META_LINKING_LABEL : "Doorgaan met Facebook"}</span>
        </button>
        {(meta.page_name || meta.ig_username || meta.connected) && (
          <button className="secondary" type="button" disabled={Boolean(busy)} onClick={onDisconnect}>
            Ontkoppelen
          </button>
        )}
      </div>
      {sameTabUrl || onSameTabHref ? (
        <div className="banner">
          <p>Pop-up geblokkeerd? Ga verder in dit tabblad.</p>
          <button className="secondary" type="button" onClick={onSameTab}>
            Doorgaan in dit tabblad
          </button>
        </div>
      ) : null}
      <p className="hint">
        Mislukt de koppeling? Je gegevens hierboven blijven bewaard. Probeer opnieuw of controleer
        of je de juiste Facebook-pagina mag beheren.
      </p>
    </section>
  );
}
