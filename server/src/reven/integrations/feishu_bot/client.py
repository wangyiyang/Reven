"""飞书应用 API：通知消息发送与多维表格（Bitable）共用鉴权与脱敏错误处理。"""

import json
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from reven.integrations.feishu_bot.cards import build_markdown_card
from reven.notifications import Notification

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BOT_INFO_URL = "https://open.feishu.cn/open-apis/bot/v3/info"
MESSAGES_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
BITABLE_APPS_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
_MAX_RESPONSE_BYTES = 64 * 1024
# 多维表格写接口单批上限 500 条（官方限制），查询单页上限 500
BITABLE_MAX_BATCH_SIZE = 500
BITABLE_MAX_PAGE_SIZE = 500


class FeishuBotApiError(Exception):
    """只包含固定提示和数字错误码，不暴露响应正文、凭证或令牌。

    code 为飞书开放平台数字错误码（无平台码的失败为 None），供日志记录稳定码（#176）。
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BitableField:
    """多维表格字段元数据（type 为官方字段类型数字编码）。

    options 仅单选/多选类字段非空（取自 property.options[*].name），
    供写入方预检单选选项是否已配置。
    """

    field_id: str
    name: str
    type: int
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class BitableRecord:
    """多维表格记录：record_id + 原始 fields 字典。"""

    record_id: str
    fields: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class BitableRecordPage:
    """records/search 单页结果。"""

    records: tuple[BitableRecord, ...]
    page_token: str | None
    has_more: bool


@dataclass(frozen=True)
class BitableRecordWrite:
    """待创建记录；client_token 供幂等去重（同 token 重复创建被飞书拒绝）。"""

    fields: dict[str, Any]
    client_token: str | None = None


@dataclass(frozen=True)
class BitableRecordUpdate:
    """待更新记录：record_id + 要写入的 fields。"""

    record_id: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class BitableFilterCondition:
    """search 过滤条件（operator 取官方枚举：is/contains/isNot 等）。"""

    field_name: str
    operator: str
    value: tuple[str, ...]


class FeishuBotApiClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = http
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def _tenant_token(self) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        payload = await self._request(
            "POST",
            TENANT_TOKEN_URL,
            body={"app_id": self._app_id, "app_secret": self._app_secret},
            error="飞书应用凭证无效",
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuBotApiError("飞书应用凭证无效")
        self._token = token
        expire = payload.get("expire", 7200)
        self._token_expires_at = time.monotonic() + max(expire - 60, 0) if isinstance(expire, int) else 0
        return token

    async def verify_bot(self) -> None:
        await self._request(
            "GET",
            BOT_INFO_URL,
            token=await self._tenant_token(),
            error="飞书机器人信息获取失败（请确认已开通并发布机器人能力）",
        )

    async def get_bot_open_id(self) -> str:
        """获取机器人自身 open_id（群聊 @ 判定用）；复用 verify_bot 同一端点与 token 缓存。"""
        payload = await self._request(
            "GET",
            BOT_INFO_URL,
            token=await self._tenant_token(),
            error="飞书机器人信息获取失败（请确认已开通并发布机器人能力）",
        )
        bot = payload.get("bot")
        open_id = bot.get("open_id") if isinstance(bot, dict) else None
        if not isinstance(open_id, str) or not open_id:
            raise FeishuBotApiError("飞书机器人信息响应格式无效")
        return open_id

    async def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        *,
        resource_type: str = "file",
    ) -> bytes:
        """从消息中下载附件资源（如 Excel 报表文件）。"""
        token = await self._tenant_token()
        url = f"{MESSAGES_URL}/{quote(message_id)}/resources/{quote(file_key)}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": resource_type}
        if self._http is not None:
            resp = await self._http.get(url, headers=headers, params=params, timeout=60.0, follow_redirects=True)
        else:
            async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
                resp = await client.get(url, headers=headers, params=params, follow_redirects=True)
        if resp.status_code != 200:
            raise FeishuBotApiError(f"飞书附件下载失败（HTTP {resp.status_code}）")
        return resp.content

    async def send_text(self, open_id: str, text: str) -> None:
        await self._send_message(open_id, "text", {"text": text})

    async def send_markdown(self, open_id: str, markdown: str, *, title: str | None = None) -> None:
        await self._deliver(
            partial(self._send_message, open_id),
            build_markdown_card(markdown, title=title),
            _markdown_text(markdown, title),
        )

    async def send_markdown_to_chat(self, chat_id: str, markdown: str, *, title: str | None = None) -> None:
        await self._deliver(
            partial(self._send_message, chat_id, receive_id_type="chat_id"),
            build_markdown_card(markdown, title=title),
            _markdown_text(markdown, title),
        )

    async def reply_markdown(self, message_id: str, markdown: str, *, title: str | None = None) -> None:
        await self._deliver(
            partial(self._reply_message, message_id),
            build_markdown_card(markdown, title=title),
            _markdown_text(markdown, title),
        )

    async def send_text_to_recipients(self, recipients: tuple[str, ...], text: str) -> None:
        await self._send_to_recipients(recipients, lambda open_id: self.send_text(open_id, text))

    async def send_markdown_to_recipients(
        self, recipients: tuple[str, ...], markdown: str, *, title: str | None = None
    ) -> None:
        await self._send_to_recipients(
            recipients,
            lambda open_id: self.send_markdown(open_id, markdown, title=title),
        )

    async def send_notification_to_recipients(self, recipients: tuple[str, ...], notification: Notification) -> None:
        markdown = f"**当前阶段**：{notification.stage}\n\n{notification.summary}"
        if notification.links:
            markdown += "\n\n" + "　".join(f"[{label}]({url})" for label, url in notification.links.items())
        lines = [notification.title, f"当前阶段：{notification.stage}", notification.summary]
        lines.extend(f"{label}：{url}" for label, url in notification.links.items())
        card = build_markdown_card(markdown, title=notification.title)
        await self._send_to_recipients(
            recipients,
            lambda open_id: self._deliver(partial(self._send_message, open_id), card, "\n".join(lines)),
        )

    async def _deliver(
        self,
        send: Callable[[str, dict[str, Any]], Awaitable[None]],
        card: dict[str, Any],
        text: str,
    ) -> None:
        """同目标卡片失败才尝试文本；两种表示都失败则显式传播。"""
        try:
            await send("interactive", card)
        except FeishuBotApiError:
            await send("text", {"text": text})

    async def _send_to_recipients(
        self, recipients: tuple[str, ...], send_one: Callable[[str], Awaitable[None]]
    ) -> None:
        if not recipients:
            raise FeishuBotApiError("请先配置通知接收人 Open ID")
        failures: list[FeishuBotApiError] = []
        for open_id in recipients:
            try:
                await send_one(open_id)
            except FeishuBotApiError as exc:
                failures.append(exc)
        if failures:
            delivered = len(recipients) - len(failures)
            raise FeishuBotApiError(f"{failures[0]}；已发送 {delivered}/{len(recipients)} 位接收人")

    async def _send_message(
        self, receive_id: str, msg_type: str, content: dict[str, Any], *, receive_id_type: str = "open_id"
    ) -> None:
        await self._request(
            "POST",
            f"{MESSAGES_URL}?receive_id_type={receive_id_type}",
            token=await self._tenant_token(),
            body={"receive_id": receive_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            error="飞书消息发送失败",
        )

    async def _reply_message(self, message_id: str, msg_type: str, content: dict[str, Any]) -> None:
        await self._request(
            "POST",
            f"{MESSAGES_URL}/{quote(message_id, safe='')}/reply",
            token=await self._tenant_token(),
            body={"msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            error="飞书消息回复失败",
        )

    # --- 多维表格（Bitable）---

    async def list_fields(self, app_token: str, table_id: str) -> tuple[BitableField, ...]:
        """列出目标表全部字段（自动翻页）；供绑定测试的字段校验使用。"""
        fields: list[BitableField] = []
        page_token: str | None = None
        while True:
            query: dict[str, str | int] = {"page_size": BITABLE_MAX_PAGE_SIZE}
            if page_token is not None:
                query["page_token"] = page_token
            url = f"{_bitable_table_url(app_token, table_id)}/fields?{urlencode(query)}"
            payload = await self._request(
                "GET", url, token=await self._tenant_token(), error="飞书多维表格字段查询失败"
            )
            data = _bitable_data(payload)
            items = data.get("items")
            if not isinstance(items, list):
                raise FeishuBotApiError("飞书多维表格响应格式无效")
            fields.extend(_parse_bitable_field(item) for item in items)
            next_token = data.get("page_token")
            if data.get("has_more") is True and isinstance(next_token, str) and next_token:
                page_token = next_token
                continue
            return tuple(fields)

    async def search_records(
        self,
        app_token: str,
        table_id: str,
        *,
        filter_conditions: Sequence[BitableFilterCondition] | None = None,
        page_size: int = BITABLE_MAX_PAGE_SIZE,
        page_token: str | None = None,
    ) -> BitableRecordPage:
        """按条件只读查询记录（单页）；page_size 收敛到 [1, 500]。"""
        query: dict[str, str | int] = {"page_size": max(1, min(page_size, BITABLE_MAX_PAGE_SIZE))}
        if page_token is not None:
            query["page_token"] = page_token
        url = f"{_bitable_table_url(app_token, table_id)}/records/search?{urlencode(query)}"
        body: dict[str, Any] = {}
        if filter_conditions:
            body["filter"] = {
                "conjunction": "and",
                "conditions": [
                    {"field_name": condition.field_name, "operator": condition.operator, "value": list(condition.value)}
                    for condition in filter_conditions
                ],
            }
        payload = await self._request(
            "POST", url, token=await self._tenant_token(), body=body, error="飞书多维表格记录查询失败"
        )
        data = _bitable_data(payload)
        items = data.get("items")
        if not isinstance(items, list):
            raise FeishuBotApiError("飞书多维表格响应格式无效")
        next_token = data.get("page_token")
        return BitableRecordPage(
            records=tuple(_parse_bitable_record(item) for item in items),
            page_token=next_token if isinstance(next_token, str) and next_token else None,
            has_more=data.get("has_more") is True,
        )

    async def batch_create_records(
        self, app_token: str, table_id: str, records: Sequence[BitableRecordWrite]
    ) -> tuple[BitableRecord, ...]:
        """批量创建记录；超过单批 500 条自动分批，返回全部已创建记录。"""
        created: list[BitableRecord] = []
        for chunk in _bitable_chunks(records):
            body = {
                "records": [
                    {"fields": record.fields, **({"client_token": record.client_token} if record.client_token else {})}
                    for record in chunk
                ]
            }
            payload = await self._request(
                "POST",
                f"{_bitable_table_url(app_token, table_id)}/records/batch_create",
                token=await self._tenant_token(),
                body=body,
                error="飞书多维表格记录创建失败",
            )
            data = _bitable_data(payload)
            items = data.get("records")
            if not isinstance(items, list):
                raise FeishuBotApiError("飞书多维表格响应格式无效")
            created.extend(_parse_bitable_record(item) for item in items)
        return tuple(created)

    async def batch_update_records(
        self, app_token: str, table_id: str, records: Sequence[BitableRecordUpdate]
    ) -> tuple[BitableRecord, ...]:
        """批量更新记录；超过单批 500 条自动分批，返回全部已更新记录。"""
        updated: list[BitableRecord] = []
        for chunk in _bitable_chunks(records):
            body = {"records": [{"record_id": record.record_id, "fields": record.fields} for record in chunk]}
            payload = await self._request(
                "POST",
                f"{_bitable_table_url(app_token, table_id)}/records/batch_update",
                token=await self._tenant_token(),
                body=body,
                error="飞书多维表格记录更新失败",
            )
            data = _bitable_data(payload)
            items = data.get("records")
            if not isinstance(items, list):
                raise FeishuBotApiError("飞书多维表格响应格式无效")
            updated.extend(_parse_bitable_record(item) for item in items)
        return tuple(updated)

    async def batch_delete_records(self, app_token: str, table_id: str, record_ids: Sequence[str]) -> None:
        """批量删除记录；超过单批 500 条自动分批。"""
        for chunk in _bitable_chunks(record_ids):
            await self._request(
                "POST",
                f"{_bitable_table_url(app_token, table_id)}/records/batch_delete",
                token=await self._tenant_token(),
                body={"records": list(chunk)},
                error="飞书多维表格记录删除失败",
            )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        error: str,
    ) -> dict[str, Any]:
        # 注入的共享 client（ProviderClients 长驻实例）直接使用且不在这里关闭；
        # 否则按请求自建造 client，保持 timeout=10s / trust_env=False 策略不变。
        if self._http is not None:
            return await self._request_via(self._http, method, url, body=body, token=token, error=error)
        async with httpx.AsyncClient(timeout=10, trust_env=False, transport=self._transport) as http:
            return await self._request_via(http, method, url, body=body, token=token, error=error)

    async def _request_via(
        self,
        http: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        token: str | None,
        error: str,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with http.stream(method, url, json=body, headers=headers) as response:
                payload = await _read_payload(response)
                code = payload.get("code")
                if type(code) is not int:
                    raise FeishuBotApiError("飞书应用响应格式无效")
                if code != 0:
                    if code in {99991672, 99991679} and url.startswith(MESSAGES_URL):
                        error = "飞书发消息权限不足，请开通 im:message:send_as_bot 并发布应用"
                    raise FeishuBotApiError(f"{error}（code={code}）", code=code)
                if not response.is_success:
                    raise FeishuBotApiError(f"{error}（HTTP {response.status_code}）")
                return payload
        except httpx.HTTPError as exc:
            raise FeishuBotApiError(f"飞书应用连接失败（{type(exc).__name__}）") from None


def _markdown_text(markdown: str, title: str | None) -> str:
    return f"{title}\n{markdown}" if title else markdown


async def _read_payload(response: httpx.Response) -> dict[str, Any]:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise FeishuBotApiError("飞书应用响应超过大小限制")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FeishuBotApiError("飞书应用响应格式无效") from None
    if not isinstance(payload, dict):
        raise FeishuBotApiError("飞书应用响应格式无效")
    return payload


def _bitable_table_url(app_token: str, table_id: str) -> str:
    return f"{BITABLE_APPS_URL}/{quote(app_token, safe='')}/tables/{quote(table_id, safe='')}"


def _bitable_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise FeishuBotApiError("飞书多维表格响应格式无效")
    return data


def _parse_bitable_field(item: object) -> BitableField:
    if not isinstance(item, dict):
        raise FeishuBotApiError("飞书多维表格响应格式无效")
    field_id = item.get("field_id")
    name = item.get("field_name")
    field_type = item.get("type")
    if not isinstance(field_id, str) or not isinstance(name, str) or type(field_type) is not int:
        raise FeishuBotApiError("飞书多维表格响应格式无效")
    return BitableField(
        field_id=field_id, name=name, type=field_type, options=_parse_field_options(item.get("property"))
    )


def _parse_field_options(property_value: object) -> tuple[str, ...]:
    if not isinstance(property_value, dict):
        return ()
    options = property_value.get("options")
    if not isinstance(options, list):
        return ()
    return tuple(
        option["name"] for option in options if isinstance(option, dict) and isinstance(option.get("name"), str)
    )


def _parse_bitable_record(item: object) -> BitableRecord:
    if not isinstance(item, dict):
        raise FeishuBotApiError("飞书多维表格响应格式无效")
    record_id = item.get("record_id")
    fields = item.get("fields")
    if not isinstance(record_id, str) or not isinstance(fields, dict):
        raise FeishuBotApiError("飞书多维表格响应格式无效")
    return BitableRecord(record_id=record_id, fields=fields)


def _bitable_chunks(items: Sequence[Any]) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), BITABLE_MAX_BATCH_SIZE):
        yield items[start : start + BITABLE_MAX_BATCH_SIZE]
