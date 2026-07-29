from uuid import uuid4

import pytest
from reven.integrations.github.client import GitHubTransientError
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.blog.publisher import (
    BlogPublisher,
    RequiredCheck,
    checks_state,
    pages_state,
    pull_request_body,
    release_branch,
    select_pull_request,
    verify_remote_branch,
)


def test_release_branch_never_targets_default_branch() -> None:
    assert release_branch("11111111-2222", "a" * 64, "master") == "reven/11111111-aaaaaaaaaaaa"


def test_no_required_checks_is_blocked() -> None:
    with pytest.raises(BlockedPublishError, match="required"):
        checks_state((), [], [])


def test_required_check_run_and_status_contexts_must_all_succeed() -> None:
    assert (
        checks_state(
            (RequiredCheck("Jekyll build"), RequiredCheck("security")),
            [{"name": "Jekyll build", "status": "completed", "conclusion": "success"}],
            [{"context": "security", "state": "success"}],
        )
        == "success"
    )
    with pytest.raises(BlockedPublishError, match="失败"):
        checks_state(
            (RequiredCheck("Jekyll build"),),
            [{"name": "Jekyll build", "status": "completed", "conclusion": "failure"}],
            [],
        )


def test_required_app_check_rejects_status_and_other_app_with_same_name() -> None:
    required = (RequiredCheck("Jekyll build", 42),)
    assert (
        checks_state(
            required,
            [
                {
                    "id": 2,
                    "name": "Jekyll build",
                    "app": {"id": 7},
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
            [{"id": 99, "context": "Jekyll build", "state": "success"}],
        )
        == "pending"
    )


def test_latest_rerun_wins_for_same_required_identity() -> None:
    required = (RequiredCheck("Jekyll build", 42),)
    assert (
        checks_state(
            required,
            [
                {
                    "id": 1,
                    "name": "Jekyll build",
                    "app": {"id": 42},
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 2,
                    "name": "Jekyll build",
                    "app": {"id": 42},
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
            [],
        )
        == "success"
    )
    with pytest.raises(BlockedPublishError, match="失败"):
        checks_state(
            required,
            [
                {
                    "id": 3,
                    "name": "Jekyll build",
                    "app": {"id": 42},
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 2,
                    "name": "Jekyll build",
                    "app": {"id": 42},
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
            [],
        )


def test_legacy_context_uses_timestamp_across_status_and_check_run_ids() -> None:
    assert (
        checks_state(
            (RequiredCheck("Jekyll build"),),
            [
                {
                    "id": 1,
                    "name": "Jekyll build",
                    "app": {"id": 42},
                    "completed_at": "2026-07-30T01:00:00Z",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
            [
                {
                    "id": 999,
                    "context": "Jekyll build",
                    "created_at": "2026-07-29T01:00:00Z",
                    "state": "failure",
                }
            ],
        )
        == "success"
    )


def test_select_pr_never_reuses_closed_unmerged() -> None:
    assert select_pull_request([{"number": 1, "state": "closed", "merged_at": None}]) is None
    assert select_pull_request(
        [
            {"number": 2, "state": "closed", "merged_at": "today"},
            {"number": 3, "state": "open", "merged_at": None},
        ]
    ) == {"number": 3, "state": "open", "merged_at": None}


def test_remote_branch_must_equal_fenced_local_commit() -> None:
    assert verify_remote_branch("abc", {"commit": {"sha": "abc"}}) == "abc"
    with pytest.raises(BlockedPublishError, match="冲突"):
        verify_remote_branch("abc", {"commit": {"sha": "old"}})


def test_pages_latest_never_accepts_historical_or_other_commit() -> None:
    assert pages_state({"commit": "other", "status": "built"}, "merge") == "pending"
    assert pages_state({"commit": "merge", "status": "built"}, "merge") == "success"
    with pytest.raises(BlockedPublishError, match="Pages"):
        pages_state({"commit": "other", "status": "errored"}, "merge")


@pytest.mark.anyio
async def test_merge_response_lost_recovers_only_from_merged_pr_query() -> None:
    class Client:
        def __init__(self) -> None:
            self.queries = 0

        async def pull_requests(self, head, *, base, state="all"):  # type: ignore[no-untyped-def]
            self.queries += 1
            if self.queries == 1:
                return [{"number": 7, "state": "open", "merged_at": None}]
            return [
                {
                    "number": 7,
                    "state": "closed",
                    "merged_at": "2026-07-30",
                    "merge_commit_sha": "merge-sha",
                }
            ]

        async def merge(self, number, sha):  # type: ignore[no-untyped-def]
            raise GitHubTransientError("lost", uncertain=True)

    class Store:
        async def save_result(self, claim, patch):  # type: ignore[no-untyped-def]
            result.update(patch)
            return True

        async def clear_operation(self, claim, operation_id):  # type: ignore[no-untyped-def]
            return True

    class Never:
        pass

    result: dict[str, object] = {}
    publisher = BlogPublisher(
        Client(),  # type: ignore[arg-type]
        Never(),  # type: ignore[arg-type]
        Never(),  # type: ignore[arg-type]
        Store(),  # type: ignore[arg-type]
        remote_url="https://github.com/acme/blog.git",
        token="secret",
    )
    claim = JobClaim(uuid4(), uuid4())
    assert await publisher._ensure_merge(claim, result, 7, "head-sha", "reven/branch", "trunk") == "merge-sha"
    assert result["merge_sha"] == "merge-sha"


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
