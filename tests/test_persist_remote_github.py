"""GitHub Contents provider for HAMSTER remote persist."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from maaike.persist_remote import (
    _get_github,
    _provider_for_url,
    _put_github,
    content_fingerprint,
)


class _Resp:
    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")

    def json(self):
        if isinstance(self._payload, dict):
            return self._payload
        return json.loads(self.text)


def test_provider_detects_github_contents_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAAIKE_PERSIST_PROVIDER", raising=False)
    url = "https://api.github.com/repos/SandrinePr/hamster-persist/contents/hamster-maaike-backup.json"
    assert _provider_for_url(url) == "github"
    assert _provider_for_url("https://example.com/backup.json") == "http"


def test_put_and_get_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAAIKE_PERSIST_TOKEN", "fake-token")
    url = "https://api.github.com/repos/SandrinePr/hamster-persist/contents/hamster-maaike-backup.json"
    package = {
        "format": "maaike_export_v1",
        "secrets_excluded": True,
        "clients": [{"id": 1, "name": "Red Rock"}],
        "posts": [],
    }
    payload = json.dumps(package, ensure_ascii=False).encode("utf-8")
    calls: list[tuple[str, str]] = []

    def fake_request(method, request_url, **kwargs):
        calls.append((method, request_url))
        if method == "get":
            return _Resp(404)
        assert method == "put"
        body = kwargs.get("json") or {}
        assert body.get("content")
        assert "sha" not in body  # create path
        return _Resp(201, {"content": {"sha": "abc"}})

    monkeypatch.setattr(
        "maaike.persist_remote.requests.get",
        lambda *a, **k: fake_request("get", a[0] if a else k.get("url"), **k),
    )
    monkeypatch.setattr(
        "maaike.persist_remote.requests.put",
        lambda *a, **k: fake_request("put", a[0] if a else k.get("url"), **k),
    )
    put = _put_github(url, payload)
    assert put["ok"] is True

    encoded = base64.b64encode(payload).decode("ascii")

    def fake_get(*a, **k):
        return _Resp(200, {"content": encoded, "sha": "abc", "encoding": "base64"})

    monkeypatch.setattr("maaike.persist_remote.requests.get", fake_get)
    got = _get_github(url)
    assert got["ok"] is True
    assert got["data"]["clients"][0]["name"] == "Red Rock"


def test_fingerprint_ignores_exported_at() -> None:
    a = json.dumps({"exported_at": "1", "x": 1}, ensure_ascii=False).encode()
    b = json.dumps({"exported_at": "2", "x": 1}, ensure_ascii=False).encode()
    assert content_fingerprint(a) == content_fingerprint(b)


def test_get_github_uses_download_url_for_large_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAAIKE_PERSIST_TOKEN", "fake-token")
    url = "https://api.github.com/repos/SandrinePr/hamster-persist/contents/hamster-maaike-backup.json"
    package = {"format": "maaike_export_v1", "clients": [{"id": 1}], "posts": []}
    raw = json.dumps(package).encode("utf-8")

    def fake_get(request_url, **kwargs):
        if "raw.githubusercontent.com" in request_url or "download_url" in str(kwargs):
            return _Resp(200, text=raw.decode("utf-8"))
        if request_url.endswith("hamster-maaike-backup.json") or "/contents/" in request_url:
            return _Resp(
                200,
                {
                    "encoding": "none",
                    "content": "",
                    "sha": "big",
                    "size": len(raw),
                    "download_url": "https://raw.githubusercontent.com/example/hamster-maaike-backup.json",
                },
            )
        return _Resp(200, text=raw.decode("utf-8"))

    monkeypatch.setattr("maaike.persist_remote.requests.get", fake_get)
    got = _get_github(url)
    assert got["ok"] is True
    assert got["data"]["clients"][0]["id"] == 1
