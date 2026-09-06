"""Notion VI Hub 一次性迁移：拉取页面 → 章节启发式映射 → 草稿品牌 + 素材归档 + skipped 报告。

设计约束（issue #46）：
- 结果只生成草稿，不自动发布，权威来源切换由人工核对后完成；
- 幂等：同一页面已有成功迁移时不重复创建；素材按 sha256 去重复用；
- dry-run 不写库（不建草稿、不登记素材），但会真实下载图片以给出准确计数；
- 不可导入项（未识别章节、无标注色值、规范类内容）全部列入 skipped 并附原因。
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from reven.brand.domain import BrandAssetPurpose, BrandAssetSource, BrandVersionSource, ImportRunStatus
from reven.brand.models import BrandImportRun
from reven.brand.repository import BrandRepository
from reven.brand.service import BrandService
from reven.content_sync.downloader import SecureContentDownloader
from reven.content_sync.executor import ContentSyncFailure
from reven.content_sync.media_archive import ContentAssetStore, DownloadRequest
from reven.scheduling import utc_now

VI_HUB_PAGE_ID = "67477fcdc2ce40c2ab93a52976f08318"

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
_URL = re.compile(r"https?://[^\s)\]]+")
_HANDLE = re.compile(r"@([A-Za-z0-9_]{2,64})")

# 已知色名 → 品牌配色槽位（VI v2.1 术语作为待核对初始资料，不作永久约束）
_COLOR_SLOTS = (
    (("终端绿", "主色", "primary"), "primary"),
    (("碳黑", "文字", "text"), "text"),
    (("冷白", "背景", "background"), "background"),
)
_SPEC_KEYWORDS = ("规范", "prompt", "kit", "sop", "流程", "方法")


class NotionPageSource(Protocol):
    async def retrieve_page(self, page_id: str) -> dict[str, Any]: ...
    async def retrieve_page_markdown(self, page_id: str) -> str: ...


@dataclass(frozen=True)
class CandidateImage:
    section: str
    alt: str
    url: str
    purpose: str
    label: str


@dataclass(frozen=True)
class ParsedViHub:
    payload: dict[str, object]  # BrandProfilePayload 的已识别子集
    images: tuple[CandidateImage, ...]
    skipped: tuple[dict[str, str], ...] = field(default=())


def parse_vi_hub(markdown: str, page_title: str) -> ParsedViHub:
    """章节启发式映射：标题关键词决定字段归属，图片全部收集并按章节猜测用途。"""
    sections = _split_sections(markdown)
    payload: dict[str, object] = {}
    images: list[CandidateImage] = []
    skipped: list[dict[str, str]] = []
    if page_title.strip():
        payload["brand_name"] = page_title.strip()

    for title, body in sections:
        lowered = title.lower()
        for ordinal, (alt, url) in enumerate(_IMAGE.findall(body), start=1):
            purpose = _purpose_for(lowered)
            label = alt.strip() or f"{title}-{ordinal}"
            images.append(CandidateImage(title, alt, url, purpose, label[:200]))
        text_body = _IMAGE.sub("", body)
        if any(keyword in lowered for keyword in _SPEC_KEYWORDS):
            skipped.append({"item": title, "reason": "规范/方法类内容需人工提炼为渠道模板，未自动导入"})
            continue
        _parse_fields(title, lowered, text_body, payload, skipped)
    return ParsedViHub(payload, tuple(images), tuple(skipped))


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(markdown))
    if not matches:
        return [("页面正文", markdown)] if markdown.strip() else []
    sections: list[tuple[str, str]] = []
    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        sections.append(("页面信息", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1), markdown[match.end() : end]))
    return sections


def _purpose_for(lowered_title: str) -> str:
    if "二维码" in lowered_title:
        return BrandAssetPurpose.QRCODE
    if "logo" in lowered_title or "标志" in lowered_title:
        return BrandAssetPurpose.LOGO
    if "头像" in lowered_title or "avatar" in lowered_title:
        return BrandAssetPurpose.AVATAR
    if "封面" in lowered_title or "cover" in lowered_title:
        return BrandAssetPurpose.COVER
    return BrandAssetPurpose.OTHER


def _parse_fields(
    title: str,
    lowered: str,
    body: str,
    payload: dict[str, object],
    skipped: list[dict[str, str]],
) -> None:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if "品牌名" in lowered or "brand name" in lowered:
        if first_line:
            payload["brand_name"] = first_line[:100]
        return
    if "署名" in lowered or "作者" in lowered or "author" in lowered:
        if first_line:
            payload["default_author"] = first_line[:16]
        return
    if "handle" in lowered:
        match = _HANDLE.search(body)
        if match:
            payload["handle"] = match.group(1)
        else:
            skipped.append({"item": title, "reason": "未找到 @handle 形式的标识"})
        return
    if "官网" in lowered or "网站" in lowered or "website" in lowered:
        match = _URL.search(body)
        if match:
            payload["website"] = match.group(0)[:200]
        return
    if "tagline" in lowered or "slogan" in lowered or "一句话" in lowered:
        if first_line:
            payload["tagline"] = first_line[:200]
        return
    if "简介" in lowered or "介绍" in lowered or "intro" in lowered:
        if first_line:
            payload["intro"] = first_line[:500]
        return
    if "配色" in lowered or "颜色" in lowered or "色彩" in lowered or "color" in lowered or "vi" == lowered.strip():
        _parse_colors(title, body, payload, skipped)
        return
    if title == "页面信息":
        # 首个标题前的导言区：作为品牌简介候选
        if first_line and "intro" not in payload:
            payload["intro"] = first_line[:500]
        return
    skipped.append({"item": title, "reason": "未识别章节，未导入"})


def _parse_colors(title: str, body: str, payload: dict[str, object], skipped: list[dict[str, str]]) -> None:
    colors: dict[str, str] = {}
    for line in body.splitlines():
        hex_match = _HEX.search(line)
        if hex_match is None:
            continue
        value = f"#{hex_match.group(1).upper()}"
        label = line[: hex_match.start()].strip(" -：:*`")
        slot = next(
            (slot for keywords, slot in _COLOR_SLOTS if any(k in label.lower() or k in label for k in keywords)),
            None,
        )
        if slot is None:
            skipped.append({"item": f"{title} / {label or value}", "reason": "色值未标注已知用途（终端绿/碳黑/冷白）"})
            continue
        colors[slot] = value
    if colors:
        payload["colors"] = colors
    if not colors and not _HEX.search(body):
        skipped.append({"item": title, "reason": "配色章节未找到 #RRGGBB 色值"})


class ViHubImporter:
    """迁移执行器：下载素材、写草稿与导入运行记录。"""

    def __init__(
        self,
        session: AsyncSession,
        notion: NotionPageSource,
        downloader: SecureContentDownloader,
        store: ContentAssetStore,
    ) -> None:
        self.session = session
        self.notion = notion
        self.downloader = downloader
        self.store = store
        self.repo = BrandRepository(session)
        self.service = BrandService(self.repo)

    async def run(self, *, page_id: str = VI_HUB_PAGE_ID, dry_run: bool) -> BrandImportRun:
        if not dry_run:
            existing = await self.repo.successful_import_run(page_id)
            if existing is not None:
                return existing
        run = BrandImportRun(notion_page_id=page_id, dry_run=dry_run, status=ImportRunStatus.RUNNING, report={})
        self.session.add(run)
        await self.session.flush()
        try:
            report = await self._execute(page_id, dry_run)
            run.status = ImportRunStatus.COMPLETED
            run.report = report
        except Exception as exc:
            run.status = ImportRunStatus.FAILED
            run.error = _safe_message(exc)
            run.finished_at = utc_now()
            await self.session.commit()
            return run
        run.finished_at = utc_now()
        await self.session.commit()
        return run

    async def _execute(self, page_id: str, dry_run: bool) -> dict[str, object]:
        page = await self.notion.retrieve_page(page_id)
        markdown = await self.notion.retrieve_page_markdown(page_id)
        parsed = parse_vi_hub(markdown, _page_title(page))
        skipped = list(parsed.skipped)
        imported = reused = 0
        for candidate in parsed.images:
            outcome = await self._import_image(candidate, page_id, dry_run)
            if outcome == "imported":
                imported += 1
            elif outcome == "reused":
                reused += 1
            else:
                skipped.append({"item": candidate.label, "reason": outcome})
        profile_status = await self._write_profile(parsed, dry_run, skipped)
        return {
            "brand_name": parsed.payload.get("brand_name", ""),
            "profile_fields": sorted(parsed.payload.keys()),
            "profile_status": profile_status,
            "assets_imported": imported,
            "assets_reused": reused,
            "skipped": skipped,
        }

    async def _import_image(self, candidate: CandidateImage, page_id: str, dry_run: bool) -> str:
        """返回 imported / reused / 跳过原因。"""
        request = DownloadRequest(
            ordinal=0,
            kind="image",
            embedded=True,
            source_url=candidate.url,
            label=candidate.label,
        )
        try:
            content: bytes | None = None
            async for media in self.downloader.download(uuid4(), (request,)):
                content = media.content
        except ContentSyncFailure as exc:
            return f"下载失败：{exc}"
        if not content:
            return "下载结果为空"
        if dry_run:
            existing = await self.repo.asset_by_sha256(hashlib.sha256(content).hexdigest())
            return "reused" if existing is not None else "imported"
        _asset, created = await self.service.register_asset(
            self.store,
            content,
            mime_type=_sniff(content) or "image/png",
            purpose=candidate.purpose,
            label=candidate.label,
            source=BrandAssetSource.NOTION_IMPORT,
            source_ref=page_id,
        )
        return "imported" if created else "reused"

    async def _write_profile(self, parsed: ParsedViHub, dry_run: bool, skipped: list[dict[str, str]]) -> str:
        if not parsed.payload:
            skipped.append({"item": "品牌档案", "reason": "未识别出任何品牌字段"})
            return "empty"
        if dry_run:
            return "would_create_draft"
        existing_draft = await self.repo.draft_brand()
        if existing_draft is not None:
            skipped.append({"item": "品牌档案", "reason": "已存在品牌草稿，未覆盖；请人工核对合并"})
            return "skipped_existing_draft"
        draft = await self.service.upsert_brand_draft(parsed.payload)
        draft.source = BrandVersionSource.NOTION_IMPORT
        return "draft_created"


def _page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties")
    if not isinstance(properties, dict):
        return ""
    for value in properties.values():
        if isinstance(value, dict) and value.get("type") == "title":
            parts = value.get("title")
            if isinstance(parts, list):
                return "".join(part.get("plain_text", "") for part in parts if isinstance(part, dict))
    return ""


def _sniff(content: bytes) -> str | None:
    from reven.brand.images import sniff_image_mime

    return sniff_image_mime(content)


def _safe_message(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return re.sub(r"https?://\S+", "[已脱敏地址]", text)[:500]
