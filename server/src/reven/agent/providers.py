"""显式模型协议映射；密钥仅在模型客户端生命周期内使用。"""

from typing import Any

import httpx
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from reven.agent.errors import AgentModelUnavailableError
from reven.integrations.providers import model_ref_of
from reven.security.origin import normalize_origin

OPENAI_COMPATIBLE_PROVIDERS = frozenset({"openai", "openai-compatible", "siliconflow"})


class RevenChatDeepSeek(ChatDeepSeek):
    """补充官方适配器未回传的推理字段，保留其响应与工具处理。"""

    def _get_request_payload(
        self, input_: LanguageModelInput, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        payload: dict[str, Any] = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for message, encoded in zip(messages, payload["messages"], strict=True):
            if isinstance(message, AIMessage):
                reasoning = message.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    encoded["reasoning_content"] = reasoning
        return payload


def _api_base(provider: str, base_url: str | None) -> str:
    if base_url is not None:
        origin = normalize_origin(base_url)
        if not origin.startswith("https://"):
            raise ValueError("模型端点必须使用 HTTPS origin")
        return origin if provider == "deepseek-official" else f"{origin}/v1"
    if provider == "deepseek-official":
        return "https://api.deepseek.com"
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "siliconflow":
        return "https://api.siliconflow.cn/v1"
    raise ValueError("兼容端点必须配置 base_url")


def build_chat_model(
    provider: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    *,
    http_async_client: httpx.AsyncClient | None = None,
    http_client: httpx.Client | None = None,
) -> BaseChatModel:
    model_ref = model_ref_of(provider, model)
    if provider != "deepseek-official" and provider not in OPENAI_COMPATIBLE_PROVIDERS:
        raise AgentModelUnavailableError(model_ref, "未支持该 Provider 协议")
    if not api_key:
        raise AgentModelUnavailableError(model_ref, "未配置凭证")
    try:
        endpoint = _api_base(provider, base_url)
    except ValueError:
        raise AgentModelUnavailableError(model_ref, "模型端点配置无效") from None
    options: dict[str, Any] = {
        "model": model,
        "api_key": SecretStr(api_key),
        "base_url": endpoint,
        "http_async_client": http_async_client or httpx.AsyncClient(timeout=60, trust_env=False),
        "http_client": http_client or httpx.Client(timeout=60, trust_env=False),
        "max_retries": 0,
        "timeout": 60,
    }
    if provider == "deepseek-official":
        return RevenChatDeepSeek(**options)
    return ChatOpenAI(**options, use_responses_api=False)
