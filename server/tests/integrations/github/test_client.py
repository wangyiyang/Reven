from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from reven.integrations.github.client import (
    GitHubBlockedError,
    GitHubClient,
    GitHubPermanentError,
    GitHubTransientError,
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
            headers={"link": '<https://api.github.com/repos/acme/blog/pulls?page=2>; rel="next"'},
        )

    route = respx.get("https://api.github.com/repos/acme/blog/pulls").mock(side_effect=response)
    async with GitHubClient("acme", "blog", "secret") as client:
        pulls = await client.pull_requests("reven/branch", base="trunk")
    assert pulls[-1]["number"] == 101
    assert route.calls[0].request.url.params["head"] == "acme:reven/branch"
    assert route.calls[0].request.url.params["base"] == "trunk"


@pytest.mark.anyio
@respx.mock
async def test_pages_latest_uses_latest_endpoint() -> None:
    route = respx.get("https://api.github.com/repos/acme/blog/pages/builds/latest").mock(
        return_value=httpx.Response(200, json={"id": 9, "commit": "merge", "status": "built"})
    )
    async with GitHubClient("acme", "blog", "secret") as client:
        assert (await client.latest_pages_build())["id"] == 9
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
