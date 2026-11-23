/**
 * Local unit checks for Meta attempt status (no secrets / no network).
 * Run: node --test frontend/src/metaLoginDisplay.test.mjs
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  META_ABORTED_LABEL,
  META_LINKING_LABEL,
  metaAttemptBanner,
  metaForDisplay,
} from "./metaLoginDisplay.js";

const OLD_SECRET_ERROR = "Error validating client secret.";

describe("metaAttemptBanner — fail then new attempt", () => {
  it("shows the previous failure while idle", () => {
    const banner = metaAttemptBanner({
      linkPhase: "idle",
      statusDetail: OLD_SECRET_ERROR,
      statusLabel: "Mislukt",
      connected: false,
    });
    assert.equal(banner?.kind, "error");
    assert.match(banner.text, /Error validating client secret/);
  });

  it("hides the previous failure while linking and shows Bezig met koppelen…", () => {
    const banner = metaAttemptBanner({
      linkPhase: "linking",
      attemptError: "",
      metaError: OLD_SECRET_ERROR,
      statusDetail: OLD_SECRET_ERROR,
      statusLabel: "Mislukt",
      connected: false,
    });
    assert.deepEqual(banner, { kind: "progress", text: META_LINKING_LABEL });
  });

  it("shows only the new attempt error after a failed return", () => {
    const banner = metaAttemptBanner({
      linkPhase: "idle",
      attemptError: "Nieuwe fout van deze poging",
      metaError: OLD_SECRET_ERROR,
      statusDetail: OLD_SECRET_ERROR,
      connected: false,
    });
    assert.deepEqual(banner, { kind: "error", text: "Nieuwe fout van deze poging" });
  });

  it("shows Koppeling afgebroken when the popup is closed", () => {
    const banner = metaAttemptBanner({
      linkPhase: "aborted",
      attemptError: META_ABORTED_LABEL,
      statusDetail: OLD_SECRET_ERROR,
      connected: false,
    });
    assert.deepEqual(banner, { kind: "error", text: META_ABORTED_LABEL });
  });
});

describe("metaForDisplay", () => {
  it("strips status_detail while linking so the UI cannot revive the old error", () => {
    const meta = {
      connected: false,
      status_label: "Mislukt",
      status_detail: OLD_SECRET_ERROR,
    };
    const shown = metaForDisplay(meta, { linkPhase: "linking", attemptError: "" });
    assert.equal(shown.status_detail, null);
    assert.equal(meta.status_detail, OLD_SECRET_ERROR);
  });

  it("keeps status_detail when idle with no attempt error", () => {
    const meta = { status_detail: OLD_SECRET_ERROR };
    const shown = metaForDisplay(meta, { linkPhase: "idle", attemptError: "" });
    assert.equal(shown.status_detail, OLD_SECRET_ERROR);
  });
});

describe("fail then retry sequence", () => {
  it("old secret error disappears for the new attempt, then only the new result shows", () => {
    // 1) Previous attempt failed
    let phase = "idle";
    let attemptError = "";
    let statusDetail = OLD_SECRET_ERROR;
    let banner = metaAttemptBanner({
      linkPhase: phase,
      attemptError,
      statusDetail,
      connected: false,
      statusLabel: "Mislukt",
    });
    assert.match(banner.text, /Error validating client secret/);

    // 2) User starts a new attempt — prior error must be hidden
    phase = "linking";
    attemptError = "";
    banner = metaAttemptBanner({
      linkPhase: phase,
      attemptError,
      metaError: OLD_SECRET_ERROR,
      statusDetail,
      connected: false,
      statusLabel: "Mislukt",
    });
    assert.equal(banner.text, META_LINKING_LABEL);

    const whileLinking = metaForDisplay(
      { status_detail: statusDetail, connected: false },
      { linkPhase: phase, attemptError },
    );
    assert.equal(whileLinking.status_detail, null);

    // 3a) New attempt fails with a different message
    phase = "idle";
    attemptError = "Toegang geweigerd voor deze app.";
    statusDetail = attemptError;
    banner = metaAttemptBanner({
      linkPhase: phase,
      attemptError,
      statusDetail: OLD_SECRET_ERROR,
      connected: false,
    });
    assert.equal(banner.text, "Toegang geweigerd voor deze app.");
    assert.doesNotMatch(banner.text, /client secret/i);

    // 3b) Or user closes the popup — aborted, not the old secret error
    phase = "aborted";
    attemptError = META_ABORTED_LABEL;
    banner = metaAttemptBanner({
      linkPhase: phase,
      attemptError,
      statusDetail: OLD_SECRET_ERROR,
      connected: false,
    });
    assert.equal(banner.text, META_ABORTED_LABEL);
  });
});
