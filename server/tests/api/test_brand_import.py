"""品牌 Notion 迁移 API 测试。"""

import hashlib
from typing import Any

import pytest
import reven.api.routes.brand as brand_routes
from reven.content_sync.media_archive import DownloadedMedia
from reven.integrations.tencent_cos.store import ArchivedAsset

VI_MARKDOWN = """# 品牌名
翊行代码

# 配色
- 终端绿 #00E676：主色

# Logo
![几何Logo](https://file.notion.so/logo.png)
"""

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeNotion:
    def __init__(self, **_: Any) -> None:
        pass

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return {"properties": {"title": {"type": "title", "title": [{"plain_text": "翊行代码"}]}}}

    async def retrieve_page_markdown(self, page_id: str) -> str:
        return VI_MARKDOWN


class FakeDownloader:
    def __init__(self, *_: Any) -> None:
        pass

    async def download(self, run_id, requests):  # type: ignore[no-untyped-def]
        for request in requests:
            yield DownloadedMedia(request, PNG, hashlib.sha256(PNG).hexdigest(), "image/png")


class FakeStore:
    async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset:
        url = f"https://cdn.example.com/{sha256[:8]}.png"
        return ArchivedAsset(f"brand/{sha256[:8]}.png", sha256, mime_type, len(content), url, False)

    async def aclose(self) -> None:
        pass


async def _fake_load_notion_config(factory):  # type: ignore[no-untyped-def]
    return "secret-token", "data-source-id"


@pytest.fixture()
def import_client(workbench, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    client, _factory = workbench
    monkeypatch.setattr(brand_routes, "load_notion_config", _fake_load_notion_config)
    monkeypatch.setattr(brand_routes, "NotionClient", FakeNotion)
    monkeypatch.setattr(brand_routes, "SecureContentDownloader", FakeDownloader)
    monkeypatch.setattr(brand_routes, "build_tencent_cos_asset_store", lambda _settings: FakeStore())
    return client


def test_import_notion_dry_run_execute_idempotent(import_client) -> None:  # type: ignore[no-untyped-def]
    dry = import_client.post("/api/brand/import/notion", json={"dry_run": True})
    assert dry.status_code == 200
    body = dry.json()
    assert body["status"] == "已完成"
    assert body["dry_run"] is True
    assert body["report"]["profile_status"] == "would_create_draft"
    assert body["report"]["assets_imported"] == 1
    assert body["finished_at"] is not None
    assert import_client.get("/api/brand/profile").json() == {"published": None, "draft": None}

    run = import_client.post("/api/brand/import/notion", json={"dry_run": False})
    assert run.status_code == 200
    assert run.json()["report"]["profile_status"] == "draft_created"
    assert run.json()["report"]["assets_imported"] == 1
    profile = import_client.get("/api/brand/profile").json()
    assert profile["draft"]["payload"]["brand_name"] == "翊行代码"
    assert profile["draft"]["source"] == "Notion 导入"

    again = import_client.post("/api/brand/import/notion", json={"dry_run": False})
    assert again.json()["id"] == run.json()["id"]

    runs = import_client.get("/api/brand/import/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 2  # dry-run + execute；幂等重放不新建记录


def test_import_notion_requires_configured_integration(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench
    response = client.post("/api/brand/import/notion", json={"dry_run": True})
    assert response.status_code == 409
    assert response.json()["code"] == "notion_not_configured"
