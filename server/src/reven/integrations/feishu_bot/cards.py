"""飞书卡片 2.0 构造：把 markdown 内容包装为 interactive 卡片，供对话回复与通知复用。"""

from typing import Any


def build_markdown_card(markdown: str, *, title: str | None = None) -> dict[str, Any]:
    """构造卡片 2.0 消息体：正文为单个 markdown 元素；title 非空时放入 header。"""
    card: dict[str, Any] = {
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": markdown}]},
    }
    if title:
        card["header"] = {"title": {"tag": "plain_text", "content": title}}
    return card
