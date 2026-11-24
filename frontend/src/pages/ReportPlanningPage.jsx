import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const FETCH_LABEL = {
  updated: "Posts/cijfers ok",
  partial: "Deels beschikbaar",
  failed: "Nog geen bruikbare data",
  pending: "Nog niet bekeken",
};

function isJunkTestName(name) {
  const n = String(name || "").toLowerCase();
  return n.startsWith("qa planning") || n === "qa controle" || n === "klant debug";
}

function addMinutes(hhmm, minutes) {
  const [h, m] = String(hhmm || "09:00").split(":").map(Number);
  const total = h * 60 + m + Number(minutes || 0);
  const wrapped = ((total % (24 * 60)) + 24 * 60) % (24 * 60);
  const nh = Math.floor(wrapped / 60);
  const nm = wrapped % 60;
  return `${String(nh).padStart(2, "0")}:${String(nm).padStart(2, "0")}`;
}

export default function ReportPlanningPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [draft, setDraft] = useState(null);
  const [showMore, setShowMore] = useState(false);
  const [simYear, setSimYear] = useState(() => new Date().getFullYear());
  const [simMonth, setSimMonth] = useState(() => new Date().getMonth() + 1);
  const [simResult, setSimResult] = useState(null);

  function buildDraft(payload) {
    const clients = (payload.clients || []).filter((c) => !isJunkTestName(c.name));
    const byId = new Map(clients.map((c) => [c.id, c]));
    let slots = (payload.plan.client_slots || [])
      .map((s) => ({
        client_id: s.client_id,
        time: s.time,
        name: byId.get(s.client_id)?.name,
      }))
      .filter((s) => s.name);
    if (!slots.length) {
      slots = (payload.schedule || [])
        .map((s) => ({ client_id: s.client_id, time: s.time, name: s.name }))
        .filter((s) => byId.has(s.client_id));
    }
    return {
      plan: payload.plan,
      clients,
      slots,
    };
  }

  async function reload() {
    const payload = await api("/api/report-planning");
    setData(payload);
    setDraft(buildDraft(payload));
  }

  useEffect(() => {
    reload().catch((exc) => setError(exc.message));
  }, []);

  const scheduledIds = useMemo(
    () => new Set((draft?.slots || []).map((s) => s.client_id)),
    [draft],
  );

  const availableToAdd = useMemo(
    () => (draft?.clients || []).filter((c) => !scheduledIds.has(c.id)),
    [draft, scheduledIds],
  );

  function setSlotTime(clientId, time) {
    setDraft((prev) => ({
      ...prev,
      slots: prev.slots.map((s) => (s.client_id === clientId ? { ...s, time } : s)),
    }));
  }

  function removeSlot(clientId) {
    setDraft((prev) => ({
      ...prev,
      slots: prev.slots.filter((s) => s.client_id !== clientId),
    }));
  }

  function moveSlot(clientId, dir) {
    setDraft((prev) => {
      const slots = [...prev.slots];
      const idx = slots.findIndex((s) => s.client_id === clientId);
      const j = idx + dir;
      if (idx < 0 || j < 0 || j >= slots.length) return prev;
      [slots[idx], slots[j]] = [slots[j], slots[idx]];
      return { ...prev, slots };
    });
  }

  function addClient(clientId) {
    const client = draft.clients.find((c) => c.id === clientId);
    if (!client) return;
    setDraft((prev) => {
      const last = prev.slots[prev.slots.length - 1];
      const interval = Number(prev.plan.interval_minutes || 60);
      const time = last
        ? addMinutes(last.time, interval)
        : prev.plan.start_time || "09:00";
      return {
        ...prev,
        slots: [...prev.slots, { client_id: client.id, name: client.name, time }],
      };
    });
  }

  function applyPauseFromFirst() {
    const interval = Number(draft.plan.interval_minutes || 60);
    setDraft((prev) => {
      if (!prev.slots.length) return prev;
      const first = prev.slots[0].time || "09:00";
      return {
        ...prev,
        slots: prev.slots.map((s, idx) => ({
          ...s,
          time: idx === 0 ? first : addMinutes(first, interval * idx),
        })),
      };
    });
  }

  async function savePlan() {
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const slots = draft.slots.map((s) => ({ client_id: s.client_id, time: s.time }));
      const payload = await api("/api/report-planning", {
        method: "PUT",
        body: {
          name: draft.plan.name || "Maandelijkse klantrapporten",
          schedule_kind: draft.plan.schedule_kind,
          once_date: draft.plan.once_date || null,
          recurring_rule: draft.plan.recurring_rule,
          start_time: slots[0]?.time || draft.plan.start_time,
          interval_minutes: Number(draft.plan.interval_minutes),
          period_mode: draft.plan.period_mode,
          period_year: draft.plan.period_year ? Number(draft.plan.period_year) : null,
          period_month: draft.plan.period_month ? Number(draft.plan.period_month) : null,
          client_ids: slots.map((s) => s.client_id),
          client_slots: slots,
          include_trend_report: Boolean(draft.plan.include_trend_report),
          shared_trend_report_id: draft.plan.shared_trend_report_id || null,
          retry_max: Number(draft.plan.retry_max ?? 2),
          retry_wait_seconds: Number(draft.plan.retry_wait_seconds ?? 120),
          cost_limit_usd: Number(draft.plan.cost_limit_usd ?? 25),
          auto_execute: false,
        },
      });
      setData(payload);
      setDraft(buildDraft(payload));
      setNotice("Globale planning opgeslagen — hetzelfde voor elke klant die je links kiest.");
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function simulateMonthlyTrend() {
    setBusy("sim_trend");
    setError("");
    setNotice("");
    try {
      const res = await api("/api/report-planning/monthly-trend/simulate", {
        method: "POST",
        body: {
          year: Number(simYear),
          month: Number(simMonth),
          simulate_without_paid_ai: true,
        },
      });
      setSimResult(res);
      setNotice(
        res.created
          ? `Simulatie geslaagd: '${res.title}' is aangemaakt en opgeslagen in het dashboard (zonder betaalde AI-run).`
          : `Geen dubbel rapport aangemaakt: '${res.title}' bestond al voor deze maand (idempotent gecontroleerd).`
      );
      await reload();
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  if (!data || !draft) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Laden…</p>;
  }

  const trendSched = data.monthly_trend_schedule || {};
  const trendRuns = trendSched.recent_runs || [];
  const nextDate = data?.suggested_dates?.[0];
  const lastRun = data.last_run;
  const lastRunClients = (lastRun?.clients || []).filter((row) => !isJunkTestName(row.client_name));
  const example =
    draft.slots.length >= 2
      ? `${draft.slots[0].name} om ${draft.slots[0].time}, daarna ${draft.slots[1].name} om ${draft.slots[1].time}`
      : draft.slots.length === 1
        ? `${draft.slots[0].name} om ${draft.slots[0].time}`
        : "nog geen klanten in de planning";

  return (
    <div className="stack">
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      <section className="card stack">
        <div className="search-form-header">
          <h3 style={{ marginTop: 0, marginBottom: 0 }}>
            Automatisch algemeen trendrapport (1e van de maand)
          </h3>
          <span className="pill ok">Actief · {trendSched.timezone || "Europe/Amsterdam"}</span>
        </div>
        <p style={{ margin: 0, lineHeight: 1.55 }}>
          Op de <strong>1e van iedere maand om 06:00 uur</strong> ({trendSched.timezone || "Europe/Amsterdam"})
          maakt HAMSTER automatisch één zelfstandig <strong>Algemeen trendrapport</strong> over trends per
          socialmediakanaal en bewaart dit in het dashboard. Een herstart of nieuwe poging maakt geen
          dubbele rapporten aan.
        </p>
        {trendSched.next_run?.label_nl ? (
          <p className="hint" style={{ margin: 0 }}>
            Eerstvolgende automatische run: <strong>{trendSched.next_run.label_nl}</strong>.
          </p>
        ) : null}

        <div className="row-actions wrap" style={{ alignItems: "end" }}>
          <label>
            Simulatiemaand
            <select value={String(simMonth)} onChange={(e) => setSimMonth(Number(e.target.value))}>
              {[
                [1, "januari"],
                [2, "februari"],
                [3, "maart"],
                [4, "april"],
                [5, "mei"],
                [6, "juni"],
                [7, "juli"],
                [8, "augustus"],
                [9, "september"],
                [10, "oktober"],
                [11, "november"],
                [12, "december"],
              ].map(([m, label]) => (
                <option key={m} value={m}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Jaar
            <input
              type="number"
              min={2024}
              max={2035}
              value={simYear}
              onChange={(e) => setSimYear(Number(e.target.value) || 2026)}
              style={{ width: "6.5rem" }}
            />
          </label>
          <button
            className="secondary"
            type="button"
            disabled={Boolean(busy)}
            onClick={simulateMonthlyTrend}
          >
            {busy === "sim_trend"
              ? "Simuleren…"
              : "Test 1e-van-de-maand planning (zonder betaalde AI)"}
          </button>
        </div>

        {simResult ? (
          <p className="hint" style={{ margin: 0 }}>
            Laatste simulatie: rapport #{simResult.report_id} ({simResult.title}) ·{" "}
            {simResult.created ? "nieuw aangemaakt" : "bestaand rapport behouden (geen duplicaat)"} ·
            tijdzone {simResult.timezone}.
          </p>
        ) : null}

        {trendRuns.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Maand</th>
                  <th>Rapport</th>
                  <th>Status</th>
                  <th>Laatste controle ({trendSched.timezone || "Europe/Amsterdam"})</th>
                </tr>
              </thead>
              <tbody>
                {trendRuns.slice(0, 5).map((r) => (
                  <tr key={`${r.period_year}-${r.period_month}`}>
                    <td>
                      <strong>
                        {String(r.period_month).padStart(2, "0")}-{r.period_year}
                      </strong>
                    </td>
                    <td>{r.report_title || `#${r.report_id}`}</td>
                    <td>{r.report_status || r.status}</td>
                    <td>{r.last_checked_at || r.triggered_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Eén planning voor alle klanten</h3>
        <p style={{ margin: 0, lineHeight: 1.55 }}>
          Hier plan je <strong>iedereen</strong> in — niet per klant apart. Wissel je links van Red Rock
          naar Test1, dan blijft dit schema hetzelfde.
        </p>
        <p className="hint" style={{ margin: 0 }}>
          Pauze tussen klanten = hun starttijden. Voorbeeld nu: <strong>{example}</strong>.
          Claude mag overdag; automatisch starten staat nog uit.
        </p>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Dag &amp; rapportperiode</h3>
        <div className="row-actions wrap" style={{ alignItems: "end" }}>
          <label>
            Hoe vaak
            <select
              value={draft.plan.schedule_kind}
              onChange={(e) =>
                setDraft({ ...draft, plan: { ...draft.plan, schedule_kind: e.target.value } })
              }
            >
              <option value="recurring">Elke maand (voorstel: laatste zondag)</option>
              <option value="once">Eén vaste datum</option>
            </select>
          </label>
          {draft.plan.schedule_kind === "once" ? (
            <label>
              Datum
              <input
                type="date"
                value={draft.plan.once_date || ""}
                onChange={(e) =>
                  setDraft({ ...draft, plan: { ...draft.plan, once_date: e.target.value } })
                }
              />
            </label>
          ) : null}
          <label>
            Standaard pauze (voor nieuwe klanten / herberekenen)
            <select
              value={String(draft.plan.interval_minutes)}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  plan: { ...draft.plan, interval_minutes: e.target.value },
                })
              }
            >
              <option value="30">30 minuten</option>
              <option value="60">1 uur</option>
              <option value="90">1,5 uur</option>
              <option value="120">2 uur</option>
            </select>
          </label>
          <label>
            Rapport over
            <select
              value={draft.plan.period_mode}
              onChange={(e) =>
                setDraft({ ...draft, plan: { ...draft.plan, period_mode: e.target.value } })
              }
            >
              <option value="previous_calendar_month">Vorige kalendermaand</option>
              <option value="fixed_month">Zelf een maand kiezen</option>
            </select>
          </label>
        </div>
        {draft.plan.schedule_kind === "recurring" && nextDate ? (
          <p className="hint" style={{ margin: 0 }}>
            Volgende voorsteldatum: <strong>{nextDate.label}</strong> (later definitief te maken).
          </p>
        ) : null}
      </section>

      <section className="card stack">
        <div className="search-form-header">
          <h3 style={{ marginTop: 0 }}>Tijdschema per klant</h3>
          {draft.slots.length > 1 ? (
            <button className="secondary" type="button" onClick={applyPauseFromFirst}>
              Herbereken vanaf eerste + pauze
            </button>
          ) : null}
        </div>
        <p className="hint" style={{ margin: 0 }}>
          Zet hier bv. Red Rock op 12:00 en Test1 op 13:00. Volgorde = volgorde in de wachtrij.
        </p>

        {!draft.slots.length ? <p className="hint">Nog niemand ingepland. Voeg hieronder een klant toe.</p> : null}

        <div className="report-list stack">
          {draft.slots.map((slot, idx) => (
            <div className="report-list-row" key={slot.client_id}>
              <div className="report-list-main">
                <span className="report-list-title">
                  {idx + 1}. {slot.name}
                </span>
                <div className="report-list-meta">
                  <label style={{ margin: 0 }}>
                    Starttijd
                    <input
                      type="time"
                      value={slot.time}
                      onChange={(e) => setSlotTime(slot.client_id, e.target.value)}
                    />
                  </label>
                </div>
              </div>
              <div className="report-list-actions">
                <button className="secondary" type="button" onClick={() => moveSlot(slot.client_id, -1)}>
                  Omhoog
                </button>
                <button className="secondary" type="button" onClick={() => moveSlot(slot.client_id, 1)}>
                  Omlaag
                </button>
                <button className="secondary" type="button" onClick={() => removeSlot(slot.client_id)}>
                  Weg
                </button>
              </div>
            </div>
          ))}
        </div>

        {availableToAdd.length ? (
          <label>
            Klant toevoegen aan dit schema
            <select
              defaultValue=""
              onChange={(e) => {
                const id = Number(e.target.value);
                if (id) addClient(id);
                e.target.value = "";
              }}
            >
              <option value="">Kies een klant…</option>
              {availableToAdd.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="hint">Alle beschikbare klanten staan al in het schema.</p>
        )}
      </section>

      <div className="row-actions wrap">
        <button className="primary" type="button" disabled={Boolean(busy)} onClick={savePlan}>
          {busy === "save" ? "Opslaan…" : "Planning opslaan"}
        </button>
        <button className="secondary" type="button" onClick={() => setShowMore((v) => !v)}>
          {showMore ? "Minder details" : "Meer opties"}
        </button>
      </div>

      {showMore ? (
        <section className="card stack">
          <h3 style={{ marginTop: 0 }}>Meer opties</h3>
          <label className="row-actions" style={{ gap: "0.5rem", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={Boolean(draft.plan.include_trend_report)}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  plan: { ...draft.plan, include_trend_report: e.target.checked },
                })
              }
            />
            Zelfde trendrapport hergebruiken voor alle klanten
          </label>
          <p className="hint" style={{ margin: 0 }}>
            {(data.server_runtime || {}).summary}
          </p>
        </section>
      ) : null}

      {lastRun && lastRunClients.length ? (
        <section className="card stack">
          <h3 style={{ marginTop: 0 }}>Laatste controle</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Klant</th>
                  <th>Gepland</th>
                  <th>Data</th>
                  <th>Concept</th>
                </tr>
              </thead>
              <tbody>
                {lastRunClients.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.client_name}</strong>
                    </td>
                    <td>{(row.scheduled_at || "").slice(11, 16) || "—"}</td>
                    <td>{FETCH_LABEL[row.fetch_status] || row.fetch_status}</td>
                    <td>
                      {row.report_status === "prepared"
                        ? "Klaar om te bekijken"
                        : row.report_status || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
