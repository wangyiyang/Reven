from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from reven.integrations.github.client import (
    GitHubBlockedError,
    GitHubClient,
    GitHubError,
    GitHubPermanentError,
    GitHubTransientError,
    _next_page,
    validate_site_url,
)
from reven.publishing.blog.publisher import RequiredCheck


@pytest.mark.anyio
@respx.mock
async def test_client_loads_default_branch_and_checks_without_token_in_url() -> None:
    repo = respx.get("https://api.github.com/repos/acme/blog").mock(
        return_value=httpx.Response(200, json={"default_branch": "trunk"})
    )
    checks = respx.get("https://api.github.com/repos/acme/blog/commits/abc/check-runs").mock(
        return_value=httpx.Response(
            200, json={"check_runs": [{"name": "jekyll", "status": "completed", "conclusion": "success"}]}
        )
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        assert await client.default_branch() == "trunk"
        assert (await client.check_runs("abc"))[0]["name"] == "jekyll"
    assert "secret" not in str(repo.calls[0].request.url)
    assert checks.called


@pytest.mark.anyio
async def test_article_validation_rejects_cross_origin_redirect() -> None:
    async def resolver(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [(None, None, None, None, ("93.184.216.34", 443))]

    class RedirectRequester:
        @asynccontextmanager
        async def stream(self, url, pinned_ip):  # type: ignore[no-untyped-def]
            yield httpx.Response(
                302,
                headers={"location": "https://evil.example/post.html"},
                request=httpx.Request("GET", url),
            )

    async with GitHubClient(
        "acme",
        "blog",
        "secret",
        article_resolver=resolver,
        article_requester=RedirectRequester(),  # type: ignore[arg-type]
    ) as client:
        with pytest.raises(ValueError, match="重定向"):
            await client.verify_article("/post.html", "安全标题")


@pytest.mark.anyio
@respx.mock
async def test_client_parses_legacy_and_modern_required_checks() -> None:
    respx.get("https://api.github.com/repos/acme/blog/branches/trunk/protection/required_status_checks").mock(
        return_value=httpx.Response(
            200,
            json={
                "contexts": ["legacy"],
                "checks": [{"context": "Jekyll build", "app_id": 42}],
            },
        )
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        assert await client.required_contexts("trunk") == (
            RequiredCheck("legacy"),
            RequiredCheck("Jekyll build", 42),
        )


@pytest.mark.anyio
@respx.mock
async def test_pull_requests_follow_link_pagination_and_include_exact_base() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"number": 101, "state": "open"}])
        return httpx.Response(
            200,
            json=[{"number": index} for index in range(100)],
            headers={
                "link": (
                    "<https://api.github.com/repos/acme/blog/pulls?"
                    'page=2&per_page=100&head=acme%3Areven%2Fbranch&base=trunk&state=all>; rel="next"'
                )
            },
        )

    route = respx.get("https://api.github.com/repos/acme/blog/pulls").mock(side_effect=response)
    async with GitHubClient("acme", "blog", "secret") as client:
        pulls = await client.pull_requests("reven/branch", base="trunk")
    assert pulls[-1]["number"] == 101
    assert route.calls[0].request.url.params["head"] == "acme:reven/branch"
    assert route.calls[0].request.url.params["base"] == "trunk"
    assert route.calls[1].request.url.params["head"] == "acme:reven/branch"
    assert route.calls[1].request.url.params["base"] == "trunk"
    assert route.calls[1].request.url.params["page"] == "2"


def test_next_page_allows_omitted_original_filters() -> None:
    params = {"per_page": "100", "head": "acme:reven/branch", "base": "trunk", "state": "all"}
    assert (
        _next_page(
            '<https://api.github.com/repos/acme/blog/pulls?page=2>; rel="next"',
            1,
            "/repos/acme/blog/pulls",
            params,
        )
        == 2
    )


@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.example/repos/acme/blog/pulls?page=2>; rel="next"',
        '<https://user@api.github.com/repos/acme/blog/pulls?page=2>; rel="next"',
        '<https://api.github.com:444/repos/acme/blog/pulls?page=2>; rel="next"',
        '<https://api.github.com/repos/acme/blog/pulls?page=2&base=other>; rel="next"',
        '<https://api.github.com/repos/acme/blog/pulls?page=2&secret=x>; rel="next"',
        '<https://api.github.com/repos/acme/blog/pulls?page=2&page=3>; rel="next"',
        '<https://api.github.com/repos/acme/blog/pulls?page=2&base=trunk&base=trunk>; rel="next"',
    ],
)
def test_next_page_rejects_filter_and_query_confusion(link: str) -> None:
    params = {"per_page": "100", "head": "acme:reven/branch", "base": "trunk", "state": "all"}
    with pytest.raises(GitHubError, match="分页"):
        _next_page(link, 1, "/repos/acme/blog/pulls", params)


