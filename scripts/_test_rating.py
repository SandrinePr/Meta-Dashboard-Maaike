"""Verify rating settings, missing metrics, activate/recalc. No secrets."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from maaike.db import connect, initialize_database

BASE = "https://127.0.0.1:8000"
CTX = ssl._create_unverified_context()


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def main() -> None:
    initialize_database()
    before_links = connect().execute("SELECT COUNT(*) n FROM post_import_links").fetchone()["n"]

    st, settings = call("GET", "/api/clients/1/rating-settings")
    print("get", st, "active", settings.get("active"), "blockers", settings.get("activation_blockers"))

    st, loaded = call(
        "PUT",
        "/api/clients/1/rating-settings",
        {"load_template": "voorlopig_engagement_per_bereik"},
    )
    print(
        "template",
        st,
        loaded.get("profile_name"),
        "active",
        loaded.get("active"),
        "ready",
        loaded.get("ready_to_activate"),
    )

    st, refused = call(
        "PUT",
        "/api/clients/1/rating-settings",
        {
            "profile_name": loaded.get("profile_name"),
            "formula_key": loaded.get("formula_key"),
            "weights": loaded.get("weights"),
            "denominator_metric": "reach",
            "good_min": None,
            "average_min": None,
            "active": True,
            "is_provisional": True,
        },
    )
    print("activate_without_thresholds", st, refused.get("detail", "")[:120])

    st, active = call(
        "PUT",
        "/api/clients/1/rating-settings",
        {
            "profile_name": "Voorlopig — gewogen interactie / bereik",
            "formula_key": "voorlopig_engagement_per_bereik",
            "weights": {"likes": 1, "comments": 2, "shares": 2, "saves": 3},
            "denominator_metric": "reach",
            "good_min": 5,
            "average_min": 2,
            "min_age_hours": None,
            "active": True,
            "is_provisional": True,
            "notes": "Testgrenzen — niet Maaike-definitief",
        },
    )
    print("activate", st, "active", active.get("active"), "ready", active.get("ready_to_activate"))

    st, posts = call("GET", "/api/clients/1/posts")
    sample = (posts.get("posts") or [])[:8]
    labels = {}
    for post in sample:
        fr = post.get("formula_rating") or {}
        labels[fr.get("label")] = labels.get(fr.get("label"), 0) + 1
        if fr.get("label") == "Niet te beoordelen" and "nul" in (fr.get("reason") or "").lower():
            print("FAIL silent zero language", post["id"])
    print("sample_labels", labels)
    scored = next((p for p in sample if (p.get("formula_rating") or {}).get("score_known")), None)
    nb = next((p for p in sample if (p.get("formula_rating") or {}).get("label") == "Niet te beoordelen"), None)
    if scored:
        fr = scored["formula_rating"]
        print("scored_example", scored["id"], fr.get("label"), fr.get("score"), fr.get("color"))
        print("explanation_snip", (fr.get("explanation") or "")[:180])
    if nb:
        print("nb_example", nb["id"], (nb["formula_rating"].get("reason") or "")[:160])

    st, detail = call("GET", f"/api/clients/1/posts/{(scored or sample[0])['id']}")
    print("detail_rating", st, (detail.get("formula_rating") or {}).get("label"), detail.get("rating"))

    # deactivate again so demo stays safe by default after test? User may want it on for demo.
    # Leave active with provisional thresholds clearly labeled — or deactivate.
    call(
        "PUT",
        "/api/clients/1/rating-settings",
        {
            "profile_name": "Voorlopig — gewogen interactie / bereik",
            "formula_key": "voorlopig_engagement_per_bereik",
            "weights": {"likes": 1, "comments": 2, "shares": 2, "saves": 3},
            "denominator_metric": "reach",
            "good_min": 5,
            "average_min": 2,
            "active": False,
            "is_provisional": True,
            "notes": "Testgrenzen bewaard maar gedeactiveerd na controle.",
        },
    )
    after_links = connect().execute("SELECT COUNT(*) n FROM post_import_links").fetchone()["n"]
    print("import_links_unchanged", before_links == after_links, before_links)


if __name__ == "__main__":
    main()
