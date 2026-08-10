from reven.content_sync.markdown_media import discover_media, rewrite_media


def test_discovers_downloadable_media_and_preserves_external_platform_links() -> None:
    markdown = """图片 ![架构图](https://files.notion.so/diagram.png?sig=1)

[访谈音频](https://prod-files-secure.s3.us-west-2.amazonaws.com/audio.mp3?X-Amz-Signature=1)

[演示视频](https://files.notion.so/demo.mp4) 与 [附件](https://files.notion.so/brief.pdf)

[YouTube](https://youtube.com/watch?v=1) [Bilibili](https://www.bilibili.com/video/BV1)

`![代码图片](https://files.notion.so/code.png)`
"""

    manifest = discover_media(markdown)

    assert [(item.kind, item.label) for item in manifest] == [
        ("图片", "架构图"),
        ("音频", "访谈音频"),
        ("视频", "演示视频"),
        ("附件", "附件"),
    ]
    rewritten = rewrite_media(
        markdown,
        manifest,
        (
            "https://assets.example/diagram.png",
            "https://assets.example/audio.mp3",
            "https://assets.example/demo.mp4",
            "https://assets.example/brief.pdf",
        ),
    )
    assert "https://youtube.com/watch?v=1" in rewritten
    assert "https://www.bilibili.com/video/BV1" in rewritten
    assert "https://files.notion.so/code.png" in rewritten
    assert "https://assets.example/audio.mp3" in rewritten
    assert "https://assets.example/brief.pdf" in rewritten


def test_discovers_and_rewrites_reference_style_media_definitions_once() -> None:
    markdown = (
        "![架构图][image]\n\n"
        "再次引用 ![架构图][image]\n\n"
        "[下载附件][report]\n\n"
        "[image]: <https://files.notion.so/diagram.png?sig=secret>\n"
        "[report]: https://files.notion.so/report.pdf?sig=secret\n"
    )

    manifest = discover_media(markdown)
    rewritten = rewrite_media(
        markdown,
        manifest,
        ("https://assets.example/diagram.png", "https://assets.example/report.pdf"),
    )

    assert [(item.kind, item.embedded) for item in manifest] == [("图片", True), ("附件", False)]
    assert rewritten.count("https://assets.example/diagram.png") == 1
    assert "![架构图][image]" in rewritten
    assert "https://files.notion.so" not in rewritten
