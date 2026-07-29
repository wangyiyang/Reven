import pytest
from reven.jobs.errors import BlockedPublishError
from reven.publishing.blog.publisher import BlogPublisher, checks_state, pull_request_body, release_branch


def test_release_branch_never_targets_default_branch() -> None:
    assert release_branch("11111111-2222", "a" * 64, "master") == "reven/11111111-aaaaaaaaaaaa"


def test_no_required_checks_is_blocked() -> None:
    with pytest.raises(BlockedPublishError, match="required"):
        checks_state((), [], [])


def test_required_check_run_and_status_contexts_must_all_succeed() -> None:
    assert (
        checks_state(
            ("Jekyll build", "security"),
            [{"name": "Jekyll build", "status": "completed", "conclusion": "success"}],
            [{"context": "security", "state": "success"}],
        )
        == "success"
    )
    with pytest.raises(BlockedPublishError, match="失败"):
        checks_state(
            ("Jekyll build",),
            [{"name": "Jekyll build", "status": "completed", "conclusion": "failure"}],
            [],
        )


def test_pull_request_fallback_has_pyramid_sections() -> None:
    body = pull_request_body(None, "_posts/post.md")
    assert body.startswith("## 目的")
    assert "## 改动" in body
    assert "## 验证" in body


@pytest.mark.anyio
async def test_existing_article_url_returns_without_external_calls() -> None:
    class Store:
        async def load(self, claim):  # type: ignore[no-untyped-def]
            return {
                "blog_result": {
                    "article_url": "https://www.wangyiyang.cc/post.html",
                    "pull_request_number": 7,
                    "merge_sha": "abc",
                }
            }

    class Never:
        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            raise AssertionError(f"unexpected external call: {name}")

    publisher = BlogPublisher(
        Never(),  # type: ignore[arg-type]
        Never(),  # type: ignore[arg-type]
        Never(),  # type: ignore[arg-type]
        Store(),  # type: ignore[arg-type]
        remote_url="https://github.com/acme/blog.git",
        token="secret",
    )
    result = await publisher.publish(object())  # type: ignore[arg-type]
    assert result.article_url.endswith("/post.html")
