from datetime import UTC, datetime
from uuid import uuid4

import pytest
from reven.content_sync.gate import CurrentSnapshotView, SnapshotAssetView
from reven.publishing.wechat.preview import (
    MAX_PREVIEW_IMAGES,
    MAX_PREVIEW_MARKDOWN_BYTES,
    PreviewValidationError,
    _snapshot_body_with_public_urls,
)


def test_preview_replaces_snapshot_placeholders_with_permanent_urls() -> None:
    snapshot = _snapshot("![图](reven-asset://sha256/" + "a" * 64 + ")", 1)

    result = _snapshot_body_with_public_urls(snapshot)

    assert result == "![图](https://assets.example/1)"
    assert "reven-asset://" not in result


def test_preview_rejects_oversized_snapshot_markdown() -> None:
    snapshot = _snapshot("a" * (MAX_PREVIEW_MARKDOWN_BYTES + 1), 0)

    with pytest.raises(PreviewValidationError, match="大小"):
        _snapshot_body_with_public_urls(snapshot)


def test_preview_rejects_too_many_snapshot_images() -> None:
    snapshot = _snapshot("正文", MAX_PREVIEW_IMAGES + 1)

    with pytest.raises(PreviewValidationError, match="图片数量"):
        _snapshot_body_with_public_urls(snapshot)


def test_preview_rejects_unresolved_internal_asset() -> None:
    snapshot = _snapshot("![图](reven-asset://sha256/" + "f" * 64 + ")", 0)

    with pytest.raises(PreviewValidationError, match="未解析"):
        _snapshot_body_with_public_urls(snapshot)


def _snapshot(markdown: str, image_count: int) -> CurrentSnapshotView:
    now = datetime.now(tz=UTC)
    assets = tuple(
        SnapshotAssetView(
            ordinal=index,
            kind="图片",
            embedded=True,
            storage_key=f"assets/{index}",
            public_url=f"https://assets.example/{index}",
            sha256="a" * 64 if index == 1 else f"{index:064x}",
            mime_type="image/png",
            byte_size=1,
            filename=None,
            alt_text=None,
        )
        for index in range(1, image_count + 1)
    )
    return CurrentSnapshotView(
        uuid4(),
        uuid4(),
        now,
        now,
        "标题",
        markdown,
        f"# 标题\n\n{markdown}",
        "b" * 64,
        {},
        assets,
    )
