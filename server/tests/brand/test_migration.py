"""VI Hub 迁移：解析器纯函数与执行器行为。"""

import hashlib
from typing import Any

import pytest
from reven.brand.migration import ViHubImporter, parse_vi_hub
from reven.brand.models import BrandAsset, BrandVersion
from reven.content_sync.media_archive import DownloadedMedia
from reven.integrations.tencent_cos.store import ArchivedAsset
from sqlalchemy import select

VI_MARKDOWN = """翊行代码 VI 手册

# 品牌名
翊行代码

# 默认署名
王一羊

# Handle
@wangyiyang

# 官网
https://wangyiyang.cc

# 一句话介绍
把内容工程化。

# 配色
- 终端绿 #00E676：主色
- 碳黑 #0A0A0A：正文
- 冷白 #FAFAFA：背景
- 氛围蓝 #0F4C81

# Logo
![几何Logo](https://file.notion.so/logo.png)

# 公众号二维码
![二维码](https://file.notion.so/qr.png)

# 公众号规范
字号、行距等排版规范……

# 杂物间
一些不相关的内容。
"""

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
QR = b"\x89PNG\r\n\x1a\n" + b"1" * 32


def test_parse_vi_hub_maps_sections() -> None:
    parsed = parse_vi_hub(VI_MARKDOWN, "翊行代码 VI 手册")

    assert parsed.payload["brand_name"] == "翊行代码"
    assert parsed.payload["default_author"] == "王一羊"
    assert parsed.payload["handle"] == "wangyiyang"
    assert parsed.payload["website"] == "https://wangyiyang.cc"
    assert parsed.payload["tagline"] == "把内容工程化。"
    assert parsed.payload["colors"] == {"primary": "#00E676", "text": "#0A0A0A", "background": "#FAFAFA"}

    purposes = {image.label: image.purpose for image in parsed.images}
    assert purposes == {"几何Logo": "标志", "二维码": "二维码"}

    skipped = {(item["item"], item["reason"]) for item in parsed.skipped}
    assert any("氛围蓝" in item and "未标注已知用途" in reason for item, reason in skipped)
    assert any(item == "公众号规范" and "人工提炼" in reason for item, reason in skipped)
    assert any(item == "杂物间" and "未识别" in reason for item, reason in skipped)


def test_parse_empty_markdown() -> None:
    parsed = parse_vi_hub("", "")
    assert parsed.payload == {}
    assert parsed.images == ()


class FakeNotion:
    def __init__(self, markdown: str = VI_MARKDOWN) -> None:
        self.markdown = markdown

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return {
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "翊行代码"}]},
            }
        }

    async def retrieve_page_markdown(self, page_id: str) -> str:
        return self.markdown


class FailingNotion(FakeNotion):
    async def retrieve_page_markdown(self, page_id: str) -> str:
        raise RuntimeError("https://signed-url?token=secret 读取失败")


class FakeDownloader:
    def __init__(self) -> None:
        self.contents = {"https://file.notion.so/logo.png": PNG, "https://file.notion.so/qr.png": QR}

    async def download(self, run_id, requests):  # type: ignore[no-untyped-def]
        for request in requests:
            content = self.contents[request.source_url]
            yield DownloadedMedia(request, content, hashlib.sha256(content).hexdigest(), "image/png")


class FakeStore:
    def __init__(self) -> None:
        self.archived: list[str] = []

    async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset:
        self.archived.append(sha256)
        url = f"https://cdn.example.com/{sha256[:8]}.png"
        return ArchivedAsset(f"brand/{sha256[:8]}.png", sha256, mime_type, len(content), url, False)


def _importer(db_session, notion=None) -> ViHubImporter:  # type: ignore[no-untyped-def]
    return ViHubImporter(db_session, notion or FakeNotion(), FakeDownloader(), FakeStore())  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_execute_creates_draft_and_assets_idempotently(db_session) -> None:  # type: ignore[no-untyped-def]
    importer = _importer(db_session)
    run = await importer.run(dry_run=False)

    assert run.status == "已完成"
    assert run.report["profile_status"] == "draft_created"
    assert run.report["assets_imported"] == 2

    drafts = (await db_session.scalars(select(BrandVersion).where(BrandVersion.status == "草稿"))).all()
    assert len(drafts) == 1
    assert drafts[0].payload["brand_name"] == "翊行代码"
    assert drafts[0].source == "Notion 导入"
    assets = (await db_session.scalars(select(BrandAsset))).all()
    assert len(assets) == 2

    # 幂等：已成功迁移过，第二次直接返回既有运行记录
    again = await importer.run(dry_run=False)
    assert again.id == run.id
    assets_after = (await db_session.scalars(select(BrandAsset))).all()
    assert len(assets_after) == 2


@pytest.mark.anyio
async def test_dry_run_writes_nothing(db_session) -> None:  # type: ignore[no-untyped-def]
    run = await _importer(db_session).run(dry_run=True)

    assert run.status == "已完成"
    assert run.dry_run is True
    assert run.report["profile_status"] == "would_create_draft"
    assert run.report["assets_imported"] == 2
    assert (await db_session.scalars(select(BrandVersion))).all() == []
    assert (await db_session.scalars(select(BrandAsset))).all() == []


@pytest.mark.anyio
async def test_existing_draft_not_overwritten(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(
        BrandVersion(version=1, status="草稿", source="手工创建", payload={"brand_name": "人工草稿"})
    )
    await db_session.commit()

    run = await _importer(db_session).run(dry_run=False)

    assert run.report["profile_status"] == "skipped_existing_draft"
    assert any("未覆盖" in item["reason"] for item in run.report["skipped"])
    drafts = (await db_session.scalars(select(BrandVersion).where(BrandVersion.status == "草稿"))).all()
    assert drafts[0].payload["brand_name"] == "人工草稿"


@pytest.mark.anyio
async def test_failure_records_error_run(db_session) -> None:  # type: ignore[no-untyped-def]
    run = await _importer(db_session, notion=FailingNotion()).run(dry_run=False)

    assert run.status == "失败"
    assert run.error is not None
    assert "token=secret" not in run.error  # 脱敏
    assert "已脱敏地址" in run.error
    assert run.finished_at is not None
