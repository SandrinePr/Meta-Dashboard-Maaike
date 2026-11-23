import { useState } from "react";
import { api } from "../api.js";

const DELETE_KINDS = [
  "klantnaam en klantrecord",
  "Meta-koppeling en tokens",
  "posts, comments en media",
  "strategie, doelen en Canva-gegevens",
  "Figma-koppeling en planningitems",
  "legenda (formats, pillars, hooks)",
  "rapporten en reviews",
  "concurrenten en crawl-accounts",
  "AI-analyses en proefruns",
  "activiteitenlog voor deze klant",
];

export default function ClientsPage({
  clients = [],
  selectedClientId = null,
  loadClients,
  onOpenClient,
  onEditClient,
  onAddClient,
  onDeletedSelected,
  onNotice,
  onError,
}) {
  const [confirmClient, setConfirmClient] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [localError, setLocalError] = useState("");

  async function confirmDelete() {
    if (!confirmClient) return;
    const target = confirmClient;
    setLocalError("");
    onError("");
    setBusyId(target.id);
    try {
      const payload = await api(`/api/clients/${target.id}`, { method: "DELETE" });
      setConfirmClient(null);
      const remaining = await loadClients();
      onNotice(payload.message || `Klant “${target.name}” is verwijderd.`);
      if (selectedClientId === target.id) {
        onDeletedSelected?.(remaining || []);
      }
    } catch (exc) {
      const message =
        exc.message ||
        "De klant kon niet worden verwijderd. Controleer de verbinding en probeer opnieuw.";
      setLocalError(message);
      onError(message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack clients-overview">
      <div className="page-toolbar">
        <div>
          <h3>Alle klanten</h3>
          <p className="hint">
            Open een klant voor het dashboard, bewerk de inrichting, of verwijder een klant. Het
            tandwiel opent altijd dit overzicht.
          </p>
        </div>
        <button className="primary" type="button" onClick={onAddClient}>
          Nieuwe klant toevoegen
        </button>
      </div>

      {localError ? <p className="banner error">{localError}</p> : null}

      {!clients.length ? (
        <div className="card stack">
          <p className="banner">Er zijn nog geen klanten</p>
          <p className="hint">Voeg een klant toe om Meta te koppelen en het dashboard te gebruiken.</p>
          <button className="primary" type="button" onClick={onAddClient}>
            Nieuwe klant toevoegen
          </button>
        </div>
      ) : (
        <ul className="client-list">
          {clients.map((item) => {
            const isSelected = selectedClientId === item.id;
            const connected = Boolean(item.connected);
            return (
              <li key={item.id} className={`client-list-item${isSelected ? " is-selected" : ""}`}>
                <div className="client-list-main">
                  <strong>{item.name}</strong>
                  <span className="muted">
                    {connected
                      ? `Gekoppeld${item.page_name ? ` · ${item.page_name}` : ""}${
                          item.ig_username ? ` · @${item.ig_username}` : ""
                        }`
                      : "Nog niet gekoppeld"}
                    {isSelected ? " · geselecteerd" : ""}
                  </span>
                </div>
                <div className="row-actions client-list-actions">
                  <button className="primary" type="button" onClick={() => onOpenClient(item)}>
                    Openen
                  </button>
                  <button className="secondary" type="button" onClick={() => onEditClient(item)}>
                    Bewerken
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busyId === item.id}
                    onClick={() => {
                      setLocalError("");
                      setConfirmClient(item);
                    }}
                  >
                    Verwijderen
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {confirmClient ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setConfirmClient(null)}>
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-client-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-client-title">Klant verwijderen?</h2>
            <p>
              Je staat op het punt om <strong>{confirmClient.name}</strong> te verwijderen.
            </p>
            <p className="hint">
              Dit verwijdert alleen gegevens van deze klant. Andere klanten blijven onaangeroerd.
              Globale promptinstellingen blijven bewaard.
            </p>
            <p>
              <strong>Wordt verwijderd:</strong>
            </p>
            <ul className="plain-list">
              {DELETE_KINDS.map((kind) => (
                <li key={kind}>{kind}</li>
              ))}
            </ul>
            <div className="row-actions">
              <button
                className="secondary"
                type="button"
                disabled={busyId === confirmClient.id}
                onClick={() => setConfirmClient(null)}
              >
                Annuleren
              </button>
              <button
                className="primary"
                type="button"
                disabled={busyId === confirmClient.id}
                onClick={confirmDelete}
              >
                {busyId === confirmClient.id ? "Bezig…" : `Verwijder ${confirmClient.name}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
