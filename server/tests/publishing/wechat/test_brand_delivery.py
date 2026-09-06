"""品牌绑定下微信交付的模板套用与主题传递。"""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.wechat.publisher import WeChatPublisher


class FakeWeChat:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.draft_content = ""

    async def get_token(self) -> str:
        self.calls.append("get_token")
        return "token"

    async def upload_body_image(self, path: Path) -> str:
        self.calls.append("upload_body_image")
        return f"https://mmbiz.qpic.cn/{path.name}"

    async def upload_cover_material(self, path: Path) -> str:
        self.calls.append("upload_cover_material")
        return "thumb-id"

    async def create_draft(self, payload: dict[str, object]) -> str:
        self.calls.append("create_draft")
        articles = payload["articles"]
        assert isinstance(articles, list)
        self.draft_content = str(articles[0]["content"])
        return "draft-media-id"


class FakeStore:
    def __init__(self, metadata: dict[str, object], brand: dict[str, object] | None = None) -> None:
        self.metadata = metadata
        self.brand = brand
        self.result: dict[str, object] = {}

    async def load(self, claim: JobClaim) -> dict[str, object]:
        return {
            "source_markdown": "# title\n![x](reven-asset://image/1)",
            "snapshot_metadata": self.metadata,
            "wechat_result": self.result,
            "title": "title",
            "author": "author",
            "digest": "digest",
            "content_source_url": "",
            "brand": self.brand,
        }

    async def assert_lease(self, claim: JobClaim) -> bool:
        return True

    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool:
        self.result.update(patch)
        return True

    async def clear_inflight_if_operation_matches(self, job_id, operation_key: str, operation_id: str) -> bool:  # type: ignore[no-untyped-def]
        return False


def _assets(tmp_path: Path) -> tuple[MaterializedAssets, dict[str, object]]:
    image = tmp_path / "image-1.png"
    cover = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
    image_asset = MaterializedAsset("https://n/image", image, "a" * 64, "image/png", image.stat().st_size)
    cover_asset = MaterializedAsset("https://n/cover", cover, "b" * 64, "image/png", cover.stat().st_size)
    metadata: dict[str, object] = {
        "images": [{"ordinal": 1, "path": str(image), "sha256": "a" * 64}],
        "cover": {"path": str(cover), "sha256": "b" * 64},
        "cover_sha256": "b" * 64,
    }
    return MaterializedAssets((image_asset,), cover_asset), metadata


class EchoRenderer:
    """把正文中的占位符原样渲染为 img，记录收到的主题。"""

    def __init__(self) -> None:
        self.theme: object = None
        self.markdown = ""

    async def render(self, markdown: str, theme: object = None) -> str:
        self.markdown = markdown
        self.theme = theme
        images = "".join(
            f'<img src="reven-asset://image/{ordinal}">' for ordinal in range(1, markdown.count("reven-asset://") + 1)
        )
        return f"<section>{images}</section>"


def _footer_entry(path: Path, public_url: str, label: str = "二维码") -> dict[str, object]:
    return {
        "asset_id": str(uuid4()),
        "label": label,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "public_url": public_url,
        "path": str(path),
        "mime_type": "image/png",
        "size": path.stat().st_size,
    }


def _brand(template_payload: dict[str, object] | None) -> dict[str, object]:
    return {
        "brand_payload": {"name": "翊行代码", "default_author": "王一羊"},
        "template_payload": template_payload,
        "theme": {"primaryColor": "#0F4C81", "fontFamily": "sans-serif", "fontSize": 17},
        "author": "王一羊",
        "assets": {},
    }


@pytest.mark.anyio
async def test_footer_image_module_appended_uploaded_and_theme_passed(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    materialized, metadata = _assets(snapshot_dir)
    qr = snapshot_dir / "footer.png"
    qr.write_bytes(b"\x89PNG\r\n\x1a\nqr")
    metadata["footer_assets"] = [_footer_entry(qr, "https://cdn.example.com/qr.png")]
    asset_id = str(metadata["footer_assets"][0]["asset_id"])  # type: ignore[index]
    template = {"footer_modules": [{"key": "qr", "type": "image", "asset_id": asset_id, "enabled": True}]}

    renderer = EchoRenderer()
    wechat = FakeWeChat()
    publisher = WeChatPublisher(
        wechat,
        renderer,
        FakeStore(metadata, _brand(template)),
        assets_loader=lambda _: materialized,
    )

    result = await publisher.publish(JobClaim(uuid4(), uuid4()))

    assert result.media_id == "draft-media-id"
    # 正文图片 + 文末图片都上传并替换
    assert wechat.calls.count("upload_body_image") == 2
    assert "reven-asset://" not in wechat.draft_content
    assert "https://cdn.example.com/qr.png" not in wechat.draft_content
    # 主题透传渲染器
    assert renderer.theme is not None
    assert getattr(renderer.theme, "primary_color") == "#0F4C81"
    # 文末模块以续序占位符进入渲染输入（公网 URL 不落渲染器）
    assert "![二维码](reven-asset://image/2)" in renderer.markdown


@pytest.mark.anyio
async def test_footer_text_module_appended_without_image_upload(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    materialized, metadata = _assets(snapshot_dir)
    template = {
        "footer_modules": [{"key": "follow", "type": "text", "content": "欢迎关注「翊行代码」", "enabled": True}]
    }
    renderer = EchoRenderer()
    wechat = FakeWeChat()
    publisher = WeChatPublisher(
        wechat,
        renderer,
        FakeStore(metadata, _brand(template)),
        assets_loader=lambda _: materialized,
    )

    await publisher.publish(JobClaim(uuid4(), uuid4()))

    assert wechat.calls.count("upload_body_image") == 1  # 仅正文图片
    assert "欢迎关注「翊行代码」" in renderer.markdown


@pytest.mark.anyio
async def test_missing_footer_file_blocks_delivery(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    materialized, metadata = _assets(snapshot_dir)
    ghost = snapshot_dir / "ghost.png"
    ghost.write_bytes(b"\x89PNG\r\n\x1a\nghost")
    entry = _footer_entry(ghost, "https://cdn.example.com/ghost.png")
    ghost.unlink()  # 冻结文件丢失
    metadata["footer_assets"] = [entry]
    template = {"footer_modules": [{"key": "qr", "type": "image", "asset_id": entry["asset_id"], "enabled": True}]}
    publisher = WeChatPublisher(
        FakeWeChat(),
        EchoRenderer(),
        FakeStore(metadata, _brand(template)),
        assets_loader=lambda _: materialized,
    )

    with pytest.raises(BlockedPublishError, match="文末素材文件缺失"):
        await publisher.publish(JobClaim(uuid4(), uuid4()))


@pytest.mark.anyio
async def test_no_brand_binding_keeps_legacy_delivery(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    materialized, metadata = _assets(snapshot_dir)
    renderer = EchoRenderer()
    wechat = FakeWeChat()
    publisher = WeChatPublisher(wechat, renderer, FakeStore(metadata), assets_loader=lambda _: materialized)

    await publisher.publish(JobClaim(uuid4(), uuid4()))

    assert renderer.theme is None
    assert "欢迎关注" not in renderer.markdown
