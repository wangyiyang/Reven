from reven.publishing.wechat.preview import _canonical_with_current_urls


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
