"""卡片 2.0 构造测试：markdown 元素 + 可选 header 标题。"""

from reven.integrations.feishu_bot.cards import build_markdown_card


def test_card_wraps_markdown_in_schema_2_body() -> None:
    card = build_markdown_card("**加粗**")

    assert card["schema"] == "2.0"
    assert card["body"] == {"elements": [{"tag": "markdown", "content": "**加粗**"}]}
    assert "header" not in card


def test_card_with_title_puts_it_in_header() -> None:
    card = build_markdown_card("正文", title="Reven RSS 每日汇总")

    assert card["header"] == {"title": {"tag": "plain_text", "content": "Reven RSS 每日汇总"}}
    assert card["body"]["elements"] == [{"tag": "markdown", "content": "正文"}]
