"""仅通过 HTTPS 访问的 Notion API 客户端。

调用方负责创建并管理注入的 ``httpx.AsyncClient``（base_url 必须是 HTTPS，
例如 ``https://api.notion.com``）。错误统一分类为
``NotionConfigError`` / ``NotionTransientError``，错误信息中的响应正文摘录
会先脱敏（以 Token 为已知 Secret），绝不携带明文凭证。
"""

import json
import math
from typing import Any, NoReturn

import httpx

from reven.integrations.notion.models import NotionConfigError, NotionSchemaError, NotionTransientError
from reven.security.redaction import redact

_BODY_EXCERPT_LENGTH = 500
_DEFAULT_RETRY_AFTER = 1.0


class NotionClient:
    API_VERSION = "2026-03-11"

    def __init__(self, token: str, http: httpx.AsyncClient) -> None:
        if http.base_url.scheme != "https":
            raise ValueError("NotionClient 仅允许 HTTPS base URL")
        self._token = token
        self.http = http
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    async def query_data_source(
        self,
        data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"page_size": 100, "result_type": "page"}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return await self._request(
            "POST",
            f"/v1/data_sources/{data_source_id}/query",
            json=payload,
        )

    async def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/data_sources/{data_source_id}")

    async def update_data_source(self, data_source_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/v1/data_sources/{data_source_id}", json={"properties": properties})

    async def retrieve_page_markdown(self, page_id: str) -> str:
        result = await self._request("GET", f"/v1/pages/{page_id}/markdown")
        markdown = result.get("markdown")
        if not isinstance(markdown, str):
            raise NotionSchemaError("字段 markdown 缺失或不是字符串，Notion 响应契约可能已变化")
        return markdown

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self.http.request(method, path, headers=self.headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise NotionTransientError("Notion 请求超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise NotionTransientError(f"Notion 请求失败（{type(exc).__name__}），请稍后重试") from exc
        if response.is_success:
            try:
                payload: dict[str, Any] = response.json()
            except json.JSONDecodeError as exc:
                excerpt = redact(response.text[:_BODY_EXCERPT_LENGTH], [self._token])
                raise NotionTransientError(f"Notion 响应格式异常，可重试：{excerpt}") from exc
            return payload
        self._raise_for_status(response)

    def _raise_for_status(self, response: httpx.Response) -> NoReturn:
        # 注意：Notion 409 conflict 官方语义可重试，这里刻意归入不可重试的配置错误（安全方向，不误重试）
        excerpt = redact(response.text[:_BODY_EXCERPT_LENGTH], [self._token])
        status = response.status_code
        if status == 429:
            raise NotionTransientError(
                f"Notion 限流（HTTP 429）：{excerpt}",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )
        if status in (401, 403, 404):
            raise NotionConfigError(f"Notion 配置无效（HTTP {status}），请检查 Token 与数据源权限：{excerpt}")
        if status >= 500:
            raise NotionTransientError(f"Notion 服务异常（HTTP {status}）：{excerpt}")
        raise NotionConfigError(f"Notion 请求被拒绝（HTTP {status}）：{excerpt}")


def _parse_retry_after(value: str | None) -> float:
    if value is None:
        return _DEFAULT_RETRY_AFTER
    try:
        seconds = float(value)
    except ValueError:
        return _DEFAULT_RETRY_AFTER
    if not math.isfinite(seconds):
        return _DEFAULT_RETRY_AFTER
    return max(seconds, 0.0)
