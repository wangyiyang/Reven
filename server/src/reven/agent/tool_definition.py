"""One validated input contract for native and MCP business tools."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from reven.agent.tool_binding import ToolSessionBinding

AsyncToolFunction = Callable[..., Awaitable[object]]
BindingFactory = Callable[[AsyncSession | None], tuple[ToolSessionBinding, AsyncToolFunction]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    owner: type[ToolSessionBinding]
    method: str
    is_write: bool = False
    requires_confirmation: bool = False
    refresh_embedding: bool = False


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    spec: ToolSpec
    source: AsyncToolFunction
    args_schema: type[BaseModel]
    description: str
    bind: BindingFactory

    @property
    def name(self) -> str:
        return self.spec.name

    def canonical_arguments(self, arguments: dict[str, object]) -> dict[str, object]:
        return self.args_schema.model_validate(arguments).model_dump(mode="json")

    async def invoke(
        self, arguments: dict[str, object], *, session: AsyncSession | None = None
    ) -> tuple[object, dict[str, object]]:
        payload = self.args_schema.model_validate(arguments)
        values: dict[str, Any] = {name: getattr(payload, name) for name in type(payload).model_fields}
        binding, function = self.bind(session)
        return await function(**values), binding.receipt
