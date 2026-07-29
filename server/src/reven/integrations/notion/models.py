"""Notion 集成的领域模型与错误分类。

错误分为三类，供上层（发布重试、连接测试、API 响应）区分处理：

- ``NotionConfigError``：配置或鉴权错误（401/403/404 及其它 4xx），需要人工修正，重试无意义。
- ``NotionTransientError``：临时性错误（429、超时、连接失败、5xx），可按 ``retry_after`` 秒后重试。
- ``NotionSchemaError``：稿件库字段与预期契约不符，错误信息包含字段名。
"""

from dataclasses import dataclass
from datetime import datetime


class NotionError(Exception):
    """Notion 调用或数据契约错误的基类。"""


class NotionConfigError(NotionError):
    """配置或鉴权错误（401/403/404 及其它 4xx），重试无法恢复。"""


class NotionTransientError(NotionError):
    """临时性错误（429、超时、连接失败、5xx），可稍后重试。"""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NotionResponseTooLargeError(NotionTransientError):
    """The decompressed response exceeded the configured safety bound."""


class NotionSchemaError(NotionError):
    """稿件库字段缺失或类型与契约不符，错误信息包含字段名。"""


@dataclass(frozen=True)
class NotionFile:
    """Notion 文件对象（内置 ``file`` 或外链 ``external``）；外链没有过期时间。"""

    name: str
    url: str
    expiry_time: datetime | None = None


@dataclass(frozen=True)
class MappedNotionPage:
    """按 spec §6 字段约定映射后的 Notion 稿件页面。"""

    page_id: str
    url: str
    title: str
    status: str
    automation_status: str | None
    target_channels: list[str]
    planned_raw: str | None
    categories: list[str]
    summary: str
    cover: NotionFile | None
    last_edited_at: datetime
