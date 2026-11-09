"""One-shot crawl + optional Claude analysis verification. Not for production use."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

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
    st, linked = call("POST", "/api/clients/1/crawl-accounts", {"name": "redrock.agency"})
    print("link", st, linked.get("account", {}).get("username") if isinstance(linked, dict) else linked)
    st, crawl = call(
        "POST",
        "/api/clients/1/crawl-accounts/redrock.agency/run",
        {"max_pages": 2, "page_limit": 25},
    )
    print("crawl_http", st)
    for key in (
        "username",
        "status",
        "fetched_at",
        "source",
        "posts_saved",
        "metrics_saved",
        "missing_metric_slots",
        "fields_seen_on_post",
        "oldest_post_at",
        "newest_post_at",
        "errors",
        "note",
        "detail",
    ):
        if isinstance(crawl, dict) and key in crawl:
            print(f"{key}=", crawl.get(key))
    if isinstance(crawl, dict):
        print("account=", crawl.get("account"))
    out = r"C:\Users\SandrinePrumpelerRed\AppData\Local\Temp\crawl_result.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(crawl, handle, ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
