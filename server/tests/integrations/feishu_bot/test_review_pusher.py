"""ReviewCardPusher：配置/白名单/候选门禁跳过，正常推送落标记，部分失败只标记成功批，异常不抛出。"""

import base64
import hashlib
import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from reven.integrations.feishu_bot.client import FeishuBotApiError
from reven.integrations.feishu_bot.review_pusher import ReviewCardPusher
from reven.integrations.models import Integration
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.review_service import CandidateReviewService
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeSender:
    """异步假发送器：记录 (open_id, card)，可设定第 N 次调用抛错。"""

    def __init__(self, *, fail_at_calls: set[int] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail_at = fail_at_calls or set()

    async def send_review_card(self, open_id: str, card: dict[str, Any]) -> None:
        self.calls.append((open_id, card))
        if len(self.calls) in self._fail_at:
            raise FeishuBotApiError("飞书审核卡片发送失败（code=999）")


class SenderFactoryStub:
    def __init__(self, sender: FakeSender) -> None:
        self.sender = sender
        self.credentials: list[tuple[str, str]] = []

    def __call__(self, app_id: str, app_secret: str) -> FakeSender:
        self.credentials.append((app_id, app_secret))
        return self.sender


async def _write_bot_config(
    session: AsyncSession,
    *,
    enabled: bool = True,
    whitelist: object = ["ou_boss"],
) -> None:
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={"whitelist_open_ids": whitelist, "enabled": enabled},
            encrypted_secret=_secret_box().encrypt({"app_id": "cli_test", "app_secret": "s3cret"}),
        )
    )
    await session.commit()


async def _seed_candidates(session: AsyncSession, count: int) -> list[RssItem]:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 9, 19))
    session.add_all([source, run])
    await session.flush()
    items = [
        RssItem(
            source_id=source.id,
            first_seen_run_id=run.id,
            source_name=source.name,
            guid=f"candidate-{index}",
            url=f"https://example.com/{index}",
            url_key=_digest(f"url-{index}"),
            guid_key=_digest(f"guid-{index}"),
            title_key=_digest(f"title-{index}"),
            title=f"Title {index}",
            title_zh=f"标题{index}",
            published_at=datetime(2026, 9, 19, index, tzinfo=UTC),
            status="candidate",
        )
        for index in range(count)
    ]
    session.add_all(items)
    await session.commit()
    return items


def _build_pusher(
    session: AsyncSession,
    sender: FakeSender,
    *,
    review_board: object | None = None,
) -> tuple[ReviewCardPusher, SenderFactoryStub]:
    factory = _factory(session)
    board = review_board or CandidateReviewService(factory)
    factory_stub = SenderFactoryStub(sender)
    return ReviewCardPusher(factory, _secret_box(), board, sender_factory=factory_stub), factory_stub


async def _pending_ids(session: AsyncSession) -> list[UUID]:
    service = CandidateReviewService(_factory(session))
    return [item.id for item in await service.list_pending_review()]


@pytest.mark.anyio
async def test_skips_when_config_missing(db_session: AsyncSession) -> None:
    sender = FakeSender()
    pusher, factory_stub = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert factory_stub.credentials == []
    assert sender.calls == []


@pytest.mark.anyio
async def test_skips_when_config_disabled(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=False)
    sender = FakeSender()
    pusher, factory_stub = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert factory_stub.credentials == []


@pytest.mark.anyio
async def test_skips_when_whitelist_empty(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, whitelist=[])
    await _seed_candidates(db_session, 1)
    sender = FakeSender()
    pusher, factory_stub = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert factory_stub.credentials == []
    assert len(await _pending_ids(db_session)) == 1  # 未推送，候选保持待审核


@pytest.mark.anyio
async def test_skips_when_no_pending_candidates(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    sender = FakeSender()
    pusher, factory_stub = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert factory_stub.credentials == []


@pytest.mark.anyio
async def test_pushes_card_and_marks_review_pushed(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    items = await _seed_candidates(db_session, 2)
    sender = FakeSender()
    pusher, factory_stub = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert factory_stub.credentials == [("cli_test", "s3cret")]
    assert len(sender.calls) == 1
    open_id, card = sender.calls[0]
    assert open_id == "ou_boss"
    assert card["header"]["title"]["content"] == "候选审核"
    assert await _pending_ids(db_session) == []  # 两候选均已标记，不再进入待审核

    # 已推送候选不重复推送：第二次调用不再发卡
    await pusher.push_pending_review()
    assert len(sender.calls) == 1
    assert {item.id for item in items}  # 候选确实存在过


@pytest.mark.anyio
async def test_sends_all_batches_to_every_whitelisted_recipient(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, whitelist=["ou_boss", "ou_backup"])
    await _seed_candidates(db_session, 11)  # 2 批（10 + 1）
    sender = FakeSender()
    pusher, _ = _build_pusher(db_session, sender)

    await pusher.push_pending_review()

    assert len(sender.calls) == 4  # 2 批 × 2 接收者
    assert [open_id for open_id, _ in sender.calls] == ["ou_boss", "ou_backup", "ou_boss", "ou_backup"]
    assert sender.calls[0][1]["header"]["title"]["content"] == "候选审核 1/2"
    assert sender.calls[2][1]["header"]["title"]["content"] == "候选审核 2/2"
    assert await _pending_ids(db_session) == []


@pytest.mark.anyio
async def test_failed_batch_is_not_marked_but_later_batches_continue(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    items = await _seed_candidates(db_session, 11)  # 2 批
    sender = FakeSender(fail_at_calls={1})  # 第 1 批发送失败
    pusher, _ = _build_pusher(db_session, sender)

    await pusher.push_pending_review()  # 失败不向上抛

    assert len(sender.calls) == 2  # 两批都尝试过
    # list_pending_review 按发布时间倒序：批次 1 = items[1:]（最新 10 条），未标记，下次重推
    pending = await _pending_ids(db_session)
    assert pending == [item.id for item in reversed(items[1:])]


@pytest.mark.anyio
async def test_send_failure_logs_item_count_and_error_type(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _write_bot_config(db_session)
    await _seed_candidates(db_session, 1)
    sender = FakeSender(fail_at_calls={1})
    pusher, _ = _build_pusher(db_session, sender)

    with caplog.at_level(logging.WARNING):
        await pusher.push_pending_review()

    assert "FeishuBotApiError" in caplog.text
    assert "s3cret" not in caplog.text


class _BrokenMarkBoard:
    def __init__(self, items: list[RssItem]) -> None:
        self._items = items

    async def list_pending_review(self) -> list[RssItem]:
        return self._items

    async def mark_review_pushed(self, item_ids: list[UUID]) -> None:
        raise RuntimeError("database down")


@pytest.mark.anyio
async def test_mark_failure_is_logged_not_raised(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    items = await _seed_candidates(db_session, 1)
    sender = FakeSender()
    pusher, _ = _build_pusher(db_session, sender, review_board=_BrokenMarkBoard(items))

    await pusher.push_pending_review()  # 标记失败不向上抛，已发出的卡不回滚

    assert len(sender.calls) == 1
