"""Verify legend CRUD, post linking, reload, and client isolation. No secrets."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from maaike.db import connect, initialize_database
from maaike.repository import list_formats, list_hooks, list_pillars

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
    conn = connect()
    print(
        "seeded_hooks_client1",
        len(list_hooks(conn, 1)),
        "formats",
        len(list_formats(conn, 1)),
        "pillars",
        len(list_pillars(conn, 1)),
    )

    st, legend1 = call("GET", "/api/clients/1/legend")
    print("legend1_http", st, {k: len(legend1.get(k) or []) for k in ("formats", "pillars", "hooks")})

    marker = "DemoFormat-BB-20261102"
    st, after_add = call(
        "POST",
        "/api/clients/2/formats",
        {"name": marker, "explanation": "Alleen voor Test-klant."},
    )
    print("add_format_client2", st, any(f.get("name") == marker for f in after_add.get("formats") or []))

    st, legend1b = call("GET", "/api/clients/1/legend")
    leaked = any(f.get("name") == marker for f in legend1b.get("formats") or [])
    print("client1_unaffected", not leaked)

    st, posts = call("GET", "/api/clients/1/posts")
    print("posts_http", st, "count", len(posts.get("posts") or []), "hooks_legend", len(posts.get("hooks") or []))
    target = None
    for post in posts.get("posts") or []:
        miss = post.get("missing_classification") or {}
        if miss.get("any"):
            target = post
            break
    if target is None and posts.get("posts"):
        target = posts["posts"][0]
    if target is None:
        print("no_posts")
        return

    formats = posts.get("formats") or []
    pillars = posts.get("pillars") or []
    hooks = posts.get("hooks") or []
    fmt = formats[0]["id"] if formats else None
    pil = pillars[0]["id"] if pillars else None
    hook_name = hooks[0]["name"] if hooks else "Demo hook BB"
    st, patched = call(
        "PATCH",
        f"/api/clients/1/posts/{target['id']}",
        {"format_id": fmt, "pillar_id": pil, "hook": hook_name},
    )
    print("patch_http", st)
    if st >= 400:
        print("patch_detail", patched)
        return

    st, posts2 = call("GET", "/api/clients/1/posts")
    reloaded = next((p for p in posts2.get("posts") or [] if p["id"] == target["id"]), None)
    print(
        "reload_ok",
        {
            "id": reloaded and reloaded["id"],
            "format_id": reloaded and reloaded.get("format_id"),
            "pillar_id": reloaded and reloaded.get("pillar_id"),
            "hook": reloaded and (reloaded.get("hook") or reloaded.get("cells", {}).get("Hook")),
            "cells_format": reloaded and reloaded.get("cells", {}).get("Contentformat"),
            "cells_pillar": reloaded and reloaded.get("cells", {}).get("Contentpijler"),
        },
    )
    missing_any = sum(1 for p in posts2.get("posts") or [] if (p.get("missing_classification") or {}).get("any"))
    print("missing_any_count", missing_any)

    # cleanup demo format on client 2 (leave if patch-only exists — formats have no delete API)
    print("done")


if __name__ == "__main__":
    main()
