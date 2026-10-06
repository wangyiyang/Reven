"""Agent 对话兼容入口与配置、运行、确认的严格 API schema。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reven.agent.persistence_types import ApprovalStatus, RunStatus


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentChatRequest(_Strict):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class AgentChatResponse(BaseModel):
    session_id: str
    response: str


class AgentConfigurationPut(_Strict):
    prompt: str = Field(min_length=1, max_length=32000)
    tool_names: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(max_length=37)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Agent 指令不能为空")
        return value

    @field_validator("tool_names")
    @classmethod
    def validate_tool_names(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("工具名称不能重复")
        return value


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AgentConfigurationResponse(_Response):
    id: UUID
    version: int
    prompt: str
    tool_names: tuple[str, ...]


class AgentApprovalResponse(_Response):
    id: UUID
    tool_call_id: str
    tool_name: str
    args: dict[str, object]
    target_summary: str
    status: ApprovalStatus


class AgentOperationResponse(_Response):
    id: UUID
    tool_call_id: str
    tool_name: str
    args: dict[str, object]
    result: dict[str, object]


class AgentRunResponse(_Response):
    id: UUID
    session_id: str
    status: RunStatus
    response: str | None
    message: str
    model_ref: str
    is_override: bool
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    approvals: tuple[AgentApprovalResponse, ...]
    operations: tuple[AgentOperationResponse, ...]


class AgentApprovalResolveRequest(_Strict):
    decision: Literal["approve", "reject"]
    session_id: str = Field(min_length=1, max_length=128)


class AgentResumeRequest(_Strict):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
