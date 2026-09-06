"""品牌领域的状态与用途常量。"""

from enum import StrEnum


class BrandVersionStatus(StrEnum):
    DRAFT = "草稿"
    PUBLISHED = "已发布"
    ARCHIVED = "已归档"


class BrandAssetPurpose(StrEnum):
    LOGO = "标志"
    AVATAR = "头像"
    QRCODE = "二维码"
    COVER = "封面"
    OTHER = "其他"


class BrandAssetSource(StrEnum):
    UPLOAD = "上传"
    NOTION_IMPORT = "Notion 导入"


class BrandVersionSource(StrEnum):
    MANUAL = "手动"
    NOTION_IMPORT = "Notion 导入"


class ImportRunStatus(StrEnum):
    RUNNING = "进行中"
    COMPLETED = "已完成"
    FAILED = "失败"
