"""Agent 业务入口：对话编排的接缝层（M4 工具集、系统提示词将在此组装）。"""

from reven.agent.runtime import AgentRuntime


class AgentService:
    """面向 API 层的对话服务；首版薄封装 runtime，保持上游变动隔离在一处。"""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def chat(self, message: str, session_id: str | None = None, *, model: str | None = None) -> tuple[str, str]:
        """执行一轮对话，返回 (session_id, 最终响应文本)。

        未配置抛 AgentNotConfiguredError（503）；运行时不可用/失败抛 AgentRuntimeError（502）；
        model 为会话级 override 模型引用（provider/model），不可达抛 AgentModelUnavailableError。
        """
        return await self._runtime.chat(message, session_id, model=model)
