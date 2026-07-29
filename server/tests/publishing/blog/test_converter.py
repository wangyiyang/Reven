from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.blog.converter import BlogArticle, BlogConverter, replace_image_sources
from reven.publishing.snapshot import build_snapshot, image_urls


def test_converter_matches_blog_contract_and_copies_frozen_assets(tmp_path: Path) -> None:
    source = tmp_path / "snapshot" / "asset.png"
    source.parent.mkdir()
    source.write_bytes(b"\x89PNG\r\n\x1a\nfrozen")
    markdown = "<callout>注意</callout>\n<empty-block/>\n![图](reven-asset://1)\n"
    snapshot = build_snapshot(
        markdown,
        image_sha256=("a" * 64,),
        cover_sha256="b" * 64,
        title='测试 "稿件"',
        summary="摘要",
        categories=("AI",),
        image_paths=(source,),
    )
    assets = MaterializedAssets((MaterializedAsset("", source, "a" * 64, "image/png", source.stat().st_size),), None)

    output = BlogConverter("https://www.wangyiyang.cc").write(
        tmp_path / "blog",
        BlogArticle("11111111-2222-3333-4444-555555555555", snapshot, assets),
        now=datetime(2026, 8, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    text = output.post_path.read_text()
    assert text.startswith('---\nlayout: post\ntitle: "测试 \\"稿件\\""\ndate: 2026-08-01')
    assert 'categories: ["AI"]' in text
    assert 'description: "摘要"' in text
    assert "> 注意\n\n" in text
    assert "https://www.wangyiyang.cc/images/posts/2026-08-01-notion-11111111/01.png" in text
    assert output.manifest == (
        Path("_posts/2026-08-01-notion-11111111.md"),
        Path("images/posts/2026-08-01-notion-11111111/01.png"),
    )
    assert output.article_path == "/2026/08/01/notion-11111111/"


def test_converter_rejects_symlinked_output_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    snapshot = build_snapshot("body", image_sha256=(), cover_sha256="", title="title")
    with pytest.raises(ValueError, match="符号链接"):
        BlogConverter("https://www.wangyiyang.cc").write(
            linked,
            BlogArticle("11111111-2222-3333-4444-555555555555", snapshot, MaterializedAssets((), None)),
        )


@pytest.mark.parametrize(
    "markdown",
    [
        "![x](reven-asset://image/999)",
        "![x](reven-asset://wrong/1)",
        "![x](https://example.com/x.png)",
        "![a](reven-asset://image/1)\n![b](reven-asset://image/1)",
    ],
)
def test_image_sources_reject_unknown_malformed_external_and_duplicate(markdown: str) -> None:
    with pytest.raises(ValueError, match="素材"):
        replace_image_sources(markdown, ("https://www.wangyiyang.cc/images/posts/x/01.png",))


def test_image_source_replacement_does_not_touch_code_literal() -> None:
    markdown = (
        "`![fake](reven-asset://image/1)`\n\n"
        "```\n![fake](reven-asset://image/1)\n```\n\n"
        "<div>\n![fake](reven-asset://image/1)\n</div>\n\n"
        "![x](reven-asset://image/1)"
    )
    output = replace_image_sources(markdown, ("https://www.wangyiyang.cc/images/posts/x/01.png",))
    assert output.count("reven-asset://image/1") == 3
    assert output.count("https://www.wangyiyang.cc/images/posts/x/01.png") == 1


def test_image_source_replacement_uses_parser_spans_in_nested_multiline_content() -> None:
    markdown = (
        "> lead ![one](reven-asset://image/1) and\n"
        "> ![two](reven-asset://image/2)\n\n"
        "- ![three](reven-asset://image/3) ![four](reven-asset://image/4)\n"
    )
    urls = tuple(f"https://www.wangyiyang.cc/images/posts/x/{index:02d}.png" for index in range(1, 5))
    output = replace_image_sources(markdown, urls)
    assert image_urls(output) == urls
    assert "> lead ![one](https://www.wangyiyang.cc/images/posts/x/01.png)" in output
