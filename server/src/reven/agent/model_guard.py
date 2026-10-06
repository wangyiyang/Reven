"""在图保存错误前截断上游异常原文，避免凭据回显进入检查点。"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from reven.agent.context import AgentContext
from reven.agent.errors import AgentModelUnavailableError

logger = logging.getLogger(__name__)


class ModelErrorBoundary(AgentMiddleware[Any, AgentContext]):
    async def awrap_model_call(
        self,
        request: ModelRequest[AgentContext],
        handler: Callable[[ModelRequest[AgentContext]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        try:
            return await handler(request)
        except Exception as error:
            logger.warning("Agent 模型调用失败（error_type=%s）", type(error).__name__)
            model_name = getattr(request.model, "model_name", None) or getattr(request.model, "model", "当前模型")
            raise AgentModelUnavailableError(str(model_name), "调用失败") from None
