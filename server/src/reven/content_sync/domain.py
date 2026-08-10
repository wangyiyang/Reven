"""Stable domain vocabulary for content synchronization."""

from enum import StrEnum


class ContentSyncStatus(StrEnum):
    UNSYNCED = "未同步"
    SYNCING = "同步中"
    SYNCED = "已同步"
    STALE = "已过期"
    FAILED = "同步失败"


class SyncRunStatus(StrEnum):
    WAITING = "等待中"
    PROCESSING = "同步中"
    SUCCEEDED = "已同步"
    FAILED = "同步失败"


class SyncStage(StrEnum):
    WAITING = "等待同步"
    READING_NOTION = "正在读取 Notion"
    DISCOVERING_MEDIA = "正在建立媒体清单"
    DOWNLOADING_MEDIA = "正在下载媒体"
    ARCHIVING_MEDIA = "正在归档媒体"
    COMMITTING_SNAPSHOT = "正在生成内容快照"
    COMPLETED = "同步完成"
    FAILED = "同步失败"
