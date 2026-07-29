"""Small bounded GitHub REST client for the blog publication workflow."""

import json
import re
import socket
from html.parser import HTMLParser
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

import httpx

from reven.publishing.assets import (
    HttpcorePinnedRequester,
    PinnedRequester,
    Resolver,
    _is_unsafe_address,
    default_resolver,
)

MAX_RESPONSE = 2 * 1024 * 1024
MAX_PAGES = 20
MAX_ITEMS = 2_000
MAX_REDIRECTS = 5


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, uncertain: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


class GitHubTransientError(GitHubError):
    pass


class GitHubBlockedError(GitHubError):
    pass


class GitHubPermanentError(GitHubError):
    pass


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
        article_resolver: Resolver = default_resolver,
        article_requester: PinnedRequester | None = None,
    ) -> None:
        if not owner or not repo or "/" in owner or "/" in repo:
            raise ValueError("GitHub 仓库标识无效")
        self.owner, self.repo = owner, repo
        self.site_url = validate_site_url(site_url)
        self.article_resolver = article_resolver
        self.article_requester = article_requester or HttpcorePinnedRequester()
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

    async def pull_requests(self, head: str, *, base: str, state: str = "all") -> list[dict[str, Any]]:
        return await self._paginate(
            f"{self._repo_path}/pulls",
            params={
                "head": f"{self.owner}:{head}",
                "base": base,
                "state": state,
                "per_page": "100",
            },
        )

    async def create_pull_request(self, *, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._json(
                "POST", f"{self._repo_path}/pulls", json={"title": title, "head": head, "base": base, "body": body}
            ),
        )

    async def get_pull(self, number: int) -> dict[str, Any]:
        if number <= 0:
            raise ValueError("PR number 无效")
        return cast(dict[str, Any], await self._json("GET", f"{self._repo_path}/pulls/{number}"))

    async def required_contexts(self, branch: str) -> tuple[Any, ...]:
        from reven.publishing.blog.publisher import RequiredCheck

        payload = await self._optional(
            "GET", f"{self._repo_path}/branches/{quote(branch, safe='')}/protection/required_status_checks"
        )
        if payload is None:
            return ()
        contexts = payload.get("contexts", [])
        required = [RequiredCheck(item) for item in contexts if isinstance(item, str)]
        modern = payload.get("checks", [])
        if isinstance(modern, list):
            for item in modern:
                if not isinstance(item, dict) or not isinstance(item.get("context"), str):
                    continue
                app_id = item.get("app_id")
                required.append(RequiredCheck(item["context"], app_id if isinstance(app_id, int) else None))
        return tuple(dict.fromkeys(required))

    async def check_runs(self, sha: str) -> list[dict[str, Any]]:
        return await self._paginate(
            f"{self._repo_path}/commits/{quote(sha, safe='')}/check-runs",
            params={"per_page": "100"},
            container="check_runs",
        )

    async def status_contexts(self, sha: str) -> list[dict[str, Any]]:
        return await self._paginate(
            f"{self._repo_path}/commits/{quote(sha, safe='')}/statuses",
            params={"per_page": "100"},
        )

    async def merge(self, number: int, sha: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._json(
                "PUT", f"{self._repo_path}/pulls/{number}/merge", json={"sha": sha, "merge_method": "merge"}
            ),
        )

    async def pages_builds(self) -> list[dict[str, Any]]:
        return await self._paginate(f"{self._repo_path}/pages/builds", params={"per_page": "100"})

    async def latest_pages_build(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._json("GET", f"{self._repo_path}/pages/builds/latest"))

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
        try:
            directory = await self._paginate(
                f"{self._repo_path}/contents/.github/PULL_REQUEST_TEMPLATE",
                params={"ref": default_branch, "per_page": "100"},
            )
        except GitHubPermanentError as exc:
            if exc.status != 404:
                raise
            directory = []
        if directory:
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
        current = expected
        for redirect in range(MAX_REDIRECTS + 1):
            pinned_ip = await self._article_ip(current)
            try:
                async with self.article_requester.stream(current, pinned_ip) as response:
                    body = await _bounded_body(response)
                    if response.is_redirect:
                        if redirect == MAX_REDIRECTS:
                            raise ValueError("文章重定向次数超限")
                        current = urljoin(current, response.headers.get("location", ""))
                        if _origin(current) != _origin(self.site_url):
                            raise ValueError("文章重定向越过固定站点 origin")
                        continue
                    _raise_for_status(response, "GET")
                    break
            except (httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
                raise GitHubTransientError("文章站点网络请求失败") from exc
        else:
            raise ValueError("文章重定向次数超限")
        parser = _Text()
        parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
        if " ".join("".join(parser.parts).split()).find(" ".join(title.split())) < 0:
            raise GitHubError("线上文章未包含预期标题")
        return current

    async def _article_ip(self, url: str) -> str:
        parsed = urlsplit(url)
        if _origin(url) != _origin(self.site_url):
            raise ValueError("文章 URL 越过固定站点 origin")
        try:
            addresses = await self.article_resolver(
                parsed.hostname or "",
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except (OSError, ValueError) as exc:
            raise GitHubTransientError("文章站点 DNS 解析失败") from exc
        ips = [str(item[-1][0]) for item in addresses if item and isinstance(item[-1], tuple)]
        if not ips or any(_is_unsafe_address(ip) for ip in ips):
            raise ValueError("文章站点解析到内部网络")
        return ips[0]

    async def _optional(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return cast(dict[str, Any], await self._json(method, path, **kwargs))
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise

    async def _paginate(
        self,
        path: str,
        *,
        params: dict[str, str],
        container: str | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        seen: set[int] = set()
        while page:
            if page in seen or len(seen) >= MAX_PAGES:
                raise GitHubError("GitHub 分页链接循环或超过页数上限")
            seen.add(page)
            request_params = {**params, "page": str(page)}
            payload, next_page = await self._json_with_next(path, params=request_params, current_page=page)
            page_items = payload.get(container, []) if container and isinstance(payload, dict) else payload
            if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
                raise GitHubError("GitHub 分页响应格式无效")
            items.extend(cast(list[dict[str, Any]], page_items))
            if len(items) > MAX_ITEMS:
                raise GitHubError("GitHub 分页结果超过数量上限")
            page = next_page or 0
        return items

    async def _json_with_next(
        self,
        path: str,
        *,
        params: dict[str, str],
        current_page: int,
    ) -> tuple[Any, int | None]:
        response, body = await self._request("GET", path, params=params)
        _raise_for_status(response, "GET")
        payload = _decode_json(body)
        return payload, _next_page(response.headers.get("link"), path, current_page)

    async def _json(self, method: str, path: str, *, allow_not_found: bool = False, **kwargs: Any) -> Any:
        response, body = await self._request(method, path, **kwargs)
        if allow_not_found and response.status_code == 404:
            return None
        _raise_for_status(response, method)
        try:
            return _decode_json(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubError("GitHub 响应格式无效") from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[httpx.Response, bytes]:
        try:
            request = self._client.build_request(method, path, **kwargs)
            response = await self._client.send(request, stream=True)
            return response, await _bounded_body(response)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubTransientError(
                "GitHub 网络请求失败",
                uncertain=method not in {"GET", "HEAD"},
            ) from exc

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


def _decoded_content(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, str) or payload.get("encoding") != "base64":
        return None
    import base64

    return base64.b64decode(content, validate=True).decode("utf-8")


def _decode_json(body: bytes) -> Any:
    return json.loads(body)


def _next_page(header: str | None, endpoint_path: str, current_page: int) -> int | None:
    if not header:
        return None
    match = re.search(r'<([^>]+)>;\s*rel="next"', header)
    if match is None:
        return None
    url = match.group(1)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.path != endpoint_path:
        raise GitHubError("GitHub 分页链接越界")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if set(query) - {"page", "per_page"} or not query.get("page", "").isdigit():
        raise GitHubError("GitHub 分页参数无效")
    page = int(query["page"])
    if page <= current_page:
        raise GitHubError("GitHub 分页页码重复或倒退")
    return page


def validate_site_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.wangyiyang.cc"
        or parsed.netloc not in {"www.wangyiyang.cc", "www.wangyiyang.cc:443"}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("博客站点必须是固定产品 HTTPS origin")
    return "https://www.wangyiyang.cc"


def _raise_for_status(response: httpx.Response, method: str) -> None:
    status = response.status_code
    if status < 400:
        return
    message = f"GitHub API 返回 {status}"
    uncertain = method not in {"GET", "HEAD"}
    if status == 429 or status >= 500:
        raise GitHubTransientError(message, status=status, uncertain=uncertain)
    if status in {401, 403}:
        raise GitHubBlockedError(message, status=status)
    raise GitHubPermanentError(message, status=status)
