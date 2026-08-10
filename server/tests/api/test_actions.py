import asyncio

from reven.domain import JobStatus
from reven.jobs.models import PublicationJob
from sqlalchemy.ext.asyncio import async_sessionmaker

from .test_articles import _seed_pair


def test_retry_rejects_successful_channel(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status=JobStatus.COMPLETED, blog_status="已上线"))

    response = client.post(
        f"/api/articles/{article.id}/jobs/{job.id}/retry",
        json={"channels": ["个人博客"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "JOB_NOT_RETRYABLE"


def test_retry_resets_only_failed_target_and_increments_revision(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status=JobStatus.FAILED, blog_status="失败"))
    job.snapshot_metadata = {
        "delivery_finalization": {"final_status": "失败", "notion_pending": False},
        "delivery_notification_events": [{"event": "old"}],
    }
    job.notification_state = {"_preparation_terminal_marker": "blocked:same-version:same-error"}
    asyncio.run(_persist_job(factory, job))

    response = client.post(
        f"/api/articles/{article.id}/jobs/{job.id}/retry",
        json={"channels": ["个人博客"]},
    )

    assert response.status_code == 200
    detail = client.get(f"/api/articles/{article.id}/jobs/{job.id}").json()
    assert detail["overall_status"] == "等待中"
    assert detail["blog_status"] == "待处理"
    assert detail["wechat_status"] == "草稿已生成"
    stored = asyncio.run(_load_job(factory, job.id))
    assert "delivery_finalization" not in stored.snapshot_metadata
    assert stored.notification_state["_revision"] == 1
    assert "_preparation_terminal_marker" not in stored.notification_state


def test_retry_explicitly_resumes_a_preparation_blocked_job(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status=JobStatus.BLOCKED, blog_status="待处理"))

    response = client.post(
        f"/api/articles/{article.id}/jobs/{job.id}/retry",
        json={"channels": ["个人博客"]},
    )

    assert response.status_code == 200
    stored = asyncio.run(_load_job(factory, job.id))
    assert stored.overall_status == JobStatus.WAITING
    assert stored.scheduled_at >= job.scheduled_at


async def _persist_job(factory, job) -> None:  # type: ignore[no-untyped-def]
    async with factory.begin() as session:
        await session.merge(job)


async def _load_job(factory: async_sessionmaker, job_id) -> PublicationJob:  # type: ignore[no-untyped-def]
    async with factory() as session:
        job = await session.get(PublicationJob, job_id)
        assert job is not None
        return job


def test_cancel_only_accepts_not_started_waiting_job(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status=JobStatus.WAITING, blog_status="待处理"))

    ok = client.post(f"/api/articles/{article.id}/jobs/{job.id}/cancel")
    second = client.post(f"/api/articles/{article.id}/jobs/{job.id}/cancel")

    assert ok.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "JOB_NOT_CANCELLABLE"


def test_retry_rejects_duplicate_or_unknown_channels(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status=JobStatus.FAILED, blog_status="失败"))
    path = f"/api/articles/{article.id}/jobs/{job.id}/retry"

    duplicate = client.post(path, json={"channels": ["个人博客", "个人博客"]})
    unknown = client.post(path, json={"channels": ["未知渠道"]})

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CHANNEL_DUPLICATED"
    assert unknown.status_code == 409
    assert unknown.json()["code"] == "CHANNEL_UNSUPPORTED"
