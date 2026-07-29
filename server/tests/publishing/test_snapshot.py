from reven.publishing.snapshot import build_snapshot


def test_signed_image_query_does_not_change_content_hash() -> None:
    first = "正文\n![图](https://files.notion.so/a.png?X-Amz-Signature=one)"
    second = "正文\n![图](https://files.notion.so/a.png?X-Amz-Signature=two)"

    first_snapshot = build_snapshot(first, image_sha256=("a" * 64,), cover_sha256="b" * 64)
    second_snapshot = build_snapshot(second, image_sha256=("a" * 64,), cover_sha256="b" * 64)

    assert first_snapshot.markdown == "正文\n![图](reven-asset://image/1)"
    assert first_snapshot.content_hash == second_snapshot.content_hash


def test_image_bytes_change_content_hash() -> None:
    markdown = "正文\n![图](https://files.notion.so/a.png)"

    first = build_snapshot(markdown, image_sha256=("a" * 64,), cover_sha256="b" * 64)
    second = build_snapshot(markdown, image_sha256=("c" * 64,), cover_sha256="b" * 64)

    assert first.content_hash != second.content_hash


def test_snapshot_includes_complete_metadata() -> None:
    snapshot = build_snapshot(
        "正文",
        image_sha256=(),
        cover_sha256="b" * 64,
        title=" 标题 ",
        summary=" 摘要 ",
        categories=("B", "A"),
    )

    assert snapshot.title == "标题"
    assert snapshot.summary == "摘要"
    assert snapshot.categories == ("A", "B")


def test_only_markdown_image_destination_is_replaced() -> None:
    url = "https://files.notion.so/a.png"
    markdown = f'`{url}`\n\n```\n{url}\n```\n\n<a href="{url}">链接</a>\n\n![图]({url})'

    snapshot = build_snapshot(markdown, image_sha256=("a" * 64,), cover_sha256="b" * 64)

    assert snapshot.markdown == markdown.replace(f"![图]({url})", "![图](reven-asset://image/1)")


def test_angle_destination_and_escaped_title_are_safely_normalized() -> None:
    markdown = r'![图](<https://files.notion.so/a b.png> "a \"title\"")'

    snapshot = build_snapshot(markdown, image_sha256=("a" * 64,), cover_sha256="b" * 64)

    assert snapshot.markdown == "![图](reven-asset://image/1)"


def test_reference_and_nested_image_syntax_are_normalized() -> None:
    markdown = (
        "![a [nested]][asset]\n"
        "![collapsed][]\n"
        "![shortcut]\n\n"
        "[asset]: https://files.notion.so/a.png?X-Amz-Signature=one\n"
        "[collapsed]: https://files.notion.so/b.png\n"
        "[shortcut]: https://files.notion.so/c.png\n"
    )

    snapshot = build_snapshot(
        markdown,
        image_sha256=("a" * 64, "b" * 64, "c" * 64),
        cover_sha256="d" * 64,
    )

    assert "![a \\[nested\\]](reven-asset://image/1)" in snapshot.markdown
    assert "![collapsed](reven-asset://image/2)" in snapshot.markdown
    assert "![shortcut](reven-asset://image/3)" in snapshot.markdown


def test_shared_reference_link_keeps_stable_semantics_and_hash() -> None:
    first = "![图][asset] 与 [下载][asset]\n\n[asset]: https://files.notion.so/a.png?X-Amz-Signature=one\n"
    second = first.replace("Signature=one", "Signature=two")

    first_snapshot = build_snapshot(first, image_sha256=("a" * 64,), cover_sha256="b" * 64)
    second_snapshot = build_snapshot(second, image_sha256=("a" * 64,), cover_sha256="b" * 64)

    assert "[下载][asset]" in first_snapshot.markdown
    assert "[ASSET]: <https://files.notion.so/a.png>" in first_snapshot.markdown
    assert first_snapshot.content_hash == second_snapshot.content_hash
