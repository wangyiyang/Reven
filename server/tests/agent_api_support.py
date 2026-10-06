"""API 边界替身；领域执行与持久化由 Agent 集成测试验证。"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from reven.agent.context import AgentActor
from reven.agent.errors import AgentError
from reven.agent.service_types import AgentTurn, ApprovalState, ConfigurationState, OperationState, RunState

RUN_ID = UUID("ec49892c-4ef1-451d-9544-314136cff104")
REVISION_ID = UUID("db2c5c8d-46ad-4da4-b6dc-f42754b39181")
APPROVAL_ID = UUID("4c649e0e-04ec-4a58-9f6f-44b30326c6f9")
NOW = datetime(2026, 10, 6, tzinfo=UTC)
CONFIGURATION = ConfigurationState(REVISION_ID, 2, "经营助手指令", ("list_customers", "delete_customer"))
RUN = RunState(
    id=RUN_ID,
    session_id="rest-session",
    status="waiting_approval",
    response="请确认删除客户。",
    model_ref="deepseek-official/deepseek-v4-flash",
    is_override=False,
    error_code=None,
    approvals=(
        ApprovalState(APPROVAL_ID, "call-delete", "delete_customer", {"customer_id": "42"}, "客户甲", "pending"),
    ),
    operations=(
        OperationState(
            UUID("f47a888a-cfba-49fd-b0ab-8b245148de88"),
            "call-create",
            "create_customer",
            {"name": "客户甲"},
            {"output": "已创建"},
        ),
    ),
    created_at=NOW,
    updated_at=NOW,
    message="删除客户甲",
)


class ApiAgentStub:
    def __init__(self, *, error: AgentError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[object, ...]] = []
        self.turn = AgentTurn("sess-fixed", "回声", RUN.model_ref, False, RUN_ID)
        self.configuration = CONFIGURATION
        self.run = RUN

    def _record(self, *args: object) -> None:
        self.calls.append(args)
        if self.error is not None:
            raise self.error

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self._record("chat", message, session_id, actor, request_key, wait_timeout_seconds)
        return self.turn

    async def get_configuration(self) -> ConfigurationState:
        self._record("get_configuration")
        return self.configuration

    async def update_configuration(self, prompt: str, tool_names: list[str]) -> ConfigurationState:
        self._record("update_configuration", prompt, tool_names)
        return replace(self.configuration, prompt=prompt, tool_names=tuple(tool_names))

    async def get_revision(self, revision_id: UUID) -> ConfigurationState:
        self._record("get_revision", revision_id)
        return self.configuration

    async def history(self, session_id: str, *, actor: AgentActor) -> tuple[RunState, ...]:
        self._record("history", session_id, actor)
        return (self.run,)

    async def get_run(self, run_id: UUID, *, actor: AgentActor, session_id: str | None = None) -> RunState:
        self._record("get_run", run_id, actor, session_id)
        return self.run

    async def resolve_approval(
        self, approval_id: UUID, decision: Literal["approve", "reject"], session_id: str, *, actor: AgentActor
    ) -> RunState:
        self._record("resolve_approval", approval_id, decision, session_id, actor)
        return self.run

    async def resume_run(self, run_id: UUID, *, actor: AgentActor, session_id: str | None = None) -> AgentTurn:
        self._record("resume_run", run_id, actor, session_id)
        return self.turn
