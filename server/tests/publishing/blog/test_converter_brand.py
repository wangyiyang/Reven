"""品牌绑定下博客转换器的 frontmatter 扩展与封面拷贝。"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.blog.converter import BlogArticle, BlogBrandFields, BlogConverter
from reven.publishing.snapshot import build_snapshot

NOW = datetime(2026, 8, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai"))


def _snapshot(tmp_path: Path) -> tuple[object, MaterializedAssets]:
    image = tmp_path / "snapshot" / "asset.png"
    cover = tmp_path / "snapshot" / "cover.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nfrozen")
    cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
    snapshot = build_snapshot(
        "正文 ![图](reven-asset://1)\n",
        image_sha256=("a" * 64,),
        cover_sha256="b" * 64,
        title="标题",
        summary="摘要",
        categories=(),
        image_paths=(image,),
    )
    assets = MaterializedAssets(
        (MaterializedAsset("", image, "a" * 64, "image/png", image.stat().st_size),),
        MaterializedAsset("", cover, "b" * 64, "image/png", cover.stat().st_size),
    )
    return snapshot, assets


def test_brand_fields_emit_author_cover_og_and_copy_cover(tmp_path: Path) -> None:
    snapshot, assets = _snapshot(tmp_path)
    brand = BlogBrandFields(author="王一羊", og_image_url=None)

    output = BlogConverter("https://www.wangyiyang.cc").write(
        tmp_path / "blog",
        BlogArticle("11111111-2222-3333-4444-555555555555", snapshot, assets, brand),  # type: ignore[arg-type]
        now=NOW,
    )

    text = output.post_path.read_text()
    assert 'author: "王一羊"' in text
    assert 'cover: "images/posts/2026-08-01-notion-11111111/cover.png"' in text
    assert 'og_image_url: "https://www.wangyiyang.cc/images/posts/2026-08-01-notion-11111111/cover.png"' in text
    cover_out = tmp_path / "blog" / "images/posts/2026-08-01-notion-11111111/cover.png"
    assert cover_out.read_bytes() == b"\x89PNG\r\n\x1a\ncover"
    assert Path("images/posts/2026-08-01-notion-11111111/cover.png") in output.manifest


def test_brand_og_override_wins_over_cover_derivation(tmp_path: Path) -> None:
    snapshot, assets = _snapshot(tmp_path)
    brand = BlogBrandFields(author="", og_image_url="https://cdn.example.com/og.png")

    output = BlogConverter("https://www.wangyiyang.cc").write(
        tmp_path / "blog",
        BlogArticle("11111111-2222-3333-4444-555555555555", snapshot, assets, brand),  # type: ignore[arg-type]
        now=NOW,
    )

    text = output.post_path.read_text()
    assert "author:" not in text
    assert 'og_image_url: "https://cdn.example.com/og.png"' in text


def test_legacy_article_without_brand_unchanged(tmp_path: Path) -> None:
    snapshot, assets = _snapshot(tmp_path)

    output = BlogConverter("https://www.wangyiyang.cc").write(
        tmp_path / "blog",
        BlogArticle("11111111-2222-3333-4444-555555555555", snapshot, assets),  # type: ignore[arg-type]
        now=NOW,
    )

    text = output.post_path.read_text()
    assert "author:" not in text
    assert "cover:" not in text
    assert "og_image_url" not in text
    assert not (tmp_path / "blog" / "images/posts/2026-08-01-notion-11111111/cover.png").exists()
