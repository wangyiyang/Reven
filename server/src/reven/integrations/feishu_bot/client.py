"""飞书机器人开放平台 API 客户端：薄封装 lark-oapi Client 的消息发送能力。

SDK 调用为同步阻塞风格，async 调用方须以 asyncio.to_thread 包裹；
lark-oapi 延迟导入到真实使用处，避免包导入期触发 SDK 模块级事件循环副作用。
"""

import json
from typing import Any


class FeishuBotApiError(Exception):
    """飞书开放平台消息发送失败（消息只含错误码，不含凭证等敏感信息）。"""


class FeishuBotApiClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        import lark_oapi  # type: ignore[import-untyped]  # 延迟导入

        self._client: Any = lark_oapi.Client.builder().app_id(app_id).app_secret(app_secret).build()

    def send_review_card(self, open_id: str, card: dict[str, Any]) -> None:
        """以 interactive 卡片消息发送给指定 open_id；失败抛 FeishuBotApiError。"""
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody  # type: ignore[import-untyped]

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message.create(request)
        if not response.success():
            raise FeishuBotApiError(f"飞书审核卡片发送失败（code={response.code}）")
