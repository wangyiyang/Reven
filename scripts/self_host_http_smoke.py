"""HTTP/TLS assertions for the isolated self-host Compose smoke test."""

import json
import ssl
import time
from email.message import Message
from http.cookiejar import CookieJar
from http.cookies import Morsel, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


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
        self.request("/api/auth/login", body={"password": password}, expected=403)
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
