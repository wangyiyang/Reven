"""feishu_bot 共享配置加载：supervisor（长连接）与推送管道（审核卡片）共用一个读取口。

配置缺失/禁用/凭证不完整/读取或解密失败均返回 None，由调用方跳过；
日志只记 provider + 异常类型，绝不带配置内容、密文或凭证。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.db import session_scope
from reven.integrations.repository import IntegrationRepository
from reven.security.secrets import SecretBox

logger = logging.getLogger(__name__)

PROVIDER = "feishu_bot"


@dataclass(frozen=True)
class FeishuBotConfig:
    app_id: str = field(repr=False)
    app_secret: str = field(repr=False)
    whitelist_open_ids: tuple[str, ...]


async def load_feishu_bot_config(
    session_factory: async_sessionmaker[AsyncSession],
    secret_box: SecretBox,
) -> FeishuBotConfig | None:
    """读取 integrations 表中 feishu_bot 的有效配置；任何不可用情形都返回 None。"""
    try:
        async with session_scope(session_factory) as session:
            integration = await IntegrationRepository(session).get_by_provider(PROVIDER)
        if integration is None or integration.public_config.get("enabled") is not True:
            return None
        if integration.encrypted_secret is None:
            return None
        secret = secret_box.decrypt(integration.encrypted_secret)
    except Exception as exc:
        # 脱敏：只记 provider + 异常类型，不带配置/密文内容
        logger.warning("飞书机器人配置读取失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        return None
    app_id = secret.get("app_id")
    app_secret = secret.get("app_secret")
    if not app_id or not app_secret:
        return None
    return FeishuBotConfig(
        app_id=app_id,
        app_secret=app_secret,
        whitelist_open_ids=_parse_whitelist(integration.public_config.get("whitelist_open_ids")),
    )


def _parse_whitelist(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)
