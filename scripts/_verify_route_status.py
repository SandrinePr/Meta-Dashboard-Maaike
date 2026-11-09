"""Report credential/route readiness without printing secrets."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from dotenv import load_dotenv

from maaike.claude_analysis import claude_connection_status, load_analysis_prompt_bundle
from maaike.db import connect
from maaike.repository import connection_label, get_client, list_posts, load_page_secret

load_dotenv(override=False)
BASE = "https://127.0.0.1:8000"
CTX = ssl._create_unverified_context()


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def main() -> None:
    key = os.getenv("CLAUDE_API_KEY", "").strip() or os.getenv("ANTHROPIC_API_KEY", "").strip()
    print(
        "anthropic_key",
        {
            "present": bool(key),
            "length": len(key),
            "prefix": key[:7] + "…" if len(key) >= 7 else "(short)",
            "looks_like_sk": key.startswith("sk-ant-"),
        },
    )
    print("claude_status", claude_connection_status()["configured"])
    print("prompts", load_analysis_prompt_bundle()["ready"], load_analysis_prompt_bundle()["missing_files"])

    conn = connect()
    client = get_client(conn, 1)
    print("client_label", connection_label(client))
    secret = load_page_secret(conn, 1)
    print(
        "meta_secret",
        {
            "present": secret is not None,
            "page_id": secret[0] if secret else None,
            "ig_id": secret[1] if secret else None,
            "token_len": len(secret[2]) if secret else 0,
        },
    )
    posts = list_posts(conn, 1)
    print("posts_total", len(posts))
    ig = [p for p in posts if p.platform == "instagram" and (p.caption or "").strip()]
    print("ig_caption_posts", len(ig))
    if ig:
        sample = sorted(ig, key=lambda p: p.published_at or "", reverse=True)[0]
        print(
            "sample_post",
            {
                "id": sample.post_id,
                "published_at": sample.published_at,
                "likes": sample.likes,
                "views": sample.views,
                "source_origin": sample.source_origin,
            },
        )
        st, payload = call("POST", f"/api/clients/1/posts/{sample.post_id}/claude-analyze", {})
        print("claude_http", st)
        if isinstance(payload, dict):
            analysis = payload.get("analysis") or payload
            print(
                "claude_result",
                {
                    "id": analysis.get("id"),
                    "status": analysis.get("status"),
                    "detail": payload.get("detail"),
                    "error_text": analysis.get("error_text"),
                    "rating_text": analysis.get("rating_text"),
                },
            )
            if analysis.get("id"):
                st2, reopened = call("GET", f"/api/clients/1/ai-analyses/{analysis['id']}")
                print("reopen_http", st2, reopened.get("analysis", {}).get("status"))

    st, crawl = call(
        "POST",
        "/api/clients/1/crawl-accounts/redrock.agency/run",
        {"max_pages": 1, "page_limit": 5},
    )
    print(
        "crawl_retry",
        {
            "http": st,
            "status": crawl.get("status") if isinstance(crawl, dict) else None,
            "errors": (crawl.get("errors") or [])[:1] if isinstance(crawl, dict) else crawl,
            "posts_saved": crawl.get("posts_saved") if isinstance(crawl, dict) else None,
        },
    )


if __name__ == "__main__":
    main()
