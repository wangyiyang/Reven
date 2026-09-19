"""候选稿审核交互卡片构建（纯函数，无副作用，与飞书 SDK 零耦合）。

卡片采用飞书 interactive card 经典 schema（config + header + elements）：
每条候选一个段落（标题/摘要/来源/发布时间）加一对「采纳 / 忽略」按钮；
每卡最多 MAX_CANDIDATES_PER_CARD 条，超出分批，多卡时 header 注明批次。
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from reven.rss.models import RssItem

MAX_CANDIDATES_PER_CARD = 10
SUMMARY_MAX_CHARS = 120


@dataclass(frozen=True)
class ReviewCardBatch:
    """一张审核卡片与其覆盖的候选 id（发送成功后按 id 批量标记已推送）。"""

    card: dict[str, Any]
    item_ids: tuple[UUID, ...]


def build_review_card_batches(items: list[RssItem]) -> list[ReviewCardBatch]:
    chunks = [items[index : index + MAX_CANDIDATES_PER_CARD] for index in range(0, len(items), MAX_CANDIDATES_PER_CARD)]
    total = len(chunks)
    return [
        ReviewCardBatch(
            card=_build_card(chunk, batch_index=index, batch_total=total),
            item_ids=tuple(item.id for item in chunk),
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


def _build_card(chunk: list[RssItem], *, batch_index: int, batch_total: int) -> dict[str, Any]:
    title = "候选审核" if batch_total == 1 else f"候选审核 {batch_index}/{batch_total}"
    elements: list[dict[str, Any]] = []
    for position, item in enumerate(chunk):
        if position:
            elements.append({"tag": "hr"})
        elements.append(_candidate_block(item))
        elements.append(_candidate_actions(item))
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
        "elements": elements,
    }


def _candidate_block(item: RssItem) -> dict[str, Any]:
    lines = [f"**{_first_text(item.title_zh, item.title)}**"]
    summary = _truncate(_first_text(item.summary_zh, item.summary))
    if summary:
        lines.append(summary)
    lines.append(f"来源：{item.source_name}")
    if item.published_at is not None:
        lines.append(f"发布时间：{item.published_at.strftime('%Y-%m-%d')}")
    return {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}


def _candidate_actions(item: RssItem) -> dict[str, Any]:
    item_id = str(item.id)
    return {
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "采纳"},
                "type": "primary",
                "value": {"action": "approve", "item_id": item_id},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "忽略"},
                "type": "danger",
                "value": {"action": "ignore", "item_id": item_id},
            },
        ],
    }


def _first_text(*values: str | None) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _truncate(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    return f"{text[: SUMMARY_MAX_CHARS - 1]}…"
