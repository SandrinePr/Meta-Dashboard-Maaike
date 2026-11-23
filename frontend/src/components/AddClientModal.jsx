import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export default function AddClientModal({ open, onClose, onCreated, onError }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setLocalError("");
    const timer = window.setTimeout(() => inputRef.current?.focus(), 50);
    return () => window.clearTimeout(timer);
  }, [open]);

  if (!open) return null;

  async function submit(event) {
    event.preventDefault();
    setLocalError("");
    onError?.("");
    setSaving(true);
    try {
      const created = await api("/api/clients", { method: "POST", body: { name } });
      setName("");
      onCreated(created);
      onClose();
    } catch (exc) {
      setLocalError(exc.message);
      onError?.(exc.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-client-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="add-client-title">Klant toevoegen</h2>
        <p className="hint">
          Tip: gebruik liever <strong>Klant inrichten</strong> voor de stapsgewijze route. Hier maak je
          alleen snel een naam aan.
        </p>
        <form className="stack" onSubmit={submit}>
          <label>
            Klantnaam
            <input
              ref={inputRef}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={saving}
              required
              autoComplete="organization"
            />
          </label>
          {localError ? <p className="banner error">{localError}</p> : null}
          <div className="row-actions">
            <button className="secondary" type="button" onClick={onClose} disabled={saving}>
              Annuleren
            </button>
            <button className="primary" type="submit" disabled={saving || !name.trim()}>
              {saving ? "Bezig…" : "Klant toevoegen"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
