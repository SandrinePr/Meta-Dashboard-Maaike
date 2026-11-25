/**
 * One concrete next step for the daily dashboard (Maaike feedback point 5).
 * Pure helper so roles and client status stay easy to test.
 */

export function canEditClient(role) {
  return role === "admin" || role === "editor";
}

/**
 * @param {{
 *   role?: string,
 *   clientName?: string,
 *   channelStatus?: {
 *     state?: string,
 *     headline?: string,
 *     next_action?: string,
 *     action_key?: string,
 *     action_label?: string,
 *   } | null,
 *   strategy?: {
 *     missing_required?: string[],
 *     next_step?: string,
 *     review_status?: string,
 *   } | null,
 *   statusLoading?: boolean,
 *   statusError?: string | null,
 * }} input
 */
export function buildNextStep(input = {}) {
  const role = input.role || "viewer";
  const name = String(input.clientName || "deze klant").trim() || "deze klant";
  const channel = input.channelStatus || null;
  const strategy = input.strategy || null;
  const editable = canEditClient(role);
  const statusLoading = input.statusLoading !== false && !input.statusError;
  const statusError = input.statusError || null;

  if (!channel && statusError) {
    return {
      title: `Status voor ${name} niet beschikbaar`,
      body:
        "De stand van zaken kon niet worden opgehaald. Vernieuw de pagina of open Socialmediaberichten om te kijken wat er al staat.",
      action: "posts",
      label: "Naar Socialmediaberichten",
      tone: "warn",
    };
  }

  if (!channel) {
    if (statusLoading) {
      return {
        title: `Status voor ${name} laden…`,
        body: "Even geduld terwijl HAMSTER de stand van zaken ophaalt.",
        action: null,
        label: "",
        tone: "neutral",
      };
    }
    return {
      title: `Status voor ${name} niet beschikbaar`,
      body: "Er is geen actuele status. Open Socialmediaberichten of kies een andere klant.",
      action: "posts",
      label: "Naar Socialmediaberichten",
      tone: "warn",
    };
  }

  if (channel.state === "view_existing") {
    return {
      title: channel.headline || "Berichten bekijken kan",
      body: channel.next_action || `De berichten van ${name} blijven zichtbaar. Vernieuwen vraagt een nieuwe koppeling.`,
      action: editable ? "setup" : "posts",
      label: editable ? channel.action_label || "Accounts koppelen om te vernieuwen" : "Berichten bekijken",
      tone: "info",
    };
  }

  if (channel.state === "connect_required") {
    if (editable) {
      return {
        title: channel.headline || "Koppel eerst je accounts",
        body: channel.next_action || `Koppel Facebook en Instagram voor ${name}.`,
        action: "setup",
        label: channel.action_label || "Klant inrichten",
        tone: "warn",
      };
    }
    return {
      title: "Nog geen Meta-koppeling",
      body: `Voor ${name} is Facebook/Instagram nog niet gekoppeld. Een editor (Jet/Mo) regelt dat via Klant inrichten. Je kunt wel bekijken wat er al staat.`,
      action: "posts",
      label: "Naar Socialmediaberichten",
      tone: "warn",
    };
  }

  if (channel.state === "fetch_first_posts") {
    if (editable) {
      return {
        title: channel.headline || "Haal je eerste berichten op",
        body: channel.next_action || `Haal de eerste berichten op voor ${name}.`,
        action: "fetch",
        label: channel.action_label || "Eerste berichten ophalen",
        tone: "info",
      };
    }
    return {
      title: "Nog geen berichten",
      body: `Voor ${name} staan nog geen berichten klaar. Vraag een editor om berichten op te halen, of bekijk Rapporten als die er al zijn.`,
      action: "reports",
      label: "Naar Rapporten",
      tone: "info",
    };
  }

  const missing = Array.isArray(strategy?.missing_required) ? strategy.missing_required : [];
  if (editable && missing.length) {
    return {
      title: "Rond de klantinrichting af",
      body:
        strategy?.next_step ||
        `Vul doelen, strategie en klantprompts voor ${name} bij in Klant inrichten.`,
      action: "setup",
      label: "Open Klant inrichten",
      tone: "warn",
    };
  }

  if (editable && strategy?.review_status === "te_controleren") {
    return {
      title: "Controleer de strategie",
      body: strategy?.next_step || `Controleer het voorstel voor ${name} in Klant inrichten.`,
      action: "setup",
      label: "Open Klant inrichten",
      tone: "info",
    };
  }

  if (channel.state === "ready_to_view") {
    if (editable) {
      return {
        title: channel.headline || "Je berichten zijn klaar om te bekijken",
        body:
          channel.next_action ||
          `Er staan berichten van ${name} klaar. Haal nieuwe berichten op wanneer je cijfers wilt bijwerken.`,
        action: "fetch",
        label: channel.action_label || "Nieuwe berichten ophalen",
        tone: "ok",
      };
    }
    return {
      title: channel.headline || "Je berichten zijn klaar om te bekijken",
      body: `Er staan berichten van ${name} klaar om te bekijken.`,
      action: "posts",
      label: "Naar Socialmediaberichten",
      tone: "ok",
    };
  }

  return {
    title: "Klaar voor dagelijks werk",
    body: `Kies voor ${name} een onderdeel: Socialmediaberichten, Resultaten of Rapporten.`,
    action: "results",
    label: "Naar Resultaten",
    tone: "ok",
  };
}
