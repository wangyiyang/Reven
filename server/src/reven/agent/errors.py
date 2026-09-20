"""Agent 领域错误类型。"""


class AgentError(Exception):
    """Agent 错误基类，携带稳定错误码供 API 映射。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentNotConfiguredError(AgentError):
    """未配置 agent API Key（agent-llm 集成缺失）时的错误。"""

    def __init__(self) -> None:
        super().__init__("AGENT_NOT_CONFIGURED", "Agent 未配置 API Key")


class AgentRuntimeError(AgentError):
    """dsh 运行时启动或会话执行失败。"""
