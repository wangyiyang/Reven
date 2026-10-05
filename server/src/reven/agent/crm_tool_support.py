"""Shared CRM MCP parameter conversion and transport error messages."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.crm.errors import ContactNotFoundError, CustomerNotFoundError, FollowUpNotFoundError, InvalidActionPairError
from reven.crm.models import CustomerStatus, FollowUpKind
from reven.crm.repository import CrmRepository
from reven.scheduling import SHANGHAI

CustomerIdParam = Annotated[UUID, Field(description="客户 ID（由 crm_customer_list / crm_customer_get 返回）")]
ContactIdParam = Annotated[UUID, Field(description="联系人 ID（由 crm_contact_list / crm_customer_get 返回）")]
FollowUpIdParam = Annotated[UUID, Field(description="跟进记录 ID（由 crm_follow_up_list / crm_customer_get 返回）")]
CustomerStatusParam = Annotated[
    CustomerStatus,
    Field(description="客户状态：潜在客户 / 跟进中 / 合作客户 / 暂停跟进 / 已流失"),
]
FollowUpKindParam = Annotated[
    FollowUpKind,
    Field(description="跟进方式：电话 / 会议（即拜访、面谈）/ 微信 / 邮件 / 其他"),
]
DueFilterParam = Annotated[
    Literal["overdue", "today", "upcoming", "none"],
    Field(description="跟进日期筛选：overdue=已逾期，today=今天到期，upcoming=未来到期，none=未安排跟进日期"),
]
ConfirmCustomerNameParam = Annotated[
    str,
    Field(description="删除确认（必填）：逐字填写要删除实体的客户名称，与客户实际名称不完全相等时拒绝执行"),
]
_FIELD_LABELS = {
    "name": "名称",
    "status": "客户状态",
    "source": "来源",
    "notes": "备注",
    "next_action": "下一步行动",
    "next_due_on": "下次跟进日期",
    "role": "职务",
    "phone": "电话",
    "email": "邮箱",
    "wechat": "微信",
    "kind": "跟进方式",
    "occurred_on": "跟进日期",
    "summary": "跟进内容",
    "contact_id": "联系人 ID",
}


def _today() -> date:
    # “今天”必须取上海时区（见 .trellis/spec crm-contract：CI UTC 16:00-24:00 窗口防日期串天）
    return datetime.now(SHANGHAI).date()


def _collect_updates(
    fields: dict[str, object],
    *,
    date_value: date | None = None,
    clear_date: bool = False,
    date_key: str = "next_due_on",
) -> dict[str, object]:
    """汇总部分更新字段：None 表示不修改；空字符串由 schema 归一为 None（即清空）；日期用 clear 开关清除。"""
    values = {key: value for key, value in fields.items() if value is not None}
    if clear_date:
        if date_value is not None:
            raise ToolError(f"{date_key} 与清除开关不能同时使用")
        values[date_key] = None
    elif date_value is not None:
        values[date_key] = date_value
    return values


def _validate[ModelT: BaseModel](model_type: type[ModelT], values: dict[str, object]) -> ModelT:
    """校验完整领域输入；失败时映射为中文 ToolError。"""
    if not values:
        raise ToolError("没有需要修改的字段：请至少传入一个要更新的字段")
    try:
        return model_type.model_validate(values)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            if message.startswith("Value error, "):
                message = message[len("Value error, ") :]
            label = _FIELD_LABELS.get(field, field)
            messages.append(f"{label}：{message}" if label else message)
        raise ToolError("参数校验未通过——" + "；".join(messages)) from exc


def _plan_text(next_action: str | None, next_due_on: date | None) -> str:
    if next_due_on is not None:
        return f"{next_due_on.isoformat()} {next_action or ''}".strip()
    return next_action or "未安排"


def _customer_not_found(customer_id: UUID) -> ToolError:
    return ToolError(f"客户不存在（id={customer_id}），请先调用 crm_customer_list 确认可用的客户 ID")


async def _confirm_customer_name(session: AsyncSession, customer_id: UUID, confirm: str) -> None:
    customer = await CrmRepository(session).get_customer(customer_id)
    if customer is None:
        raise _customer_not_found(customer_id)
    if confirm != customer.name:
        raise ToolError("删除未执行：confirm_customer_name 与客户名称不完全一致，请先用 crm_customer_get 核对后重试")


def _contact_not_found(contact_id: UUID | None) -> ToolError:
    return ToolError(f"联系人不存在或不属于该客户（id={contact_id}），请先调用 crm_contact_list 确认可用的联系人 ID")


def _follow_up_not_found(follow_up_id: UUID) -> ToolError:
    return ToolError(f"跟进记录不存在或不属于该客户（id={follow_up_id}），请先调用 crm_follow_up_list 确认")


def _action_pair_error() -> ToolError:
    return ToolError("设置下次跟进日期时必须提供下一步行动（next_action）")


@contextmanager
def _mutation_errors() -> Iterator[None]:
    try:
        yield
    except CustomerNotFoundError as exc:
        raise _customer_not_found(exc.args[0]) from exc
    except ContactNotFoundError as exc:
        raise _contact_not_found(exc.args[0]) from exc
    except FollowUpNotFoundError as exc:
        raise _follow_up_not_found(exc.args[0]) from exc
    except InvalidActionPairError as exc:
        raise _action_pair_error() from exc
