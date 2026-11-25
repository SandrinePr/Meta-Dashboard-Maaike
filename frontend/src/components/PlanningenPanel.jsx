import { useEffect, useState } from "react";
import { api } from "../api.js";

const STORAGE_KEY = "hamster-planning-order";
const DEFAULT_ORDER = ["posts", "competitors", "trend"];

function loadOrder() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(raw)) return [...DEFAULT_ORDER];
    const known = raw.filter((id) => DEFAULT_ORDER.includes(id));
    for (const id of DEFAULT_ORDER) {
      if (!known.includes(id)) known.push(id);
    }
    return known;
  } catch {
    return [...DEFAULT_ORDER];
  }
}

/**
 * The three existing schedules: post check, competitor check, monthly trend.
 * Order is stored in this browser.
 */
export default function PlanningenPanel({ client }) {
  const [order, setOrder] = useState(loadOrder);
  const [open, setOpen] = useState({ posts: true, competitors: false, trend: false });
  const [posts, setPosts] = useState(null);
  const [competitors, setCompetitors] = useState(null);
  const [trend, setTrend] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
  }, [order]);

  useEffect(() => {
    if (!client?.id) return undefined;
    let cancelled = false;
    setError("");
    Promise.all([
      api(`/api/clients/${client.id}/logs/weekly-plan`).catch(() => null),
      api(`/api/clients/${client.id}/comparison/schedule`).catch(() => null),
      api("/api/report-planning/monthly-trend").catch(() => null),
    ]).then(([postPlan, compPlan, trendPlan]) => {
      if (cancelled) return;
      setPosts(postPlan?.weekly_plan || postPlan || null);
      setCompetitors(compPlan?.weekly_plan || compPlan || null);
      setTrend(trendPlan);
    }).catch(() => {
      if (!cancelled) setError("Planningen laden is niet gelukt.");
    });
    return () => {
      cancelled = true;
    };
  }, [client?.id]);

  function move(id, direction) {
    setOrder((current) => {
      const next = [...current];
      const index = next.indexOf(id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= next.length) return current;
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
  }

  const cards = {
    posts: {
      title: "Berichtencontrole",
      when: posts?.enabled
        ? `${posts.weekday_label || "Vaste dag"} om ${posts.time || "—"}`
        : "Nog geen vaste dag",
      who: posts?.responsible_name || "Nog geen verantwoordelijke",
      mode: "Handmatig afronden. HAMSTER plant het moment, jij rondt de controle af.",
    },
    competitors: {
      title: "Concurrentencontrole",
      when: competitors?.enabled
        ? `${competitors.weekday_label || competitors.next_label || "Vaste dag"} om ${competitors.time || "—"}`
        : "Nog geen vaste dag",
      who: competitors?.responsible_name || "Nog geen verantwoordelijke",
      mode: "Ophalen kan automatisch buiten werktijd. De controle zelf doe je handmatig.",
    },
    trend: {
      title: "Algemeen trendrapport",
      when: trend?.next_run?.label_nl || "1e van de maand om 06:00 (Nederlandse tijd)",
      who: "HAMSTER (geen persoon)",
      mode: trend?.production_schedule_active
        ? "Automatisch, productie staat aan."
        : "Alleen simulatie. Productie staat uit, er wordt nog geen echt rapport aangemaakt.",
    },
  };

  return (
    <section className="card stack" aria-label="Planningen">
      <h3 style={{ marginTop: 0 }}>Planningen</h3>
      <p className="hint">
        Drie planningen voor {client?.name || "deze klant"}. Klap een onderdeel open. De volgorde
        blijft bewaard na verversen.
      </p>
      {error ? <p className="banner error">{error}</p> : null}
      {order.map((id) => {
        const card = cards[id];
        if (!card) return null;
        return (
          <article key={id} className="card stack" style={{ margin: 0 }}>
            <div className="row-actions wrap" style={{ justifyContent: "space-between" }}>
              <button type="button" className="linkish" onClick={() => setOpen((current) => ({ ...current, [id]: !current[id] }))}>
                {open[id] ? "Verberg" : "Toon"} {card.title}
              </button>
              <span className="row-actions">
                <button type="button" className="secondary" onClick={() => move(id, -1)}>Omhoog</button>
                <button type="button" className="secondary" onClick={() => move(id, 1)}>Omlaag</button>
              </span>
            </div>
            {open[id] ? (
              <ul className="plain-list">
                <li>Wanneer: {card.when}</li>
                <li>Verantwoordelijke: {card.who}</li>
                <li>Automatisch of handmatig: {card.mode}</li>
              </ul>
            ) : (
              <p className="hint" style={{ margin: 0 }}>{card.when} · {card.mode}</p>
            )}
          </article>
        );
      })}
    </section>
  );
}
