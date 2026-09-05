"""品牌模板应用纯函数测试：文末模块追加/去重/不确定提醒、主题参数、博客字段、封面比例。"""

from uuid import uuid4

from reven.brand.application import (
    apply_wechat_template,
    cover_ratio_warning,
    wechat_theme_params,
)

BRAND = {
    "brand_name": "翊行代码",
    "default_author": "王翊仰",
    "handle": "wangyiyang",
    "colors": {"primary": "#00E676", "text": "#0A0A0A"},
    "fonts": {"body": "Inter, Noto Sans SC", "mono": "JetBrains Mono"},
}


class _Asset:
    def __init__(
        self, *, enabled: bool = True, sha256: str = "a" * 64, url: str = "https://cdn.example.com/qr.png"
    ) -> None:
        self.id = uuid4()
        self.enabled = enabled
        self.sha256 = sha256
        self.public_url = url
        self.label = "公众号二维码"


def test_apply_text_module_appends_to_plain_body() -> None:
    template = {
        "footer_modules": [{"key": "follow", "type": "text", "content": "欢迎关注「翊行代码」", "enabled": True}]
    }
    result = apply_wechat_template("正文内容。", BRAND, template, {})
    assert result.errors == ()
    assert result.warnings == ()
    assert result.markdown.endswith("---\n\n欢迎关注「翊行代码」\n")
    assert result.markdown.startswith("正文内容。")


def test_apply_text_module_skips_when_already_present() -> None:
    template = {
        "footer_modules": [{"key": "follow", "type": "text", "content": "欢迎关注「翊行代码」", "enabled": True}]
    }
    markdown = "正文。\n\n欢迎关注「翊行代码」\n"
    result = apply_wechat_template(markdown, BRAND, template, {})
    assert result.markdown == markdown  # 不重复追加
    assert [w.code for w in result.warnings] == ["footer_already_present"]


def test_apply_text_module_uncertain_tail_skips_with_warning() -> None:
    template = {"footer_modules": [{"key": "follow", "type": "text", "content": "回复关键字领取资料", "enabled": True}]}
    markdown = "正文。\n\n---\n\n感谢关注本公众号，点个在看"
    result = apply_wechat_template(markdown, BRAND, template, {})
    assert result.markdown == markdown  # 不确定时不改动
    assert [w.code for w in result.warnings] == ["footer_conflict_uncertain"]


def test_disabled_module_is_ignored() -> None:
    template = {"footer_modules": [{"key": "follow", "type": "text", "content": "欢迎关注", "enabled": False}]}
    result = apply_wechat_template("正文。", BRAND, template, {})
    assert result.markdown == "正文。"
    assert result.warnings == ()


def test_apply_image_module() -> None:
    asset = _Asset()
    template = {"footer_modules": [{"key": "qr", "type": "image", "asset_id": str(asset.id), "enabled": True}]}

    appended = apply_wechat_template("正文。", BRAND, template, {asset.id: asset})  # type: ignore[dict-item]
    assert f"![公众号二维码]({asset.public_url})" in appended.markdown

    # 同一图片已内嵌（按 sha256 判定，适配冻结正文的占位符表示）
    deduped = apply_wechat_template(
        "正文 ![x](reven-asset://image/1) 结尾",
        BRAND,
        template,
        {asset.id: asset},  # type: ignore[dict-item]
        embedded_sha256=(asset.sha256,),
    )
    assert [w.code for w in deduped.warnings] == ["footer_already_present"]
    # 预览表示（sha256 在 URI 中）与冻结表示判定一致
    preview_form = apply_wechat_template(
        f"正文 ![x](reven-asset://sha256/{asset.sha256}) 结尾",
        BRAND,
        template,
        {asset.id: asset},  # type: ignore[dict-item]
        embedded_sha256=(asset.sha256,),
    )
    assert [w.code for w in preview_form.warnings] == ["footer_already_present"]

    missing = apply_wechat_template("正文。", BRAND, template, {})
    assert [e.code for e in missing.errors] == ["brand_asset_unreadable"]

    disabled_asset = _Asset(enabled=False)
    disabled = apply_wechat_template("正文。", BRAND, template, {disabled_asset.id: disabled_asset})  # type: ignore[dict-item]
    assert [e.code for e in disabled.errors] == ["brand_asset_unreadable"]


def test_no_template_is_passthrough() -> None:
    result = apply_wechat_template("正文。", BRAND, None, {})
    assert result.markdown == "正文。"
    assert result.errors == () and result.warnings == ()


def test_wechat_theme_params_template_overrides_brand() -> None:
    template = {"theme": {"primary_color": "#FF0000", "font_family": "", "font_size": 18}}
    params = wechat_theme_params(BRAND, template)
    assert params == {"primaryColor": "#FF0000", "fontFamily": "Inter, Noto Sans SC", "fontSize": 18}

    defaults = wechat_theme_params(BRAND, None)
    assert defaults == {"primaryColor": "#00E676", "fontFamily": "Inter, Noto Sans SC", "fontSize": 16}



def test_cover_ratio_warning() -> None:
    assert cover_ratio_warning(900, 383, channel="微信公众号") is None
    warning = cover_ratio_warning(500, 500, channel="微信公众号")
    assert warning is not None and warning.code == "cover_aspect_ratio"
    # 博客渠道暂无比例推荐
    assert cover_ratio_warning(500, 500, channel="个人博客") is None
    # 无尺寸信息时不提醒
    assert cover_ratio_warning(None, None, channel="微信公众号") is None
