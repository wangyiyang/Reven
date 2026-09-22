"""审核按钮回调执行：白名单门禁、核心层错误映射、线程桥接兜底、重复处理幂等 toast。"""

import asyncio
import base64
import hashlib
import logging
from datetime import date
from uuid import UUID

import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.review_callback import (
    TOAST_ALREADY_HANDLED,
    TOAST_APPROVED,
    TOAST_FAILED,
    TOAST_FORBIDDEN,
    TOAST_IGNORED,
    TOAST_INVALID,
    ReviewCallbackDispatcher,
    run_review_action,
)
from reven.integrations.models import Integration
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.review_service import CandidateReviewError, CandidateReviewService
from reven.security.secrets import SecretBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()
ITEM_ID = UUID("12345678-1234-5678-1234-567812345678")
WHITELIST = ("ou_boss",)


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


def _credentials(session: AsyncSession) -> IntegrationCredentials:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
    )
    return IntegrationCredentials(_factory(session), settings)


class FakeExecutor:
    """记录调用的假核心层；可设定 approve/ignore 抛错。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, UUID]] = []
        self._error = error

    async def approve(self, item_id: UUID) -> None:
        self.calls.append(("approve", item_id))
        if self._error is not None:
            raise self._error

    async def ignore(self, item_id: UUID) -> None:
        self.calls.append(("ignore", item_id))
        if self._error is not None:
            raise self._error


async def _write_bot_config(
    session: AsyncSession,
    *,
    enabled: bool = True,
    whitelist: tuple[str, ...] = WHITELIST,
) -> None:
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={"whitelist_open_ids": list(whitelist), "enabled": enabled},
            encrypted_secret=_secret_box().encrypt({"app_id": "cli_test", "app_secret": "s3cret"}),
        )
    )
    await session.commit()


def _dispatcher(session: AsyncSession, executor: object) -> ReviewCallbackDispatcher:
    return ReviewCallbackDispatcher(_credentials(session), executor)  # type: ignore[arg-type]


async def _seed_candidate(session: AsyncSession) -> UUID:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 9, 19))
    session.add_all([source, run])
    await session.flush()
    digest = hashlib.sha256(b"seed").hexdigest()
    item = RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid="candidate-seed",
        url="https://example.com/seed",
        url_key=digest,
        guid_key=digest,
        title_key=digest,
        title="Title",
        title_zh="标题",
        status="candidate",
    )
    session.add(item)
    await session.commit()
    return item.id


# --- run_review_action：纯异步审核映射 ---


@pytest.mark.anyio
async def test_approve_success_maps_to_approved_toast() -> None:
    executor = FakeExecutor()

    outcome = await run_review_action(
        executor, WHITELIST, action="approve", item_id=ITEM_ID, operator_open_id="ou_boss"
    )

    assert outcome is TOAST_APPROVED
    assert outcome.toast_type == "success"
    assert outcome.text == "已保存素材"
    assert executor.calls == [("approve", ITEM_ID)]


@pytest.mark.anyio
async def test_ignore_success_maps_to_ignored_toast() -> None:
    executor = FakeExecutor()

    outcome = await run_review_action(executor, WHITELIST, action="ignore", item_id=ITEM_ID, operator_open_id="ou_boss")

    assert outcome is TOAST_IGNORED
    assert outcome.toast_type == "success"
    assert outcome.text == "已忽略"
    assert executor.calls == [("ignore", ITEM_ID)]


@pytest.mark.anyio
@pytest.mark.parametrize("operator_open_id", ["ou_stranger", None])
async def test_non_whitelisted_operator_is_rejected_without_touching_core(
    operator_open_id: str | None,
) -> None:
    executor = FakeExecutor()

    outcome = await run_review_action(
        executor, WHITELIST, action="approve", item_id=ITEM_ID, operator_open_id=operator_open_id
    )

    assert outcome is TOAST_FORBIDDEN
    assert outcome.toast_type == "error"
    assert outcome.text == "无审核权限"
    assert executor.calls == []


@pytest.mark.anyio
async def test_empty_whitelist_rejects_everyone() -> None:
    executor = FakeExecutor()

    outcome = await run_review_action(executor, (), action="ignore", item_id=ITEM_ID, operator_open_id="ou_boss")

    assert outcome is TOAST_FORBIDDEN
    assert executor.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["approve", "ignore"])
@pytest.mark.parametrize(
    "error",
    [
        CandidateReviewError("RSS_CANDIDATE_NOT_FOUND", "候选不存在", status_code=404),
        CandidateReviewError("RSS_CANDIDATE_NOT_IGNORABLE", "状态不允许忽略"),
        CandidateReviewError("RSS_CANDIDATE_NOT_SAVABLE", "状态不允许保存"),
    ],
)
async def test_domain_404_409_maps_to_already_handled_toast(action: str, error: Exception) -> None:
    executor = FakeExecutor(error)

    outcome = await run_review_action(executor, WHITELIST, action=action, item_id=ITEM_ID, operator_open_id="ou_boss")

    assert outcome is TOAST_ALREADY_HANDLED
    assert outcome.toast_type == "info"
    assert outcome.text == "该候选已处理"
    assert executor.calls == [(action, ITEM_ID)]


@pytest.mark.anyio
async def test_domain_503_maps_to_failed_toast() -> None:
    executor = FakeExecutor(CandidateReviewError("RSS_REVIEW_UNAVAILABLE", "审核暂不可用", status_code=503))

    outcome = await run_review_action(
        executor, WHITELIST, action="approve", item_id=ITEM_ID, operator_open_id="ou_boss"
    )

    assert outcome is TOAST_FAILED
    assert outcome.toast_type == "error"
    assert outcome.text == "操作失败，请稍后重试"


@pytest.mark.anyio
async def test_unexpected_error_maps_to_failed_toast_and_log_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = FakeExecutor(RuntimeError("database-credential-value"))

    with caplog.at_level(logging.WARNING):
        outcome = await run_review_action(
            executor, WHITELIST, action="approve", item_id=ITEM_ID, operator_open_id="ou_boss"
        )

    assert outcome is TOAST_FAILED
    assert "RuntimeError" in caplog.text
    assert "database-credential-value" not in caplog.text  # 日志脱敏：只记异常类型


@pytest.mark.anyio
async def test_unknown_action_never_touches_core() -> None:
    executor = FakeExecutor()

    outcome = await run_review_action(executor, WHITELIST, action="delete", item_id=ITEM_ID, operator_open_id="ou_boss")

    assert outcome is TOAST_INVALID
    assert executor.calls == []


# --- ReviewCallbackDispatcher：配置加载 + 线程桥接 ---


@pytest.mark.anyio
async def test_dispatcher_executes_core_action_for_whitelisted_operator(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    executor = FakeExecutor()
    dispatcher = _dispatcher(db_session, executor)
    dispatcher.bind_loop(asyncio.get_running_loop())

    outcome = await asyncio.to_thread(dispatcher, "ignore", ITEM_ID, "ou_boss")

    assert outcome is TOAST_IGNORED
    assert executor.calls == [("ignore", ITEM_ID)]


@pytest.mark.anyio
async def test_dispatcher_rejects_when_config_missing(db_session: AsyncSession) -> None:
    executor = FakeExecutor()
    dispatcher = _dispatcher(db_session, executor)
    dispatcher.bind_loop(asyncio.get_running_loop())

    outcome = await asyncio.to_thread(dispatcher, "approve", ITEM_ID, "ou_boss")

    assert outcome is TOAST_FORBIDDEN  # 配置缺失视为不在白名单
    assert executor.calls == []


@pytest.mark.anyio
async def test_dispatcher_rejects_when_config_disabled(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=False)
    executor = FakeExecutor()
    dispatcher = _dispatcher(db_session, executor)
    dispatcher.bind_loop(asyncio.get_running_loop())

    outcome = await asyncio.to_thread(dispatcher, "approve", ITEM_ID, "ou_boss")

    assert outcome is TOAST_FORBIDDEN
    assert executor.calls == []


@pytest.mark.anyio
async def test_dispatcher_rejects_non_whitelisted_operator(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    executor = FakeExecutor()
    dispatcher = _dispatcher(db_session, executor)
    dispatcher.bind_loop(asyncio.get_running_loop())

    outcome = await asyncio.to_thread(dispatcher, "approve", ITEM_ID, "ou_stranger")

    assert outcome is TOAST_FORBIDDEN
    assert executor.calls == []


@pytest.mark.anyio
async def test_dispatcher_without_bound_loop_returns_failed_toast(db_session: AsyncSession) -> None:
    dispatcher = _dispatcher(db_session, FakeExecutor())

    outcome = dispatcher("approve", ITEM_ID, "ou_boss")

    assert outcome is TOAST_FAILED


@pytest.mark.anyio
async def test_dispatcher_bridge_failure_returns_failed_toast(db_session: AsyncSession) -> None:
    dispatcher = _dispatcher(db_session, FakeExecutor())
    dead_loop = asyncio.new_event_loop()
    dead_loop.close()
    dispatcher.bind_loop(dead_loop)

    outcome = await asyncio.to_thread(dispatcher, "approve", ITEM_ID, "ou_boss")

    assert outcome is TOAST_FAILED


@pytest.mark.anyio
async def test_repeated_ignore_clicks_are_idempotent(db_session: AsyncSession) -> None:
    """真实核心层走通重复点击：第一次忽略成功，第二次幂等返回成功 toast。"""
    await _write_bot_config(db_session)
    item_id = await _seed_candidate(db_session)
    service = CandidateReviewService(_factory(db_session))
    dispatcher = _dispatcher(db_session, service)
    dispatcher.bind_loop(asyncio.get_running_loop())

    first = await asyncio.to_thread(dispatcher, "ignore", item_id, "ou_boss")
    second = await asyncio.to_thread(dispatcher, "ignore", item_id, "ou_boss")

    assert first is TOAST_IGNORED
    assert second is TOAST_IGNORED
    status = await db_session.scalar(select(RssItem.status).where(RssItem.id == item_id))
    assert status == "ignored"


@pytest.mark.anyio
async def test_approve_clicks_save_material_without_notion_and_preserve_timestamp(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    item_id = await _seed_candidate(db_session)
    dispatcher = _dispatcher(db_session, CandidateReviewService(_factory(db_session)))
    dispatcher.bind_loop(asyncio.get_running_loop())

    forbidden = await asyncio.to_thread(dispatcher, "approve", item_id, "ou_stranger")
    assert forbidden is TOAST_FORBIDDEN
    assert await db_session.scalar(select(RssItem.status).where(RssItem.id == item_id)) == "candidate"
    first = await asyncio.to_thread(dispatcher, "approve", item_id, "ou_boss")
    saved_at = await db_session.scalar(select(RssItem.saved_at).where(RssItem.id == item_id))
    second = await asyncio.to_thread(dispatcher, "approve", item_id, "ou_boss")
    ignored = await asyncio.to_thread(dispatcher, "ignore", item_id, "ou_boss")

    assert first is second is TOAST_APPROVED
    assert first.text == "已保存素材"
    assert ignored is TOAST_ALREADY_HANDLED
    assert saved_at is not None
    assert await db_session.scalar(select(RssItem.saved_at).where(RssItem.id == item_id)) == saved_at
    assert await db_session.scalar(select(RssItem.status).where(RssItem.id == item_id)) == "saved"
    assert list(await db_session.scalars(select(Integration.provider))) == ["feishu_bot"]
