"""机翻凭证类型：有效配置的读取口在 integrations.credentials seam（IntegrationCredentials）。"""

from dataclasses import dataclass, field
from typing import ClassVar, Literal


@dataclass(frozen=True)
class BaiduTranslationConfig:
    priority: int
    app_id: str = field(repr=False)
    app_key: str = field(repr=False)
    provider: ClassVar[Literal["translate_baidu"]] = "translate_baidu"


@dataclass(frozen=True)
class AliyunTranslationConfig:
    priority: int
    access_key_id: str = field(repr=False)
    access_key_secret: str = field(repr=False)
    provider: ClassVar[Literal["translate_aliyun"]] = "translate_aliyun"


type TranslationConfig = BaiduTranslationConfig | AliyunTranslationConfig
