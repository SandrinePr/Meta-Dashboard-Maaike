import { useEffect, useState } from "react";
import { api } from "../api.js";

function fmt(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString("nl-NL");
  return String(value);
}

function fmtAvg(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("nl-NL", { maximumFractionDigits: 1 });
}

function shortWhen(iso) {
  if (!iso) return "";
  const d = new Date(String(iso).replace("Z", "+00:00"));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("nl-NL", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortStatus(row) {
  if (!row) return "Nog niet";
  if (row.has_fetched_data) {
    const when = shortWhen(row.last_crawled_at);
    return when || "Opgehaald";
  }
  if (row.last_crawl_status === "failed") return "Mislukt";
  return "Nog niet";
}

export default function ComparisonPage({ client }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [adding, setAdding] = useState(false);
  const [competitorInput, setCompetitorInput] = useState("");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  async function reload() {
    const payload = await api(`/api/clients/${client.id}/comparison`);
    setState(payload);
    if (payload.period_start) setCustomStart(payload.period_start);
    if (payload.period_end) setCustomEnd(payload.period_end);
  }

  useEffect(() => {
    setError("");
    setNotice("");
    setState(null);
    reload().catch((exc) => setError(exc.message));
  }, [client.id]);

  async function changePeriod(periodKey) {
    setBusy("period");
    setError("");
    try {
      const body = { period_key: periodKey };
      if (periodKey === "custom") {
        body.custom_start = customStart || null;
        body.custom_end = customEnd || null;
      }
      setState(await api(`/api/clients/${client.id}/comparison/period`, { method: "POST", body }));
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function addCompetitor() {
    setBusy("add");
    setError("");
    setNotice("");
    try {
      const name = competitorInput.trim();
      setState(
        await api(`/api/clients/${client.id}/comparison/competitors`, {
          method: "POST",
          body: { name },
        }),
      );
      setCompetitorInput("");
      setAdding(false);
      setNotice(`@${name.replace(/^@/, "")} toegevoegd`);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function removeCompetitor(username) {
    setBusy(`remove-${username}`);
    setError("");
    try {
      setState(
        await api(`/api/clients/${client.id}/comparison/competitors/${encodeURIComponent(username)}`, {
          method: "DELETE",
        }),
      );
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  async function refreshNow() {
    setBusy("refresh");
    setError("");
    setNotice("Bezig…");
    try {
      const payload = await api(`/api/clients/${client.id}/comparison/competitors/refresh`, {
        method: "POST",
        body: { max_accounts: 3 },
      });
      const n = (payload.crawled || []).length;
      setNotice(
        n
          ? `Opgehaald: ${(payload.crawled || []).map((c) => `@${c.username}`).join(", ")}`
          : "Niets nieuws om op te halen.",
      );
      await reload();
    } catch (exc) {
      setNotice("");
      setError(exc.message || "Ophalen mislukt.");
    } finally {
      setBusy("");
    }
  }

  async function crawlOne(username) {
    const target = String(username || "").trim().replace(/^@/, "");
    if (!target) return;
    setBusy("crawl");
    setError("");
    setNotice(`@${target}…`);
    try {
      await api(`/api/clients/${client.id}/crawl-accounts`, {
        method: "POST",
        body: { name: target },
      });
      const result = await api(
        `/api/clients/${client.id}/crawl-accounts/${encodeURIComponent(target)}/run`,
        { method: "POST", body: { max_pages: 2, page_limit: 25 } },
      );
      setNotice(`@${target}: ${result.posts_saved ?? 0} posts`);
      await reload();
    } catch (exc) {
      setNotice("");
      setError(exc.message);
    } finally {
      setBusy("");
    }
  }

  if (!state) {
    return error ? <p className="banner error">{error}</p> : <p className="muted">Laden…</p>;
  }

  return (
    <div className="stack comparison-page">
      {error ? <p className="banner error">{error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}

      <div className="search-form-header reports-page-header">
        <div>
          <h3 style={{ marginTop: 0 }}>Concurrenten</h3>
          <p className="hint" style={{ margin: 0 }}>
            {state.own_account?.label || "Geen eigen account"}
            {state.period_label ? ` · ${state.period_label}` : ""}
            {" · "}
            {state.schedule?.currently_off_hours ? "auto aan" : "auto na 18:00"}
          </p>
        </div>
        <button className="primary" type="button" disabled={busy === "refresh"} onClick={refreshNow}>
          {busy === "refresh" ? "Bezig…" : "Nu ophalen"}
        </button>
      </div>

      <div className="row-actions wrap" style={{ alignItems: "end" }}>
        <label>
          Periode
          <select
            value={state.period_key}
            disabled={Boolean(busy)}
            onChange={(event) => changePeriod(event.target.value)}
          >
            {state.period_presets.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {state.period_key === "custom" ? (
          <>
            <label>
              Van
              <input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
            </label>
            <label>
              Tot
              <input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
            </label>
            <button className="secondary" type="button" onClick={() => changePeriod("custom")}>
              Toepassen
            </button>
          </>
        ) : null}
      </div>

      <section className="card stack">
        <div className="search-form-header">
          <h3 style={{ marginTop: 0 }}>Lijst · {state.competitors.length}/10</h3>
          {!adding ? (
            <button
              className="secondary"
              type="button"
              disabled={state.competitors.length >= 10}
              onClick={() => setAdding(true)}
            >
              + Toevoegen
            </button>
          ) : null}
        </div>

        {adding ? (
          <div className="row-actions wrap">
            <label>
              @gebruikersnaam
              <input
                value={competitorInput}
                onChange={(e) => setCompetitorInput(e.target.value)}
                placeholder="@account"
              />
            </label>
            <button className="primary" type="button" disabled={busy === "add"} onClick={addCompetitor}>
              Opslaan
            </button>
            <button className="secondary" type="button" onClick={() => setAdding(false)}>
              Annuleren
            </button>
          </div>
        ) : null}

        {!state.competitors.length ? <p className="hint">Nog geen concurrenten.</p> : null}

        <div className="report-list stack">
          {state.competitors.map((name) => {
            const row = (state.account_rows || []).find((r) => r.username === name);
            return (
              <div className="report-list-row" key={name}>
                <div className="report-list-main">
                  <span className="report-list-title">@{name}</span>
                  <div className="report-list-meta">
                    <span className="hint">{shortStatus(row)}</span>
                    {row?.followers != null ? (
                      <span className="hint">{fmt(row.followers)} volgers</span>
                    ) : null}
                  </div>
                </div>
                <div className="report-list-actions">
                  <button
                    className="secondary"
                    type="button"
                    disabled={busy === "crawl"}
                    onClick={() => crawlOne(name)}
                  >
                    Opnieuw
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    disabled={busy === `remove-${name}`}
                    onClick={() => removeCompetitor(name)}
                  >
                    Weg
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Prestaties</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Volgers</th>
                <th>Posts</th>
                <th>Likes Ø</th>
                <th>Comments Ø</th>
              </tr>
            </thead>
            <tbody>
              {(state.account_rows || []).map((row) => (
                <tr key={`${row.role}-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                  </td>
                  <td>{row.has_fetched_data ? fmt(row.followers) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.posts_in_period) : "—"}</td>
                  <td>{row.has_fetched_data ? fmtAvg(row.likes_avg) : "—"}</td>
                  <td>{row.has_fetched_data ? fmtAvg(row.comments_avg) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Contentmix</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Reels</th>
                <th>Images</th>
                <th>Carrousels</th>
                <th>Video</th>
              </tr>
            </thead>
            <tbody>
              {(state.content_rows || []).map((row) => (
                <tr key={`content-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                  </td>
                  <td>{row.has_fetched_data ? fmt(row.reels) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.images) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.carousels) : "—"}</td>
                  <td>{row.has_fetched_data ? fmt(row.other_videos) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card stack">
        <h3 style={{ marginTop: 0 }}>Groei</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Start</th>
                <th>Eind</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              {(state.growth_rows || []).map((row) => (
                <tr key={`growth-${row.username}`}>
                  <td>
                    <strong>{row.display_name}</strong>
                  </td>
                  <td>{fmt(row.followers_start)}</td>
                  <td>{fmt(row.followers_end)}</td>
                  <td>{fmt(row.followers_delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

    </div>
  );
}
