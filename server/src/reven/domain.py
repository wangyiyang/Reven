from dataclasses import dataclass
from enum import StrEnum


class TargetChannel(StrEnum):
    BLOG = "个人博客"
    WECHAT = "微信公众号"


class AutomationStatus(StrEnum):
    NOT_STARTED = "未开始"
    WAITING = "等待中"
    PROCESSING = "处理中"
    BLOCKED = "阻塞"
    FAILED = "失败"
    COMPLETED = "已完成"


class BlogStage(StrEnum):
    PENDING = "待处理"
    CONVERTING = "转换中"
    BUILDING = "构建中"
    PR_CREATED = "PR 已创建"
    WAITING_CI = "等待 CI"
    MERGING = "合并中"
    ONLINE = "已上线"
    FAILED = "失败"


class WechatStage(StrEnum):
    PENDING = "待处理"
    RENDERING = "渲染中"
    UPLOADING_IMAGES = "上传图片"
    UPLOADING_COVER = "上传封面"
    CREATING_DRAFT = "创建草稿"
    DRAFT_CREATED = "草稿已生成"
    FAILED = "失败"


class JobStatus(StrEnum):
    WAITING = "等待中"
    PROCESSING = "处理中"
    BLOCKED = "阻塞"
    FAILED = "失败"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


@dataclass(frozen=True)
class ChannelSelection:
    channels: frozenset[TargetChannel]
    unsupported: tuple[str, ...]
    used_default: bool


def parse_target_channels(raw_channels: list[str]) -> ChannelSelection:
    if not raw_channels:
        return ChannelSelection(
            channels=frozenset({TargetChannel.BLOG, TargetChannel.WECHAT}),
            unsupported=(),
            used_default=True,
        )
    supported: set[TargetChannel] = set()
    unsupported: list[str] = []
    for raw in raw_channels:
        try:
            supported.add(TargetChannel(raw))
        except ValueError:
            unsupported.append(raw)
    return ChannelSelection(frozenset(supported), tuple(unsupported), False)
