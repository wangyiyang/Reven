import pytest
from reven.publishing.wechat.preview import (
    MAX_PREVIEW_IMAGES,
    MAX_PREVIEW_MARKDOWN_BYTES,
    PreviewValidationError,
    _canonical_with_current_urls,
)


def test_preview_replaces_internal_asset_placeholders_with_current_signed_urls() -> None:
    signed = "https://prod-files-secure.s3.us-west-2.amazonaws.com/image.png?X-Amz-Signature=current"
    markdown = f"![图]({signed})"

    result = _canonical_with_current_urls(markdown)

    assert signed in result
    assert "reven-asset://" not in result


def test_preview_handles_reference_images_without_downloading_them() -> None:
    signed = "https://example.notion.so/image.png?signature=current"
    markdown = f"![图][asset]\n\n[asset]: <{signed}>"

    result = _canonical_with_current_urls(markdown)

    assert signed in result
    assert "reven-asset://" not in result


@pytest.mark.parametrize(
    "url",
    [
        "http://prod-files-secure.s3.amazonaws.com/a.png",
        "data:image/png;base64,AAAA",
        "https://127.0.0.1/a.png",
        "https://localhost/a.png",
        "https://user:pass@prod-files-secure.s3.amazonaws.com/a.png",
        "https://prod-files-secure.s3.amazonaws.com:8443/a.png",
        "https://prod-files-secure.s3.amazonaws.com/a.png#fragment",
        "https://amazonaws.com.evil.example/a.png",
    ],
)
def test_preview_rejects_unsafe_image_urls(url: str) -> None:
    with pytest.raises(PreviewValidationError, match="不安全"):
        _canonical_with_current_urls(f"![图]({url})")


def test_preview_rejects_oversized_markdown_before_parsing() -> None:
    markdown = "a" * (MAX_PREVIEW_MARKDOWN_BYTES + 1)

    with pytest.raises(PreviewValidationError, match="大小"):
        _canonical_with_current_urls(markdown)


def test_preview_rejects_too_many_images() -> None:
    url = "https://prod-files-secure.s3.amazonaws.com/a.png"
    markdown = "\n".join(f"![{index}]({url})" for index in range(MAX_PREVIEW_IMAGES + 1))

    with pytest.raises(PreviewValidationError, match="图片数量"):
        _canonical_with_current_urls(markdown)
