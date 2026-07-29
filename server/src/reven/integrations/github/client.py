"""Small bounded GitHub REST client for the blog publication workflow."""

import json
from html.parser import HTMLParser
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import quote, urljoin, urlsplit

import httpx

MAX_RESPONSE = 2 * 1024 * 1024


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, uncertain: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class GitHubClient:
    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        *,
        site_url: str = "https://www.wangyiyang.cc",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not owner or not repo or "/" in owner or "/" in repo:
            raise ValueError("GitHub 仓库标识无效")
        self.owner, self.repo = owner, repo
        self.site_url = site_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(20),
            follow_redirects=False,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._owns_client = client is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def default_branch(self) -> str:
        payload = await self._json("GET", self._repo_path)
        branch = payload.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubError("GitHub 未返回默认分支")
        return branch

    async def branch(self, name: str) -> dict[str, Any] | None:
        return await self._optional("GET", f"{self._repo_path}/branches/{quote(name, safe='')}")

    async def pull_requests(self, head: str, *, state: str = "all") -> list[dict[str, Any]]:
        payload = await self._json(
            "GET", f"{self._repo_path}/pulls", params={"head": f"{self.owner}:{head}", "state": state}
        )
        return cast(list[dict[str, Any]], payload)

    async def create_pull_request(self, *, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._json(
                "POST", f"{self._repo_path}/pulls", json={"title": title, "head": head, "base": base, "body": body}
            ),
        )

    async def required_contexts(self, branch: str) -> tuple[str, ...]:
        payload = await self._optional(
            "GET", f"{self._repo_path}/branches/{quote(branch, safe='')}/protection/required_status_checks"
        )
        if payload is None:
            return ()
        contexts = payload.get("contexts", [])
        return tuple(item for item in contexts if isinstance(item, str))

    async def check_runs(self, sha: str) -> list[dict[str, Any]]:
        payload = await self._json("GET", f"{self._repo_path}/commits/{quote(sha, safe='')}/check-runs")
        runs = payload.get("check_runs", [])
        return cast(list[dict[str, Any]], runs)

    async def status_contexts(self, sha: str) -> list[dict[str, Any]]:
        payload = await self._json("GET", f"{self._repo_path}/commits/{quote(sha, safe='')}/status")
        return cast(list[dict[str, Any]], payload.get("statuses", []))

    async def merge(self, number: int, sha: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._json(
                "PUT", f"{self._repo_path}/pulls/{number}/merge", json={"sha": sha, "merge_method": "merge"}
            ),
        )

    async def pages_builds(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._json("GET", f"{self._repo_path}/pages/builds"))

    async def pull_request_template(self, default_branch: str) -> str | None:
        candidates = (
            ".github/pull_request_template.md",
            "pull_request_template.md",
            "docs/pull_request_template.md",
        )
        for path in candidates:
            payload = await self._optional(
                "GET",
                f"{self._repo_path}/contents/{path}",
                params={"ref": default_branch},
            )
            if payload is not None:
                decoded = _decoded_content(payload)
                if decoded is not None:
                    return decoded
        directory = await self._json(
            "GET",
            f"{self._repo_path}/contents/.github/PULL_REQUEST_TEMPLATE",
            params={"ref": default_branch},
            allow_not_found=True,
        )
        if isinstance(directory, list):
            markdown = next(
                (
                    item.get("path")
                    for item in directory
                    if isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                    and str(item["path"]).lower().endswith(".md")
                ),
                None,
            )
            if isinstance(markdown, str):
                payload = await self._optional(
                    "GET",
                    f"{self._repo_path}/contents/{markdown}",
                    params={"ref": default_branch},
                )
                if payload is not None:
                    return _decoded_content(payload)
        return None

    async def verify_article(self, path: str, title: str) -> str:
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise ValueError("文章路径无效")
        expected = f"{self.site_url}{path}"
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response, body = await _bounded_get(client, expected)
            if response.is_redirect:
                location = urljoin(expected, response.headers.get("location", ""))
                if _origin(location) != _origin(self.site_url):
                    raise ValueError("文章重定向越过固定站点 origin")
                response, body = await _bounded_get(client, location)
        response.raise_for_status()
        parser = _Text()
        parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
        if " ".join("".join(parser.parts).split()).find(" ".join(title.split())) < 0:
            raise GitHubError("线上文章未包含预期标题")
        return str(response.url)

    async def _optional(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return cast(dict[str, Any], await self._json(method, path, **kwargs))
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise

    async def _json(self, method: str, path: str, *, allow_not_found: bool = False, **kwargs: Any) -> Any:
        try:
            request = self._client.build_request(method, path, **kwargs)
            response = await self._client.send(request, stream=True)
            body = await _bounded_body(response)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubError("GitHub 请求失败", uncertain=method not in {"GET", "HEAD"}) from exc
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API 返回 {response.status_code}", status=response.status_code)
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubError("GitHub 响应格式无效") from exc

    @property
    def _repo_path(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname or "", parsed.port


async def _bounded_body(response: httpx.Response) -> bytes:
    body = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE:
                raise GitHubError("HTTP 响应超过大小上限")
    finally:
        await response.aclose()
    return bytes(body)


async def _bounded_get(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, bytes]:
    response = await client.send(client.build_request("GET", url), stream=True)
    return response, await _bounded_body(response)


def _decoded_content(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, str) or payload.get("encoding") != "base64":
        return None
    import base64

    return base64.b64decode(content, validate=True).decode("utf-8")
