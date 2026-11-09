"""Per-client post rating formula. Missing metrics stay unknown — never coerced to 0.

Maaike's definitive formula is not shipped. Ratings only run after a client explicitly
activates a complete settings profile. Provisional templates must stay clearly labeled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from maaike.repository import StoredPost

LABEL_GOED = "Good"
LABEL_GEMIDDELD = "Average"
LABEL_SLECHT = "Poor"
LABEL_NB = "Unable to rate"

COLOR_GOED = "green"
COLOR_GEMIDDELD = "orange"
COLOR_SLECHT = "red"
COLOR_NB = "neutral"

ENGAGEMENT_METRICS = ("likes", "comments", "shares", "saves")
DENOMINATOR_CHOICES = ("reach", "views")

PROVISIONAL_TEMPLATE_KEY = "voorlopig_engagement_per_bereik"
PROVISIONAL_TEMPLATE_NAME = "Provisional — weighted engagement / reach"

COMPARISON_DISCLAIMER = (
    "This score is not proof that posts from different platforms, content types "
    "or ages are fairly comparable. Final rules will come from Maaike."
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_rating_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_rating_settings (
            client_id INTEGER PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            profile_name TEXT NOT NULL DEFAULT '',
            is_provisional INTEGER NOT NULL DEFAULT 1,
            formula_key TEXT NOT NULL DEFAULT '',
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        """
    )


def formula_catalog() -> list[dict[str, Any]]:
    """Available formula structures — no definitive Maaike thresholds."""
    return [
        {
            "key": PROVISIONAL_TEMPLATE_KEY,
            "name": PROVISIONAL_TEMPLATE_NAME,
            "is_provisional": True,
            "description": (
                "Sum of available weighted interactions (likes/comments/shares/saves), "
                "divided by reach, × 1000. Missing metrics do not count as 0; "
                "without reach or any interaction measurement: Unable to rate."
            ),
            "default_weights": {"likes": 1.0, "comments": 2.0, "shares": 2.0, "saves": 3.0},
            "denominator_metric": "reach",
            "thresholds_required": True,
            "threshold_hints": {
                "note": "Examples are not Maaike thresholds — enter your own before activating.",
                "example_good_min": 5.0,
                "example_average_min": 2.0,
                "score_unit": "weighted engagement per 1000 reach",
            },
        },
        {
            "key": "voorlopig_engagement_per_weergaven",
            "name": "Provisional — weighted engagement / views",
            "is_provisional": True,
            "description": (
                "Same weighted interactions, divided by views × 1000. "
                "Without views or interactions: Unable to rate."
            ),
            "default_weights": {"likes": 1.0, "comments": 2.0, "shares": 2.0, "saves": 3.0},
            "denominator_metric": "views",
            "thresholds_required": True,
            "threshold_hints": {
                "note": "Examples are not Maaike thresholds — enter your own before activating.",
                "example_good_min": 8.0,
                "example_average_min": 3.0,
                "score_unit": "weighted engagement per 1000 views",
            },
        },
    ]


def _default_settings_body() -> dict[str, Any]:
    return {
        "weights": {"likes": 1.0, "comments": 2.0, "shares": 2.0, "saves": 3.0},
        "denominator_metric": "reach",
        "good_min": None,
        "average_min": None,
        "min_age_hours": None,
        "platforms": None,
        "content_kinds": None,
        "notes": "",
    }


def empty_settings(client_id: int) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "active": False,
        "profile_name": "",
        "is_provisional": True,
        "formula_key": "",
        "ready_to_activate": False,
        "activation_blockers": ["No formula selected."],
        "comparison_disclaimer": COMPARISON_DISCLAIMER,
        "catalog": formula_catalog(),
        **_default_settings_body(),
        "updated_at": None,
    }


def get_rating_settings(conn, client_id: int) -> dict[str, Any]:
    ensure_rating_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_rating_settings WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        return empty_settings(client_id)
    body = json.loads(row["settings_json"] or "{}")
    payload = empty_settings(client_id)
    payload.update(
        {
            "active": bool(row["active"]),
            "profile_name": row["profile_name"] or "",
            "is_provisional": bool(row["is_provisional"]),
            "formula_key": row["formula_key"] or "",
            "weights": body.get("weights") or payload["weights"],
            "denominator_metric": body.get("denominator_metric") or payload["denominator_metric"],
            "good_min": body.get("good_min"),
            "average_min": body.get("average_min"),
            "min_age_hours": body.get("min_age_hours"),
            "platforms": body.get("platforms"),
            "content_kinds": body.get("content_kinds"),
            "notes": body.get("notes") or "",
            "updated_at": row["updated_at"],
        }
    )
    blockers = activation_blockers(payload)
    payload["activation_blockers"] = blockers
    payload["ready_to_activate"] = not blockers
    return payload


