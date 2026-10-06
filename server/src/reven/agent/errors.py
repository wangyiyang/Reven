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
    """原生 Agent 运行时或检查点执行失败。"""


class AgentModelUnavailableError(AgentError):
    """指令指定的模型未配置、未启用或拉起失败。

    对齐 OpenClaw 语义：用户显式选择的模型不可达时明确报错，绝不静默降级到默认模型。
    message 只含模型 ref（provider/model），不含任何凭证信息。
    """

    def __init__(self, model_ref: str, reason: str = "未配置或未启用") -> None:
        super().__init__("AGENT_MODEL_UNAVAILABLE", f"模型 {model_ref} 不可用：{reason}")
        self.model_ref = model_ref