@pytest.mark.anyio
@respx.mock
async def test_pagination_rejects_cross_endpoint_link() -> None:
    respx.get("https://api.github.com/repos/acme/blog/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[],
            headers={
                "link": '<https://api.github.com/repos/acme/blog/issues?page=2>; rel="next"',
            },
        )
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        with pytest.raises(Exception, match="分页"):
            await client.pull_requests("reven/branch", base="trunk")


@pytest.mark.anyio
@respx.mock
async def test_pages_latest_uses_latest_endpoint() -> None:
    route = respx.get("https://api.github.com/repos/acme/blog/pages/builds/latest").mock(
        return_value=httpx.Response(200, json={"id": 9, "commit": "merge", "status": "built"})
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        assert (await client.latest_pages_build())["id"] == 9
    assert route.called


@pytest.mark.anyio
@respx.mock
async def test_get_pull_uses_exact_number_endpoint() -> None:
    route = respx.get("https://api.github.com/repos/acme/blog/pulls/7").mock(
        return_value=httpx.Response(200, json={"number": 7, "state": "open"})
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        assert (await client.get_pull(7))["number"] == 7
    assert route.called


@pytest.mark.parametrize(
    "url",
    [
        "https://user@www.wangyiyang.cc",
        "https://www.wangyiyang.cc:444",
        "https://www.wangyiyang.cc/path",
        "https://www.wangyiyang.cc?query=x",
        "https://127.0.0.1",
    ],
)
def test_site_url_is_fixed_product_origin(url: str) -> None:
    with pytest.raises(ValueError, match="站点"):
        validate_site_url(url)


@pytest.mark.anyio
async def test_article_dns_private_address_is_rejected_before_request() -> None:
    async def resolver(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [(None, None, None, None, ("127.0.0.1", 443))]

    class NeverRequester:
        def stream(self, url, pinned_ip):  # type: ignore[no-untyped-def]
            raise AssertionError("request must not start")

    async with GitHubClient(
        "acme",
        "blog",
        "secret",
        article_resolver=resolver,
        article_requester=NeverRequester(),  # type: ignore[arg-type]
    ) as client:
        with pytest.raises(ValueError, match="内部网络"):
            await client.verify_article("/post/", "标题")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (500, GitHubTransientError),
        (403, GitHubBlockedError),
        (404, GitHubPermanentError),
    ],
)
async def test_article_http_errors_use_github_classification(status: int, error: type[Exception]) -> None:
    async def resolver(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [(None, None, None, None, ("93.184.216.34", 443))]

    class Requester:
        @asynccontextmanager
        async def stream(self, url, pinned_ip):  # type: ignore[no-untyped-def]
            yield httpx.Response(status, request=httpx.Request("GET", url))

    async with GitHubClient(
        "acme",
        "blog",
        "secret",
        article_resolver=resolver,
        article_requester=Requester(),  # type: ignore[arg-type]
    ) as client:
        with pytest.raises(error):
            await client.verify_article("/post/", "标题")


@pytest.mark.anyio
async def test_article_network_failure_is_transient() -> None:
    async def resolver(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("secret DNS detail")

    async with GitHubClient("acme", "blog", "secret", article_resolver=resolver) as client:
        with pytest.raises(GitHubTransientError) as caught:
            await client.verify_article("/post/", "标题")
    assert "secret DNS detail" not in str(caught.value)


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, GitHubTransientError),
        (500, GitHubTransientError),
        (403, GitHubBlockedError),
        (422, GitHubPermanentError),
    ],
)
async def test_github_http_errors_are_classified(status: int, error: type[Exception]) -> None:
    respx.get("https://api.github.com/repos/acme/blog").mock(return_value=httpx.Response(status))
    async with GitHubClient("acme", "blog", "secret") as client:
        with pytest.raises(error):
            await client.default_branch()


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    "headers",
    [
        {"Retry-After": "10"},
        {"X-RateLimit-Remaining": "0"},
    ],
)
async def test_github_rate_limit_403_is_transient(headers: dict[str, str]) -> None:
    respx.get("https://api.github.com/repos/acme/blog").mock(return_value=httpx.Response(403, headers=headers))
    async with GitHubClient("acme", "blog", "secret") as client:
        with pytest.raises(GitHubTransientError):
            await client.default_branch()
