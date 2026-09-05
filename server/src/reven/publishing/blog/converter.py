"""Pure Jekyll conversion using already frozen publication assets."""

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from reven.publishing.assets import MaterializedAssets
from reven.publishing.snapshot import ContentSnapshot, image_urls, replace_image_destinations

SHANGHAI = ZoneInfo("Asia/Shanghai")
_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")
_CALLOUT = re.compile(r"<callout>(.*?)</callout>", re.DOTALL)


@dataclass(frozen=True)
class BlogBrandFields:
    """品牌绑定时写入 frontmatter 的扩展字段（冻结于任务元数据）。"""

    author: str = ""
    og_image_url: str | None = None  # 模板指定 OG 素材的绝对地址；None 表示由封面推导


@dataclass(frozen=True)
class BlogArticle:
    page_id: str
    snapshot: ContentSnapshot
    assets: MaterializedAssets
    brand: BlogBrandFields | None = None


@dataclass(frozen=True)
class ConversionOutput:
    post_path: Path
    manifest: tuple[Path, ...]
    article_path: str


class BlogConverter:
    def __init__(self, site_url: str) -> None:
        parsed = urlsplit(site_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("site_url 必须是固定 HTTPS origin")
        self.site_url = site_url.rstrip("/")

    def write(
        self,
        root: Path,
        article: BlogArticle,
        *,
        now: datetime | None = None,
    ) -> ConversionOutput:
        _safe_root(root)
        instant = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
        date = instant.date().isoformat()
        slug = _slug(article.snapshot.title, article.page_id)
        stem = f"{date}-{slug}"
        relative_post = Path("_posts") / f"{stem}.md"
        image_dir = Path("images/posts") / stem
        post_path = _new_path(root, relative_post)
        final_image_dir = _new_path(root, image_dir)
        stage = root / f".reven-stage-{uuid4()}"
        stage.mkdir(mode=0o700)
        try:
            body, image_paths, cover_rel = self._body(stage.resolve(), article, image_dir)
            staged_post = _new_path(stage, relative_post)
            staged_post.parent.mkdir(parents=True, exist_ok=True)
            staged_post.write_text(
                _frontmatter(
                    article.snapshot, instant, brand=article.brand, cover_rel=cover_rel, site_url=self.site_url
                )
                + body,
                encoding="utf-8",
            )
            if image_paths:
                final_image_dir.parent.mkdir(parents=True, exist_ok=True)
                (stage / image_dir).replace(final_image_dir)
            post_path.parent.mkdir(parents=True, exist_ok=True)
            staged_post.replace(post_path)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return ConversionOutput(post_path, (relative_post, *image_paths), f"/{date[:4]}/{date[5:7]}/{date[8:]}/{slug}/")

    def _body(
        self, root: Path, article: BlogArticle, image_dir: Path
    ) -> tuple[str, tuple[Path, ...], Path | None]:
        body = _CALLOUT.sub(
            lambda match: "\n".join(f"> {line}" for line in match.group(1).strip().splitlines()) + "\n",
            article.snapshot.markdown,
        )
        body = body.replace("<empty-block/>", "")
        paths: list[Path] = []
        public_urls: list[str] = []
        copies: list[tuple[Path, Path]] = []
        for ordinal, (snapshot_asset, asset) in enumerate(
            zip(article.snapshot.images, article.assets.images, strict=True), 1
        ):
            if snapshot_asset.ordinal != ordinal:
                raise ValueError("正文素材 URI 必须严格一一映射")
            source = _safe_frozen_file(asset.path)
            suffix = source.suffix.lower()
            relative = image_dir / f"{ordinal:02d}{suffix}"
            destination = _new_path(root, relative)
            paths.append(relative)
            public_urls.append(f"{self.site_url}/{relative.as_posix()}")
            copies.append((source, destination))
        body = replace_image_sources(body, tuple(public_urls))
        cover_rel: Path | None = None
        if article.brand is not None and article.assets.cover is not None:
            source = _safe_frozen_file(article.assets.cover.path)
            cover_rel = image_dir / f"cover{source.suffix.lower()}"
            destination = _new_path(root, cover_rel)
            paths.append(cover_rel)
            copies.append((source, destination))
        for source, destination in copies:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return body.strip() + "\n", tuple(paths), cover_rel


def _frontmatter(
    snapshot: ContentSnapshot,
    instant: datetime,
    *,
    brand: BlogBrandFields | None = None,
    cover_rel: Path | None = None,
    site_url: str = "",
) -> str:
    def quoted(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    categories = "[" + ", ".join(quoted(item) for item in snapshot.categories) + "]"
    keywords = ", ".join(snapshot.categories)
    extra = ""
    if brand is not None:
        if brand.author:
            extra += f"author: {quoted(brand.author)}\n"
        if cover_rel is not None:
            cover_posix = cover_rel.as_posix()
            extra += f"cover: {quoted(cover_posix)}\n"
            og_image = brand.og_image_url or f"{site_url.rstrip('/')}/{cover_posix}"
            extra += f"og_image_url: {quoted(og_image)}\n"
    return (
        "---\n"
        "layout: post\n"
        f"title: {quoted(snapshot.title)}\n"
        f"date: {instant:%Y-%m-%d %H:%M:%S} +0800\n"
        f"categories: {categories}\n"
        f"description: {quoted(snapshot.summary)}\n"
        f"keywords: {quoted(keywords)}\n"
        f"{extra}"
        "mermaid: false\nsequence: false\nflow: false\nmathjax: false\n"
        "mindmap: false\nmindmap2: false\n---\n\n"
    )


def _slug(title: str, page_id: str) -> str:
    words = _ASCII_WORD.findall(title)
    return "-".join(word.lower() for word in words) if words else f"notion-{page_id.replace('-', '')[:8].lower()}"


def _safe_root(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("工作区不得为符号链接")
    root.mkdir(parents=True, exist_ok=True)


def _new_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("输出路径越界")
    destination = root.resolve() / relative
    for parent in (destination, *destination.parents):
        if parent == root.resolve().parent:
            break
        if parent.is_symlink():
            raise ValueError("输出路径不得包含符号链接")
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖已有博客文件: {relative}")
    return destination


def _safe_frozen_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("冻结素材必须是普通文件")
    return path.resolve()


def replace_image_sources(markdown: str, public_urls: tuple[str, ...]) -> str:
    expected = tuple(f"reven-asset://image/{ordinal}" for ordinal in range(1, len(public_urls) + 1))
    if image_urls(markdown) != expected:
        raise ValueError("正文图片素材 URI 未严格一一映射")
    output = replace_image_destinations(markdown, public_urls)
    final = image_urls(output)
    if final != public_urls or any(url.startswith("reven-asset:") for url in final):
        raise ValueError("正文图片素材替换失败")
    return output
