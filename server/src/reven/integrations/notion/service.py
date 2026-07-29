"""Notion 集成服务层：连接测试适配器注册与字段初始化编排。"""

from typing import Any

import httpx

from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.models import NotionConfigError, NotionError, NotionSchemaError, NotionTransientError
from reven.integrations.notion.schema import bootstrap_data_source_schema
from reven.integrations.service import (
    ConnectionTestResult,
    IntegrationError,
    IntegrationService,
    public_config_without_hint,
    register_connection_test_adapter,
)
from reven.security.secrets import SecretBoxError

NOTION_BASE_URL = "https://api.notion.com"
REQUEST_TIMEOUT = httpx.Timeout(30.0)


async def test_notion_connection(public_config: dict[str, Any], secrets: dict[str, str] | None) -> ConnectionTestResult:
    """连接测试只调用 Retrieve Data Source，绝不触发字段初始化。"""
    token = secrets.get("token") if secrets else None
    if not token:
        return ConnectionTestResult(success=False, message="Notion Token 未配置")
    data_source_id = public_config.get("data_source_id")
    if not data_source_id:
        return ConnectionTestResult(success=False, message="Notion data_source_id 未配置")
    try:
        async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
            client = NotionClient(token=token, http=http)
            await client.retrieve_data_source(str(data_source_id))
    except NotionError as exc:
        return ConnectionTestResult(success=False, message=str(exc))
    return ConnectionTestResult(success=True)


def register_notion_adapter() -> None:
    """把 Notion 连接测试适配器注册进 IntegrationService 的适配器注册表。"""
    register_connection_test_adapter("notion", test_notion_connection)


async def bootstrap_notion_schema(service: IntegrationService) -> dict[str, Any] | None:
    """用已存储的 Notion Token 初始化稿件库字段；返回实际发送的 PATCH properties 或 None。"""
    integration = await service.get_integration("notion")
    if integration.encrypted_secret is None:
        raise IntegrationError(
            status_code=409, code="NOTION_SECRET_NOT_CONFIGURED", message="请先配置 Notion Token，再初始化字段"
        )
    try:
        secrets = service.secret_box.decrypt(integration.encrypted_secret)
    except SecretBoxError as exc:
        raise IntegrationError(
            status_code=500, code="INTEGRATION_SECRET_INVALID", message="集成 notion 的 Secret 密文无法解密，请重新配置"
        ) from exc
    data_source_id = public_config_without_hint(integration).get("data_source_id")
    if data_source_id is None:
        raise IntegrationError(
            status_code=409, code="NOTION_DATA_SOURCE_MISSING", message="Notion data_source_id 未配置"
        )
    try:
        async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
            client = NotionClient(token=secrets.get("token", ""), http=http)
            return await bootstrap_data_source_schema(client, str(data_source_id))
    except NotionConfigError as exc:
        raise IntegrationError(status_code=400, code="NOTION_CONFIG_INVALID", message=str(exc)) from exc
    except NotionTransientError as exc:
        raise IntegrationError(status_code=503, code="NOTION_UNAVAILABLE", message=str(exc)) from exc
    except NotionSchemaError as exc:
        raise IntegrationError(status_code=409, code="NOTION_SCHEMA_CONFLICT", message=str(exc)) from exc
