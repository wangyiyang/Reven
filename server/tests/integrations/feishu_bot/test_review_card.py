"""ReviewCardBuilder 纯函数测试：标题/摘要取舍、截断、时间行、按钮协议、分批与批次 header。"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from reven.integrations.feishu_bot.review_card import MAX_CANDIDATES_PER_CARD, build_review_card_batches
from reven.rss.models import RssItem


def _item(
    *,
    title: str = "Original Title",
    title_zh: str = "中文标题",
    summary: str = "original summary",
    summary_zh: str = "中文摘要",
    source_name: str = "Example",
    published_at: datetime | None = datetime(2026, 9, 19, 8, 30, tzinfo=UTC),
) -> RssItem:
    return RssItem(
        id=uuid4(),
        title=title,
        title_zh=title_zh,
        summary=summary,
        summary_zh=summary_zh,
        source_name=source_name,
        published_at=published_at,
    )


def _text_blocks(card: dict[str, Any]) -> list[str]:
    return [element["text"]["content"] for element in card["elements"] if element["tag"] == "div"]


def _actions(card: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [element["actions"] for element in card["elements"] if element["tag"] == "action"]


def test_empty_items_yield_no_batches() -> None:
    assert build_review_card_batches([]) == []


def test_single_card_header_has_no_batch_label() -> None:
    batches = build_review_card_batches([_item() for _ in range(MAX_CANDIDATES_PER_CARD)])

    assert len(batches) == 1
    assert batches[0].card["header"]["title"]["content"] == "候选审核"
    assert len(batches[0].item_ids) == MAX_CANDIDATES_PER_CARD


def test_multi_card_headers_carry_batch_labels() -> None:
    items = [_item() for _ in range(MAX_CANDIDATES_PER_CARD + 1)]

    batches = build_review_card_batches(items)

    assert len(batches) == 2
    assert batches[0].card["header"]["title"]["content"] == "候选审核 1/2"
    assert batches[1].card["header"]["title"]["content"] == "候选审核 2/2"
    assert len(batches[0].item_ids) == MAX_CANDIDATES_PER_CARD
    assert len(batches[1].item_ids) == 1
    assert batches[0].item_ids == tuple(item.id for item in items[:MAX_CANDIDATES_PER_CARD])


def test_title_prefers_chinese_and_falls_back_to_original() -> None:
    zh = build_review_card_batches([_item(title_zh="中文优先")])
    assert _text_blocks(zh[0].card)[0].startswith("**中文优先**")

    fallback = build_review_card_batches([_item(title_zh="  ", title="English Title")])
    assert _text_blocks(fallback[0].card)[0].startswith("**English Title**")


def test_summary_prefers_chinese_falls_back_and_truncates() -> None:
    fallback = build_review_card_batches([_item(summary_zh="", summary="english summary")])
    assert "english summary" in _text_blocks(fallback[0].card)[0]

    long_summary = "摘" * 300
    truncated = build_review_card_batches([_item(summary_zh=long_summary)])
    block = _text_blocks(truncated[0].card)[0]
    summary_line = block.splitlines()[1]
    assert len(summary_line) == 120
    assert summary_line.endswith("…")


def test_empty_summary_line_is_omitted() -> None:
    batches = build_review_card_batches([_item(summary_zh="", summary="")])
    lines = _text_blocks(batches[0].card)[0].splitlines()
    assert all("来源" in line or line.startswith("**") or "发布时间" in line for line in lines)


def test_source_and_publish_date_lines() -> None:
    batches = build_review_card_batches([_item(source_name="MIT TR")])
    block = _text_blocks(batches[0].card)[0]
    assert "来源：MIT TR" in block
    assert "发布时间：2026-09-19" in block


def test_missing_publish_date_line_is_omitted() -> None:
    batches = build_review_card_batches([_item(published_at=None)])
    block = _text_blocks(batches[0].card)[0]
    assert "发布时间" not in block
    assert "来源：Example" in block


def test_action_buttons_carry_review_protocol_value() -> None:
    item = _item()
    batches = build_review_card_batches([item])

    (actions,) = _actions(batches[0].card)
    approve, ignore = actions
    assert approve["text"]["content"] == "采纳"
    assert approve["type"] == "primary"
    assert approve["value"] == {"action": "approve", "item_id": str(item.id)}
    assert ignore["text"]["content"] == "忽略"
    assert ignore["type"] == "danger"
    assert ignore["value"] == {"action": "ignore", "item_id": str(item.id)}


def test_candidates_are_separated_by_horizontal_rules() -> None:
    batches = build_review_card_batches([_item(), _item()])
    tags = [element["tag"] for element in batches[0].card["elements"]]
    assert tags == ["div", "action", "hr", "div", "action"]
