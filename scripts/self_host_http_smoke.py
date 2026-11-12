"""HTTP/TLS assertions for the isolated self-host Compose smoke test."""

import hashlib
import json
import ssl
import time
from email.message import Message
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.cookies import Morsel, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


class FrontendAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        path = attributes.get("src" if tag == "script" else "href") if tag in {"script", "link"} else None
        if path and path.startswith("/assets/") and path.endswith((".js", ".css")):
            self.paths.add(path)


class Browser:
    def __init__(self, origin: str, *, ca_file: Path | None = None) -> None:
        self.origin = origin
        context = ssl.create_default_context(cafile=str(ca_file)) if ca_file else ssl.create_default_context()
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), HTTPSHandler(context=context))

    def request(
        self,
        path: str,
        *,
        expected: int = 200,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, Message]:
        payload = json.dumps(body).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(self.origin + path, data=payload, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected, f"{request.method} {path}: expected {expected}, got {response.status}"
            return response.read(), response.headers

    def login(self, password: str) -> str:
        deadline = time.monotonic() + 30
        while True:
            try:
                self.request("/api/health")
                break
            except (URLError, ConnectionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        body, _ = self.request("/")
        assert b"<html" in body.lower()
        self.request("/api/auth/me", expected=401)
        self.request("/agent/mcp", body={}, expected=404)
        for request_headers in ({}, {"Origin": self.origin}, {"X-Reven-CSRF": "1"}):
            self.request("/api/auth/login", body={"password": password}, headers=request_headers, expected=403)
        _, headers = self.request("/api/auth/login", body={"password": password}, headers=self.write_headers)
        cookie = SimpleCookie(headers["Set-Cookie"])["reven_session"]
        self._assert_cookie(cookie)
        self.request("/api/auth/me")
        self.request(
            "/api/auth/logout",
            body={},
            expected=403,
            headers={"Origin": "https://evil.example", "X-Reven-CSRF": "1"},
        )
        return cookie.value

    def assert_production_routes(self, index_digest: str) -> None:
        index, _ = self.request("/")
        assert b"<html" in index.lower() and hashlib.sha256(index).hexdigest() == index_digest
        for path in ("/", "/login", "/crm/customers/smoke-customer", "/rss/candidates"):
            body, headers = self.request(path)
            assert body == index and headers.get_content_type() == "text/html", path
            assert headers["Cache-Control"] == "no-cache", path
            self.assert_security_headers(headers)
        self.assert_assets(index)
        body, _ = self.request("/assets/__reven_smoke_missing__.js", expected=404)
        assert body != index
        self.request("/agent/mcp", expected=404)
        self.request("/agent/mcp", body={}, expected=404)
        body, headers = self.request("/api/health")
        assert headers.get_content_type() == "application/json"
        assert json.loads(body)["service"] == "reven" and json.loads(body)["status"] == "ok"
        self.assert_security_headers(headers)
        body, headers = self.request("/api/auth/me", expected=401)
        assert headers.get_content_type() == "application/json" and isinstance(json.loads(body), dict)
        self.assert_security_headers(headers)

    def assert_assets(self, index: bytes) -> None:
        assets = FrontendAssets()
        assets.feed(index.decode())
        assert any(path.endswith(".js") for path in assets.paths), "No built JavaScript in index"
        assert any(path.endswith(".css") for path in assets.paths), "No built CSS in index"
        for path in sorted(assets.paths):
            body, headers = self.request(path)
            expected = {"text/css"} if path.endswith(".css") else {"text/javascript", "application/javascript"}
            assert body and body != index and headers.get_content_type() in expected, path
            cache = {part.strip() for part in headers["Cache-Control"].split(",")}
            assert {"public", "max-age=31536000", "immutable"} <= cache, path
            self.assert_security_headers(headers)

    @staticmethod
    def assert_security_headers(headers: Message) -> None:
        expected = {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Frame-Options": "SAMEORIGIN",
        }
        for name, value in expected.items():
            assert headers.get_all(name) == [value], name
        policies = headers.get_all("Content-Security-Policy")
        assert policies and len(policies) == 1 and "default-src 'self'" in policies[0]

    @property
    def write_headers(self) -> dict[str, str]:
        return {"Origin": self.origin, "X-Reven-CSRF": "1"}

    def create_disabled_source(self) -> str:
        body, _ = self.request(
            "/api/rss/sources",
            expected=201,
            body={"name": "self-host smoke", "feed_url": "https://example.invalid/feed", "enabled": False},
            headers=self.write_headers,
        )
        source_id = json.loads(body)["id"]
        assert isinstance(source_id, str)
        return source_id

    def assert_persisted_source(self, source_id: str) -> None:
        self.request("/api/auth/me")
        body, _ = self.request("/api/rss/sources")
        assert any(source["id"] == source_id and not source["enabled"] for source in json.loads(body))

    def save_candidate(self, item_id: str) -> dict[str, Any]:
        body, _ = self.request("/api/rss/candidates")
        candidate = next(item for item in json.loads(body)["items"] if item["id"] == item_id)
        body, _ = self.request(f"/api/rss/candidates/{item_id}/confirm", body={}, headers=self.write_headers)
        saved = json.loads(body)
        assert isinstance(saved, dict) and saved["saved_at"] is not None
        assert saved == {**candidate, "status": "saved", "saved_at": saved["saved_at"]}
        self.assert_saved_candidate(saved)
        return saved

    def assert_saved_candidate(self, saved: dict[str, Any]) -> None:
        body, _ = self.request(f"/api/rss/candidates/{saved['id']}/confirm", body={}, headers=self.write_headers)
        assert json.loads(body) == saved
        body, _ = self.request("/api/rss/candidates?status=saved")
        materials = json.loads(body)
        assert materials["total"] == 1 and materials["items"] == [saved]
        body, _ = self.request("/api/rss/candidates")
        assert all(item["id"] != saved["id"] for item in json.loads(body)["items"])

    def logout(self, old_token: str) -> None:
        _, headers = self.request("/api/auth/logout", body={}, headers=self.write_headers, expected=204)
        cookie = SimpleCookie(headers["Set-Cookie"])["reven_session"]
        self._assert_cookie(cookie)
        assert cookie["max-age"] == "0"
        self.request("/api/auth/me", expected=401)
        self.request("/api/auth/me", headers={"Cookie": f"reven_session={old_token}"}, expected=401)

    def _assert_cookie(self, cookie: Morsel[str]) -> None:
        assert bool(cookie["secure"]) is self.origin.startswith("https://")
        assert cookie["httponly"] and cookie["samesite"] == "lax" and cookie["path"] == "/"
        assert not cookie["domain"]
