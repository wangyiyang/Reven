"""品牌与发布设置 API 测试。"""

from uuid import uuid4

import pytest

PROFILE_PAYLOAD = {
    "brand_name": "翊行代码",
    "intro": "记录技术与实践",
    "default_author": "王翊仰",
    "handle": "wangyiyang",
    "website": "https://wangyiyang.cc",
    "tagline": "less is more",
    "colors": {"primary": "#00E676", "text": "#0A0A0A", "background": "#FAFAFA"},
    "fonts": {"body": "Inter, Noto Sans SC", "mono": "JetBrains Mono"},
    "style_notes": "简洁直接",
}

WECHAT_TEMPLATE_PAYLOAD = {
    "theme": {"primary_color": "#00E676", "font_family": "Inter", "font_size": 16},
    "footer_modules": [
        {"key": "follow", "type": "text", "content": "欢迎关注「翊行代码」", "enabled": True},
    ],
}

BLOG_TEMPLATE_PAYLOAD = {"author": "王翊仰"}


def test_brand_profile_draft_publish_flow(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench

    empty = client.get("/api/brand/profile")
    assert empty.status_code == 200
    assert empty.json() == {"published": None, "draft": None}

    created = client.put("/api/brand/profile/draft", json=PROFILE_PAYLOAD)
    assert created.status_code == 200
    assert created.json()["status"] == "草稿"
    assert created.json()["version"] == 1

    updated = client.put("/api/brand/profile/draft", json={**PROFILE_PAYLOAD, "tagline": "new tagline"})
    assert updated.json()["version"] == 1
    assert updated.json()["payload"]["tagline"] == "new tagline"

    published = client.post("/api/brand/profile/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "已发布"
    assert published.json()["published_at"] is not None

    # 发布后再编辑 → 新版本草稿；旧版本归档保留
    client.put("/api/brand/profile/draft", json=PROFILE_PAYLOAD)
    republished = client.post("/api/brand/profile/publish")
    assert republished.json()["version"] == 2

    versions = client.get("/api/brand/profile/versions")
    assert [item["version"] for item in versions.json()] == [2, 1]
    assert {item["status"] for item in versions.json()} == {"已发布", "已归档"}

    profile = client.get("/api/brand/profile")
    assert profile.json()["published"]["version"] == 2
    assert profile.json()["draft"] is None

    conflict = client.post("/api/brand/profile/publish")
    assert conflict.status_code == 409


def test_brand_profile_payload_validation(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench
    bad_color = client.put(
        "/api/brand/profile/draft",
        json={**PROFILE_PAYLOAD, "colors": {"primary": "green", "text": "#0A0A0A", "background": "#FAFAFA"}},
    )
    assert bad_color.status_code == 422

    long_author = client.put("/api/brand/profile/draft", json={**PROFILE_PAYLOAD, "default_author": "x" * 17})
    assert long_author.status_code == 422


def test_channel_template_draft_publish_flow(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench

    created = client.put("/api/brand/templates/wechat/draft", json=WECHAT_TEMPLATE_PAYLOAD)
    assert created.status_code == 200
    assert created.json()["channel"] == "微信公众号"
    assert created.json()["status"] == "草稿"

    published = client.post("/api/brand/templates/wechat/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "已发布"

    state = client.get("/api/brand/templates/wechat")
    assert state.json()["published"]["payload"]["theme"]["primary_color"] == "#00E676"

    blog = client.put("/api/brand/templates/blog/draft", json=BLOG_TEMPLATE_PAYLOAD)
    assert blog.status_code == 200
    assert blog.json()["channel"] == "个人博客"

    versions = client.get("/api/brand/templates/wechat/versions")
    assert len(versions.json()) == 1

    unknown = client.get("/api/brand/templates/newsletter")
    assert unknown.status_code == 404


def test_template_publish_rejects_missing_assets(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench
    missing = str(uuid4())
    client.put(
        "/api/brand/templates/wechat/draft",
        json={
            **WECHAT_TEMPLATE_PAYLOAD,
            "footer_modules": [{"key": "qr", "type": "image", "asset_id": missing, "enabled": True}],
        },
    )
    rejected = client.post("/api/brand/templates/wechat/publish")
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "template_assets_missing"


def test_template_payload_channel_mismatch(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench
    # 微信模板 payload 缺 theme 的核心结构时按微信 schema 校验失败
    rejected = client.put("/api/brand/templates/wechat/draft", json={"theme": {"primary_color": "red"}})
    assert rejected.status_code == 422


@pytest.mark.anyio
async def test_brand_asset_register_dedupe(db_session) -> None:  # type: ignore[no-untyped-def]
    from reven.brand.repository import BrandRepository
    from reven.brand.service import BrandService

    class FakeStore:
        def __init__(self) -> None:
            self.calls = 0

        async def archive(self, content, *, sha256, mime_type):  # type: ignore[no-untyped-def]
            self.calls += 1
            from reven.integrations.tencent_cos.store import ArchivedAsset

            return ArchivedAsset(
                key=f"brand/{sha256}",
                sha256=sha256,
                mime_type=mime_type,
                size=len(content),
                public_url=f"https://cdn.example.com/brand/{sha256}",
                reused=False,
            )

    # 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c626001000000ffff030000060005"
        "57bfabd40000000049454e44ae426082"
    )
    store = FakeStore()
    service = BrandService(BrandRepository(db_session))
    asset, created = await service.register_asset(
        store, png, mime_type="image/png", purpose="封面", label="默认封面", source="上传"
    )
    assert created is True
    assert asset.width == 1 and asset.height == 1
    assert asset.public_url.endswith(asset.sha256)

    again, created_again = await service.register_asset(
        store, png, mime_type="image/png", purpose="封面", label="重复上传", source="上传"
    )
    assert created_again is False
    assert again.id == asset.id
    assert store.calls == 1

    disabled = await service.update_asset(asset, label=None, enabled=False)
    assert disabled.enabled is False


def test_brand_asset_upload_requires_cos(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _ = workbench
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c626001000000ffff030000060005"
        "57bfabd40000000049454e44ae426082"
    )
    response = client.post(
        "/api/brand/assets",
        params={"purpose": "封面", "label": "测试"},
        content=png,
        headers={"Content-Type": "application/octet-stream"},
    )
    # 测试环境未配置 COS → 显式 503，而不是静默失败
    assert response.status_code == 503
    assert response.json()["code"] == "cos_not_configured"

    bad = client.post(
        "/api/brand/assets",
        params={"purpose": "封面", "label": "文本"},
        content=b"hello",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert bad.status_code == 422
