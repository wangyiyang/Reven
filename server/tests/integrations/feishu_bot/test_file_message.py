"""飞书文件消息路由与附件下载落盘测试。"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # type: ignore[import-untyped]
from reven.agent.service import AgentTurn
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from reven.integrations.feishu_bot.handlers import RouteDecision, build_message_handler, route_message

BOT_OPEN_ID = "ou_bot"
BOT_MENTION = {"key": "@_user_1", "id": {"open_id": BOT_OPEN_ID}, "name": "Reven"}


def _file_message_event(
    *,
    chat_type: str = "p2p",
    file_key: str = "file_123",
    file_name: str = "销售日报.xlsx",
    mentions: list[dict[str, Any]] | None = None,
) -> P2ImMessageReceiveV1:
    content = f'{{"file_key":"{file_key}","file_name":"{file_name}"}}'
    message: dict[str, Any] = {
        "message_id": "om_file_1",
        "chat_id": "oc_chat_1",
        "chat_type": chat_type,
        "message_type": "file",
        "content": content,
    }
    if mentions is not None:
        message["mentions"] = mentions
    return P2ImMessageReceiveV1(
        {
            "event": {
                "sender": {"sender_id": {"open_id": "ou_user_1"}, "sender_type": "user", "tenant_key": "t"},
                "message": message,
            }
        }
    )


def test_route_message_supports_file_p2p_and_group() -> None:
    event_p2p = _file_message_event(chat_type="p2p")
    event_msg_p2p = event_p2p.event.message
    sender_p2p = event_p2p.event.sender

    decision = route_message(sender_p2p, event_msg_p2p, BOT_OPEN_ID)
    assert decision == RouteDecision(
        kind="file",
        text="销售日报.xlsx",
        file_key="file_123",
        file_name="销售日报.xlsx",
    )

    event_group = _file_message_event(chat_type="group", mentions=[BOT_MENTION])
    decision_group = route_message(event_group.event.sender, event_group.event.message, BOT_OPEN_ID)
    assert decision_group == RouteDecision(
        kind="file",
        text="销售日报.xlsx",
        file_key="file_123",
        file_name="销售日报.xlsx",
    )


@pytest.mark.anyio
async def test_file_dispatcher_downloads_and_invokes_agent(tmp_path: Path) -> None:
    credentials = AsyncMock()
    credentials.feishu_bot.return_value = AsyncMock(whitelist_open_ids=("ou_user_1",))

    agent_service = AsyncMock()
    agent_service.chat.return_value = AgentTurn("session_1", "已完成销售日报分析", "model", False)

    replies: list[str] = []

    async def mock_reply(message_id: str, text: str) -> None:
        replies.append(text)

    async def mock_downloader(message_id: str, file_key: str, *, resource_type: str = "file") -> bytes:
        return b"fake excel content"

    dispatcher = FeishuChatDispatcher(
        credentials,
        agent_service,
        reply=mock_reply,
        downloader=mock_downloader,
        workspace_root=tmp_path,
        timeout_seconds=5.0,
    )
    import asyncio

    dispatcher.bind_loop(asyncio.get_running_loop())

    handler = build_message_handler(dispatcher, BOT_OPEN_ID)
    event = _file_message_event()
    handler(event)

    await asyncio.sleep(0.1)

    # 验证文件是否写入 workspace/downloads
    downloaded_file = tmp_path / "downloads" / "销售日报.xlsx"
    assert downloaded_file.exists()
    assert downloaded_file.read_bytes() == b"fake excel content"

    # 验证 Agent 是否被调用，且传入了文件路径
    assert agent_service.chat.called
    call_prompt = agent_service.chat.call_args[0][0]
    assert str(downloaded_file) in call_prompt
    assert "销售日报.xlsx" in call_prompt

    # 验证回复
    assert "正在接收并下载文件…" in replies
    assert "思考中…" in replies
    assert "已完成销售日报分析" in replies
