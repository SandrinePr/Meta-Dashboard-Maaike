import { useEffect, useState } from "react";
import { api } from "../api.js";
import { buildNextStep } from "../nextStep.js";

/**
 * Single concrete follow-up at the top of the daily dashboard.
 */
export default function NextStepBanner({
  client,
  role,
  channelStatus,
  syncing = false,
  onOpenSetup,
  onFetchPosts,
  onOpenResults,
  onOpenPosts,
  onOpenReports,
}) {
  const [strategy, setStrategy] = useState(null);

  useEffect(() => {
    if (!client?.id) {
      setStrategy(null);
      return undefined;
    }
    let cancelled = false;
    api(`/api/clients/${client.id}/strategy`)
      .then((payload) => {
        if (!cancelled) setStrategy(payload);
      })
      .catch(() => {
        if (!cancelled) setStrategy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client?.id]);

  if (!client) return null;

  const step = buildNextStep({
    role,
    clientName: client.name,
    channelStatus,
    strategy,
  });

  const toneClass =
    step.tone === "warn"
      ? "next-step-banner is-warn"
      : step.tone === "info"
        ? "next-step-banner is-info"
        : step.tone === "ok"
          ? "next-step-banner is-ok"
          : "next-step-banner";

  function runAction() {
    if (step.action === "setup") onOpenSetup?.();
    else if (step.action === "fetch") onFetchPosts?.();
    else if (step.action === "results") onOpenResults?.();
    else if (step.action === "posts") onOpenPosts?.();
    else if (step.action === "reports") onOpenReports?.();
  }

  return (
    <section className={toneClass} aria-label="Vervolgstap">
      <div className="next-step-copy">
        <p className="next-step-kicker">Vervolgstap</p>
        <strong className="next-step-title">{step.title}</strong>
        <p className="next-step-body">{step.body}</p>
      </div>
      {step.action && step.label ? (
        <button
          className="primary"
          type="button"
          disabled={step.action === "fetch" && syncing}
          onClick={runAction}
        >
          {step.action === "fetch" && syncing ? "Bezig…" : step.label}
        </button>
      ) : null}
    </section>
  );
}
