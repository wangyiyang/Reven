"""仅由宿主构造的工具调用身份，不进入模型参数或图状态。"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AgentContext:
    owner_id: str
    session_id: UUID
    run_id: UUID


@dataclass(frozen=True, slots=True)
class AgentActor:
    owner_id: str
    channel: Literal["rest", "feishu"] = "rest"


ADMIN_ACTOR = AgentActor("admin", "rest")
