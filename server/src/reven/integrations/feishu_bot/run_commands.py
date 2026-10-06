"""飞书确认、状态与恢复指令；解析不经过模型。"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from reven.agent.errors import AgentError
from reven.agent.persistence_types import ApprovalStatus, RunStatus
from reven.agent.service_types import RunState

RUN_USAGE_TEXT = "用法：确认 <确认编号> / 取消 <确认编号> / 状态 <运行编号> / 恢复 <运行编号>"
RESULT_UNAVAILABLE_TEXT = "暂时无法取得结果；操作可能仍在进行，请先核实运行状态，避免重复提交。"
RunAction = Literal["approve", "reject", "status", "resume", "help"]
_ACTIONS: dict[str, RunAction] = {"确认": "approve", "取消": "reject", "状态": "status", "恢复": "resume"}
_STATUS_TEXT = {
    RunStatus.QUEUED: "已接收",
    RunStatus.RUNNING: "处理中",
    RunStatus.WAITING_APPROVAL: "等待确认",
    RunStatus.COMPLETED: "已完成",
    RunStatus.FAILED: "未能完成",
    RunStatus.INTERRUPTED: "已中断",
    RunStatus.NEEDS_RECONCILIATION: "需要核实",
}
_ERROR_TEXT = {
    "AGENT_NOT_CONFIGURED": "Agent 尚未配置模型，请先在集成设置中完成配置。",
    "AGENT_RUNTIME_UNAVAILABLE": "Agent 当前不可用，请检查运行时状态。",
    "AGENT_SESSION_FORBIDDEN": "无法访问该会话。",
    "AGENT_RUN_NOT_FOUND": "运行记录不存在或不可访问。",
    "AGENT_APPROVAL_NOT_FOUND": "确认记录不存在或不属于当前会话。",
    "AGENT_APPROVAL_CONFLICT": "确认已被处理，或原操作和目标已发生变化，请查询原运行。",
    "AGENT_STATE_CONFLICT": "当前运行状态不允许该操作，请查询原运行。",
    "AGENT_RUN_UNRESUMABLE": "该运行暂不能安全恢复，请先核实已有操作结果。",
}


@dataclass(frozen=True)
class RunCommand:
    action: RunAction
    identifier: UUID | None = None


def parse_run_command(text: str) -> RunCommand | None:
    parts = text.strip().split()
    if not parts or parts[0] not in _ACTIONS:
        return None
    if len(parts) != 2:
        return RunCommand("help")
    try:
        identifier = UUID(parts[1])
    except ValueError:
        return RunCommand("help")
    return RunCommand(_ACTIONS[parts[0]], identifier)


def render_run_state(run: RunState) -> str:
    lines = [f"运行 {run.id}：{_STATUS_TEXT[RunStatus(run.status)]}"]
    if run.response:
        lines.append(run.response)
    for approval in run.approvals:
        if approval.status == ApprovalStatus.PENDING:
            lines.extend((f"待确认：{approval.target_summary}", f"确认 {approval.id}", f"取消 {approval.id}"))
    if run.status == RunStatus.INTERRUPTED:
        lines.append(f"可显式继续：恢复 {run.id}")
    return "\n".join(lines)


def render_run_error(error: AgentError) -> str:
    run_id = getattr(error, "run_id", None)
    if isinstance(run_id, UUID):
        return f"运行 {run_id} 尚未完成，请先查询：状态 {run_id}。"
    return _ERROR_TEXT.get(error.code, RESULT_UNAVAILABLE_TEXT)
