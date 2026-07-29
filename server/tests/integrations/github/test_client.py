import httpx
import pytest
import respx
from reven.integrations.github.client import GitHubClient


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
@respx.mock
async def test_article_validation_rejects_cross_origin_redirect() -> None:
    respx.get("https://www.wangyiyang.cc/post.html").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example/post.html"})
    )
    async with GitHubClient("acme", "blog", "secret", site_url="https://www.wangyiyang.cc") as client:
        with pytest.raises(ValueError, match="重定向"):
            await client.verify_article("/post.html", "安全标题")
