"""飞书资源绑定领域服务：CRUD + 每用途单启用约束 + 前置校验。

- resource_type / purpose 白名单在 schema 层（Literal → 422）与服务层双重校验；
- 创建要求 feishu_bot 集成已配置且已启用；
- 启用/创建启用态绑定的唯一性冲突由部分唯一索引兜底，映射为 409；
- 绑定测试探针（真实读写目标表）在 feishu_bot.bitable 模块，路由层组合调用。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.integrations.feishu_bot.config import PROVIDER as FEISHU_BOT_PROVIDER
from reven.integrations.models import FeishuResourceBinding
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import IntegrationError

RESOURCE_TYPE_BITABLE = "bitable"
PURPOSE_RSS_CANDIDATES = "rss_candidates"
SUPPORTED_RESOURCE_TYPES = (RESOURCE_TYPE_BITABLE,)
SUPPORTED_PURPOSES = (PURPOSE_RSS_CANDIDATES,)


class FeishuResourceBindingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_bindings(self) -> list[FeishuResourceBinding]:
        statement = select(FeishuResourceBinding).order_by(FeishuResourceBinding.created_at)
        result = await self._session.scalars(statement)
        return list(result)

    async def get_binding(self, binding_id: UUID) -> FeishuResourceBinding:
        binding = await self._session.get(FeishuResourceBinding, binding_id)
        if binding is None:
            raise IntegrationError(status_code=404, code="BINDING_NOT_FOUND", message="资源绑定不存在")
        return binding

    async def create_binding(
        self,
        *,
        resource_type: str,
        purpose: str,
        config: dict[str, object],
        enabled: bool,
    ) -> FeishuResourceBinding:
        _validate_whitelist(resource_type, purpose)
        integration = await IntegrationRepository(self._session).get_by_provider(FEISHU_BOT_PROVIDER)
        if integration is None or integration.public_config.get("enabled") is not True:
            raise IntegrationError(
                status_code=409,
                code="FEISHU_BOT_NOT_ENABLED",
                message="请先配置并启用飞书应用机器人集成",
            )
        binding = FeishuResourceBinding(
            integration_id=integration.id,
            resource_type=resource_type,
            purpose=purpose,
            config=config,
            enabled=enabled,
        )
        self._session.add(binding)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise _purpose_conflict(purpose) from exc
        return binding

    async def update_config(self, binding_id: UUID, *, config: dict[str, object]) -> FeishuResourceBinding:
        binding = await self.get_binding(binding_id)
        binding.config = config
        await self._session.flush()
        return binding

    async def set_enabled(self, binding_id: UUID, *, enabled: bool) -> FeishuResourceBinding:
        binding = await self.get_binding(binding_id)
        # 先取 purpose：flush 失败后事务进入回滚态，此时再读 ORM 属性会触发刷新查询而抛 PendingRollbackError
        purpose = binding.purpose
        binding.enabled = enabled
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise _purpose_conflict(purpose) from exc
        return binding

    async def delete_binding(self, binding_id: UUID) -> None:
        binding = await self.get_binding(binding_id)
        await self._session.delete(binding)
        await self._session.flush()


def _validate_whitelist(resource_type: str, purpose: str) -> None:
    if resource_type not in SUPPORTED_RESOURCE_TYPES or purpose not in SUPPORTED_PURPOSES:
        raise IntegrationError(
            status_code=422,
            code="BINDING_UNSUPPORTED",
            message=f"不支持的资源绑定类型或用途：{resource_type}/{purpose}",
        )


def _purpose_conflict(purpose: str) -> IntegrationError:
    return IntegrationError(
        status_code=409,
        code="BINDING_PURPOSE_CONFLICT",
        message=f"用途 {purpose} 已存在启用的绑定，请先禁用其他绑定",
    )
