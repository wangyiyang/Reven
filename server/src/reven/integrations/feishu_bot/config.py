"""feishu_bot 凭证类型与白名单解析；有效配置的读取口在 integrations.credentials seam。

日志脱敏纪律：任何配置读取失败只记 provider + 异常类型，绝不带配置内容、密文或凭证。
"""

from dataclasses import dataclass, field

PROVIDER = "feishu_bot"


@dataclass(frozen=True)
class FeishuBotConfig:
    app_id: str = field(repr=False)
    app_secret: str = field(repr=False)
    whitelist_open_ids: tuple[str, ...]


def parse_whitelist(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(dict.fromkeys(value.strip() for value in raw if isinstance(value, str) and value.strip()))