def activation_blockers(settings: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not (settings.get("formula_key") or "").strip():
        blockers.append("Choose a formula template.")
    if not (settings.get("profile_name") or "").strip():
        blockers.append("Give the formula a name (e.g. including ‘Provisional’).")
    denom = settings.get("denominator_metric")
    if denom not in DENOMINATOR_CHOICES:
        blockers.append("Choose denominator: reach or views.")
    weights = settings.get("weights") or {}
    if not any(_as_float(weights.get(m)) is not None and _as_float(weights.get(m)) != 0 for m in ENGAGEMENT_METRICS):
        blockers.append("Set at least one weight > 0 on likes/comments/shares/saves.")
    good = _as_float(settings.get("good_min"))
    avg = _as_float(settings.get("average_min"))
    if good is None or avg is None:
        blockers.append("Enter good_min and average_min thresholds explicitly (no silent defaults).")
    elif not (good > avg >= 0):
        blockers.append("Required: good_min > average_min ≥ 0.")
    return blockers


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_provisional_template(settings: dict[str, Any], formula_key: str) -> dict[str, Any]:
    catalog = {item["key"]: item for item in formula_catalog()}
    item = catalog.get(formula_key)
    if item is None:
        raise ValueError("Unknown formula template.")
    next_settings = dict(settings)
    next_settings["formula_key"] = item["key"]
    next_settings["profile_name"] = item["name"]
    next_settings["is_provisional"] = True
    next_settings["weights"] = dict(item["default_weights"])
    next_settings["denominator_metric"] = item["denominator_metric"]
    # Do NOT invent thresholds — leave unset so activation stays blocked until filled.
    next_settings["good_min"] = None
    next_settings["average_min"] = None
    next_settings["active"] = False
    next_settings["notes"] = (
        "Template loaded as Provisional. Enter thresholds and activate only afterwards. "
        + COMPARISON_DISCLAIMER
    )
    return next_settings


def save_rating_settings(conn, client_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ensure_rating_tables(conn)
    current = get_rating_settings(conn, client_id)
    if body.get("load_template"):
        current = apply_provisional_template(current, str(body.get("formula_key") or body["load_template"]))
    else:
        if "formula_key" in body:
            current["formula_key"] = str(body.get("formula_key") or "").strip()
        if "profile_name" in body:
            current["profile_name"] = str(body.get("profile_name") or "").strip()
        if "is_provisional" in body:
            current["is_provisional"] = bool(body.get("is_provisional"))
        if "weights" in body and isinstance(body["weights"], dict):
            weights = {}
            for metric in ENGAGEMENT_METRICS:
                weights[metric] = _as_float(body["weights"].get(metric))
                if weights[metric] is None:
                    weights[metric] = 0.0
            current["weights"] = weights
        if "denominator_metric" in body:
            current["denominator_metric"] = str(body.get("denominator_metric") or "").strip()
        if "good_min" in body:
            current["good_min"] = _as_float(body.get("good_min"))
        if "average_min" in body:
            current["average_min"] = _as_float(body.get("average_min"))
        if "min_age_hours" in body:
            current["min_age_hours"] = _as_float(body.get("min_age_hours"))
        if "platforms" in body:
            plats = body.get("platforms")
            current["platforms"] = list(plats) if isinstance(plats, list) and plats else None
        if "content_kinds" in body:
            kinds = body.get("content_kinds")
            current["content_kinds"] = list(kinds) if isinstance(kinds, list) and kinds else None
        if "notes" in body:
            current["notes"] = str(body.get("notes") or "")
        if "active" in body:
            current["active"] = bool(body.get("active"))

    blockers = activation_blockers(current)
    if current["active"] and blockers:
        raise ValueError("Formula cannot be active: " + " ".join(blockers))

    # Force provisional naming clarity when using voorlopig templates
    if current["formula_key"].startswith("voorlopig") or current.get("is_provisional"):
        current["is_provisional"] = True
        if current["profile_name"] and "voorlopig" not in current["profile_name"].lower() and "provisional" not in current["profile_name"].lower():
            current["profile_name"] = f"Provisional — {current['profile_name']}"

    settings_json = {
        "weights": current["weights"],
        "denominator_metric": current["denominator_metric"],
        "good_min": current["good_min"],
        "average_min": current["average_min"],
        "min_age_hours": current["min_age_hours"],
        "platforms": current["platforms"],
        "content_kinds": current["content_kinds"],
        "notes": current["notes"],
    }
    now = _now()
    conn.execute(
        """
        INSERT INTO client_rating_settings (
            client_id, active, profile_name, is_provisional, formula_key, settings_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            active = excluded.active,
            profile_name = excluded.profile_name,
            is_provisional = excluded.is_provisional,
            formula_key = excluded.formula_key,
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at
        """,
        (
            client_id,
            1 if current["active"] else 0,
            current["profile_name"],
            1 if current["is_provisional"] else 0,
            current["formula_key"],
            json.dumps(settings_json, ensure_ascii=False),
            now,
        ),
    )
    return get_rating_settings(conn, client_id)


def _metric_value(post: StoredPost, name: str) -> int | None:
    value = getattr(post, name, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _post_age_hours(post: StoredPost, *, now: datetime | None = None) -> float | None:
    raw = (post.published_at or "").strip()
    if not raw:
        return None
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(tz=timezone.utc)
    return max(0.0, (moment - published).total_seconds() / 3600.0)


def rate_post(post: StoredPost, settings: dict[str, Any]) -> dict[str, Any]:
    """Compute formula rating for one post. Never invents missing numbers as 0."""
    base = {
        "source": "formula",
        "profile_name": settings.get("profile_name") or "",
        "is_provisional": bool(settings.get("is_provisional")),
        "formula_key": settings.get("formula_key") or "",
        "label": LABEL_NB,
        "color": COLOR_NB,
        "score": None,
        "score_known": False,
        "explanation": "",
        "reason": "",
        "used_metrics": {},
        "missing_metrics": [],
        "comparison_disclaimer": COMPARISON_DISCLAIMER,
        "excel_rating": post.rating_text,
        "excel_source": post.rating_source_label,
    }

    if not settings.get("active"):
        base["reason"] = "Formula not active. Set thresholds and activate rating for this client."
        base["explanation"] = base["reason"]
        return base

    blockers = activation_blockers(settings)
    if blockers:
        base["reason"] = "Active formula is incomplete: " + " ".join(blockers)
        base["explanation"] = base["reason"]
        return base

    platforms = settings.get("platforms")
    if platforms and post.platform not in platforms:
        base["reason"] = f"Platform ‘{post.platform}’ is outside the formula scope."
        base["explanation"] = base["reason"]
        return base

    kinds = settings.get("content_kinds")
    if kinds and (post.content_kind or "") not in kinds:
        base["reason"] = f"Content type ‘{post.content_kind or 'unknown'}’ is outside the formula scope."
        base["explanation"] = base["reason"]
        return base

    min_age = _as_float(settings.get("min_age_hours"))
    age = _post_age_hours(post)
    if min_age is not None and min_age > 0:
        if age is None:
            base["reason"] = "Publication time unknown; minimum age cannot be checked."
            base["explanation"] = base["reason"]
            return base
        if age < min_age:
            base["reason"] = (
                f"Post has only been online for {age:.1f} hours (minimum {min_age:g} hours). "
                "Too early for a formula rating."
            )
            base["explanation"] = base["reason"]
            return base

    weights = settings.get("weights") or {}
    used: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    weighted_sum = 0.0
    for metric in ENGAGEMENT_METRICS:
        weight = _as_float(weights.get(metric)) or 0.0
        if weight == 0:
            continue
        value = _metric_value(post, metric)
        if value is None:
            missing.append(metric)
            continue
        contribution = weight * float(value)
        weighted_sum += contribution
        used[metric] = {"value": value, "weight": weight, "contribution": round(contribution, 4)}

    if not used:
        base["missing_metrics"] = missing or list(ENGAGEMENT_METRICS)
        base["reason"] = (
            "No available interaction figures for the weighted metrics "
            f"({', '.join(missing) if missing else 'likes/comments/shares/saves'}). "
            "Missing values are not counted as 0."
        )
        base["explanation"] = base["reason"]
        return base

    denom_name = settings.get("denominator_metric")
    denom_value = _metric_value(post, str(denom_name))
    if denom_value is None:
        base["used_metrics"] = used
        base["missing_metrics"] = missing + [str(denom_name)]
        base["reason"] = (
            f"Denominator ‘{denom_name}’ is missing. Without a denominator there is no score "
            "(not silently divided by 0 or 1)."
        )
        base["explanation"] = base["reason"]
        return base
    if denom_value <= 0:
        base["used_metrics"] = used
        base["missing_metrics"] = missing
        base["reason"] = f"Denominator ‘{denom_name}’ is {denom_value}; division is not meaningful."
        base["explanation"] = base["reason"]
        return base

    score = (weighted_sum / float(denom_value)) * 1000.0
    good_min = float(settings["good_min"])
    average_min = float(settings["average_min"])
    if score >= good_min:
        label, color = LABEL_GOED, COLOR_GOED
    elif score >= average_min:
        label, color = LABEL_GEMIDDELD, COLOR_GEMIDDELD
    else:
        label, color = LABEL_SLECHT, COLOR_SLECHT

    parts = [
        f"{'Provisional ' if settings.get('is_provisional') else ''}formula: {settings.get('profile_name')}.",
        "Calculation: ("
        + " + ".join(f"{m}×{info['weight']:g}" for m, info in used.items())
        + f") / {denom_name} × 1000 = {score:.3f}.",
        f"Thresholds: Good ≥ {good_min:g}, Average ≥ {average_min:g}, below that Poor.",
    ]
    if missing:
        parts.append(
            "Not included (unknown, not 0): " + ", ".join(missing) + "."
        )
    if age is not None:
        parts.append(f"Age online ≈ {age:.1f} hours.")
    parts.append(COMPARISON_DISCLAIMER)

    base.update(
        {
            "label": label,
            "color": color,
            "score": round(score, 3),
            "score_known": True,
            "explanation": " ".join(parts),
            "reason": "",
            "used_metrics": used,
            "missing_metrics": missing,
            "denominator": {"metric": denom_name, "value": denom_value},
        }
    )
    return base


def rate_posts(posts: list[StoredPost], settings: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {post.post_id: rate_post(post, settings) for post in posts}
