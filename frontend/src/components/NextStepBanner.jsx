import { useEffect, useState } from "react";
import { api } from "../api.js";
import { buildNextStep } from "../nextStep.js";

/**
 * Single concrete follow-up at the top of the daily dashboard.
 * Loads channel + strategy itself so a slow sidebar sync cannot leave “laden…” forever.
 */
export default function NextStepBanner({
  client,
  role,
  channelStatus: channelFromParent = null,
  channelLoading: parentLoading = false,
  channelError: parentError = null,
  syncing = false,
  onOpenSetup,
  onFetchPosts,
  onOpenResults,
  onOpenPosts,
  onOpenReports,
}) {
  const [channelStatus, setChannelStatus] = useState(channelFromParent);
  const [channelLoading, setChannelLoading] = useState(!channelFromParent);
  const [channelError, setChannelError] = useState(parentError);
  const [strategy, setStrategy] = useState(null);
  const [strategyDone, setStrategyDone] = useState(false);

  useEffect(() => {
    if (channelFromParent) {
      setChannelStatus(channelFromParent);
      setChannelLoading(false);
      setChannelError(null);
    } else if (parentError) {
      setChannelError(parentError);
      setChannelLoading(false);
    } else if (parentLoading) {
      setChannelLoading(true);
    }
  }, [channelFromParent, parentError, parentLoading]);

  useEffect(() => {
    if (!client?.id) {
      setChannelStatus(null);
      setChannelLoading(false);
      setChannelError(null);
      setStrategy(null);
      setStrategyDone(true);
      return undefined;
    }
    let cancelled = false;
    setStrategyDone(false);
    if (!channelFromParent) {
      setChannelLoading(true);
      setChannelError(null);
    }

    const channelPromise = channelFromParent
      ? Promise.resolve(null)
      : api(`/api/clients/${client.id}/sync-totals`)
          .then((payload) => {
            if (cancelled) return;
            if (payload?.client_id != null && Number(payload.client_id) !== Number(client.id)) {
              return;
            }
            setChannelStatus(payload?.channel_status || null);
            setChannelError(null);
          })
          .catch((exc) => {
            if (cancelled) return;
            setChannelStatus(null);
            setChannelError(exc.message || "Status laden mislukt.");
          })
          .finally(() => {
            if (!cancelled) setChannelLoading(false);
          });

    const strategyPromise = api(`/api/clients/${client.id}/strategy`)
      .then((payload) => {
        if (!cancelled) setStrategy(payload);
      })
      .catch(() => {
        if (!cancelled) setStrategy(null);
      })
      .finally(() => {
        if (!cancelled) setStrategyDone(true);
      });

    Promise.allSettled([channelPromise, strategyPromise]);
    return () => {
      cancelled = true;
    };
  }, [client?.id, channelFromParent]);

  if (!client) return null;

  const effectiveChannel = channelFromParent || channelStatus;
  const waitingForChannel = !effectiveChannel && (channelLoading || parentLoading) && !(channelError || parentError);
  const waitingForStrategy =
    Boolean(effectiveChannel) && !strategyDone && (role === "admin" || role === "editor");

  const step = buildNextStep({
    role,
    clientName: client.name,
    channelStatus: effectiveChannel,
    strategy: strategyDone ? strategy : null,
    statusLoading: waitingForChannel || waitingForStrategy,
    statusError: channelError || parentError,
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
