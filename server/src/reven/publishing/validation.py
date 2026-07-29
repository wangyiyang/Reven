"""Aggregated, user-facing pre-publication validation."""

from dataclasses import dataclass

from reven.domain import TargetChannel

WECHAT_TITLE_MAX = 64
WECHAT_AUTHOR_MAX = 16
WECHAT_SUMMARY_MAX = 120
WECHAT_BODY_MAX = 200_000


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str


ValidationError = ValidationIssue


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[ValidationError, ...]
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PublicationCandidate:
    title: str
    markdown: str
    summary: str
    author: str
    cover: object | None
    image_count: int
    materialized_image_count: int
    channels: tuple[TargetChannel, ...]
    integration_status: dict[str, bool]
    unsupported_channels: tuple[str, ...] = ()
    materialization_errors: tuple[ValidationError, ...] = ()
    feishu_error: str | None = None


def validate_candidate(candidate: PublicationCandidate) -> ValidationResult:
    errors: list[ValidationError] = list(candidate.materialization_errors)
    warnings: list[ValidationIssue] = []
    _required_content(candidate, errors)
    _assets(candidate, errors)
    _channels(candidate, errors)
    _wechat_limits(candidate, errors)
    if candidate.feishu_error:
        warnings.append(ValidationIssue("feishu_unavailable", "飞书通知暂不可用，不影响发布", "feishu"))
    return ValidationResult(tuple(errors), tuple(warnings))


def _add(errors: list[ValidationError], code: str, message: str, field: str) -> None:
    errors.append(ValidationError(code, message, field))


def _required_content(candidate: PublicationCandidate, errors: list[ValidationError]) -> None:
    if not candidate.title.strip():
        _add(errors, "title_empty", "标题不能为空", "title")
    if not candidate.markdown.strip():
        _add(errors, "body_empty", "正文不能为空", "markdown")


def _assets(candidate: PublicationCandidate, errors: list[ValidationError]) -> None:
    if candidate.cover is None:
        _add(errors, "cover_missing", "请配置并确认封面可下载", "cover")
    if candidate.materialized_image_count != candidate.image_count:
        _add(errors, "image_download_failed", "部分正文图片未能完整下载", "images")


def _channels(candidate: PublicationCandidate, errors: list[ValidationError]) -> None:
    if candidate.unsupported_channels:
        _add(errors, "channel_unsupported", "目标渠道包含不支持的选项", "channels")
    providers = {
        TargetChannel.BLOG: "github",
        TargetChannel.WECHAT: "wechat",
    }
    for channel in _effective_channels(candidate):
        provider = providers[channel]
        if not candidate.integration_status.get(provider, False):
            _add(errors, "integration_unavailable", f"{channel.value}集成未配置或连接测试未成功", provider)


def _wechat_limits(candidate: PublicationCandidate, errors: list[ValidationError]) -> None:
    if TargetChannel.WECHAT not in _effective_channels(candidate):
        return
    limits = (
        ("title", candidate.title, WECHAT_TITLE_MAX, "wechat_title_too_long", "微信标题"),
        ("author", candidate.author, WECHAT_AUTHOR_MAX, "wechat_author_too_long", "微信作者"),
        ("summary", candidate.summary, WECHAT_SUMMARY_MAX, "wechat_summary_too_long", "微信摘要"),
        ("markdown", candidate.markdown, WECHAT_BODY_MAX, "wechat_body_too_long", "微信正文"),
    )
    for field_name, value, maximum, code, label in limits:
        if len(value) > maximum:
            _add(errors, code, f"{label}超过 {maximum} 字限制", field_name)


def _effective_channels(candidate: PublicationCandidate) -> tuple[TargetChannel, ...]:
    if candidate.channels or candidate.unsupported_channels:
        return candidate.channels
    return (TargetChannel.BLOG, TargetChannel.WECHAT)
