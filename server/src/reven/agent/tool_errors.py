"""Controlled failures at the trusted business execution boundary."""

from reven.agent.errors import AgentError


class AgentToolContextError(AgentError):
    def __init__(self) -> None:
        super().__init__("AGENT_TOOL_CONTEXT_INVALID", "工具调用缺少有效的运行上下文")


class AgentOperationConflictError(AgentError):
    def __init__(self) -> None:
        super().__init__("AGENT_OPERATION_CONFLICT", "工具调用编号与已保存的操作不一致")


class AgentToolApprovalError(AgentError):
    def __init__(self) -> None:
        super().__init__("AGENT_TOOL_APPROVAL_REQUIRED", "删除未执行：需要原用户批准当前目标与参数")


class AgentToolDependencyError(AgentError):
    def __init__(self, previous_call_id: str, current_call_id: str) -> None:
        super().__init__(
            "AGENT_TOOL_DEPENDENCY_FAILED",
            f"前序工具调用 {previous_call_id} 未完成，当前调用 {current_call_id} 未执行",
        )
