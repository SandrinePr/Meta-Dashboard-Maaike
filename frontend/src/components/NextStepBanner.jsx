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
  channelLoading = false,
  channelError = null,
  syncing = false,
  onOpenSetup,
  onFetchPosts,
  onOpenResults,
  onOpenPosts,
  onOpenReports,
}) {
  const [strategy, setStrategy] = useState(null);
  const [strategyDone, setStrategyDone] = useState(false);

  useEffect(() => {
    if (!client?.id) {
      setStrategy(null);
      setStrategyDone(true);
      return undefined;
    }
    let cancelled = false;
    setStrategyDone(false);
    api(`/api/clients/${client.id}/strategy`)
      .then((payload) => {
        if (!cancelled) setStrategy(payload);
      })
      .catch(() => {
        if (!cancelled) setStrategy(null);
      })
      .finally(() => {
        if (!cancelled) setStrategyDone(true);
      });
    return () => {
      cancelled = true;
    };
  }, [client?.id]);

  if (!client) return null;

  const waitingForChannel = !channelStatus && channelLoading && !channelError;
  const waitingForStrategy =
    Boolean(channelStatus) &&
    !strategyDone &&
    (role === "admin" || role === "editor");

  const step = buildNextStep({
    role,
    clientName: client.name,
    channelStatus,
    strategy: strategyDone ? strategy : null,
    statusLoading: waitingForChannel || waitingForStrategy,
    statusError: channelError,
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

  const showAction =
    step.action &&
    step.label &&
    !(step.action === "fetch" && role === "viewer") &&
    !(step.action === "setup" && role === "viewer");

  return (
    <section className={toneClass} aria-label="Vervolgstap">
      <div className="next-step-copy">
        <p className="next-step-kicker">Vervolgstap</p>
        <strong className="next-step-title">{step.title}</strong>
        <p className="next-step-body">{step.body}</p>
      </div>
      {showAction ? (
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
