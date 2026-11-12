"""CRM follow_ups MCP adapter: input conversion and Chinese output."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.crm_tool_support import (
    ConfirmCustomerNameParam,
    CustomerIdParam,
    FollowUpIdParam,
    FollowUpKindParam,
    _collect_updates,
    _confirm_customer_name,
    _customer_not_found,
    _mutation_errors,
    _plan_text,
    _validate,
)
from reven.crm.inputs import FollowUpCreate, FollowUpUpdate
from reven.crm.models import FollowUp
from reven.crm.repository import CrmRepository, CustomerPlan
from reven.crm.service import CrmService


class CrmFollowUpTools:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_follow_ups(self, customer_id: CustomerIdParam) -> str:
        """列出指定客户的全部跟进（拜访）记录，按跟进日期倒序。"""
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            customer = await repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            follow_ups = await repository.list_follow_ups(customer_id)
        if not follow_ups:
            return f"客户「{customer.name}」暂无跟进记录，可用 crm_follow_up_create 记录一次拜访或沟通。"
        header = f"客户「{customer.name}」的跟进记录（{len(follow_ups)}）："
        lines = [_follow_up_line(index, follow_up) for index, follow_up in enumerate(follow_ups, 1)]
        return "\n".join([header, *lines])

    async def create_follow_up(
        self,
        customer_id: CustomerIdParam,
        kind: FollowUpKindParam,
        occurred_on: Annotated[date, Field(description="跟进发生日期，格式 YYYY-MM-DD")],
        summary: Annotated[str, Field(description="跟进内容纪要（必填），如拜访沟通要点")],
        contact_id: Annotated[
            UUID | None,
            Field(description="参与跟进的联系人 ID（由 crm_contact_list 返回）；不确定则不传"),
        ] = None,
        next_action: Annotated[str | None, Field(description="下一步行动；设置下次跟进日期时必填")] = None,
        next_due_on: Annotated[date | None, Field(description="下次跟进日期，格式 YYYY-MM-DD")] = None,
    ) -> str:
        """为客户记录一次跟进（拜访）记录：方式（面谈=拜访/当面沟通）、日期、内容纪要，可选下一步计划。

        最新一条跟进上的 next_action / next_due_on 即该客户的当前计划：记录后自动生效，无需额外同步。
        """
        payload = _validate(
            FollowUpCreate,
            {
                "contact_id": contact_id,
                "kind": kind,
                "occurred_on": occurred_on,
                "summary": summary,
                "next_action": next_action,
                "next_due_on": next_due_on,
            },
        )
        with _mutation_errors():
            async with self._session_factory() as session:
                customer, follow_up = await CrmService(session).create_follow_up(customer_id, payload)
                plan = await CrmRepository(session).get_customer_plan(customer_id)
        occurred = follow_up.occurred_on.isoformat()
        text = f"已为客户「{customer.name}」记录 {occurred} 的{follow_up.kind}跟进（id={follow_up.id}）。"
        if follow_up.next_action or follow_up.next_due_on:
            text += _plan_effect_text(plan, follow_up)
        return text

    async def update_follow_up(
        self,
        customer_id: CustomerIdParam,
        follow_up_id: FollowUpIdParam,
        kind: FollowUpKindParam | None = None,
        occurred_on: Annotated[date | None, Field(description="新跟进日期，格式 YYYY-MM-DD")] = None,
        summary: Annotated[str | None, Field(description="新跟进内容纪要；不传则不修改")] = None,
        contact_id: Annotated[UUID | None, Field(description="改关联的联系人 ID")] = None,
        clear_contact: Annotated[bool, Field(description="为 true 时解除该记录与联系人的关联")] = False,
        next_action: Annotated[str | None, Field(description="新下一步行动；传空字符串表示清空")] = None,
        next_due_on: Annotated[date | None, Field(description="新下次跟进日期，格式 YYYY-MM-DD")] = None,
        clear_next_due_on: Annotated[bool, Field(description="为 true 时清除下次跟进日期")] = False,
    ) -> str:
        """修改一条跟进（拜访）记录（部分更新，只传要改的字段）。

        若该记录是客户最新一条跟进，修改其下一步行动/日期即更新客户的当前计划。
        """
        values = _collect_updates(
            {"kind": kind, "occurred_on": occurred_on, "summary": summary, "next_action": next_action},
            date_value=next_due_on,
            clear_date=clear_next_due_on,
            date_key="next_due_on",
        )
        if clear_contact:
            if contact_id is not None:
                raise ToolError("contact_id 与 clear_contact 不能同时使用")
            values["contact_id"] = None
        elif contact_id is not None:
            values["contact_id"] = contact_id
        payload = _validate(FollowUpUpdate, values)
        with _mutation_errors():
            async with self._session_factory() as session:
                updated = await CrmService(session).update_follow_up(customer_id, follow_up_id, payload)
        return f"已更新跟进记录：{_follow_up_line(0, updated).removeprefix('0. ')}"

    async def delete_follow_up(
        self,
        customer_id: CustomerIdParam,
        follow_up_id: FollowUpIdParam,
        confirm_customer_name: ConfirmCustomerNameParam,
    ) -> str:
        """删除一条跟进（拜访）记录，不可恢复；若删除的是最新一条，客户当前计划回退到次新跟进或为空。

        调用前必须与用户确认删除意图，并把所属客户名称逐字填入 confirm_customer_name。
        """
        with _mutation_errors():
            async with self._session_factory() as session:
                await _confirm_customer_name(session, customer_id, confirm_customer_name)
                follow_up = await CrmService(session).delete_follow_up(customer_id, follow_up_id)
                label = f"{follow_up.occurred_on.isoformat()} 的{follow_up.kind}跟进"
        return f"已删除{label}（id={follow_up_id}）。"


def _plan_effect_text(plan: CustomerPlan | None, follow_up: FollowUp) -> str:
    """创建跟进后的计划生效文案：派生计划取自最新一条跟进，只有新记录真正给出派生值时才能声称已生效。"""
    if plan is not None and plan.next_action == follow_up.next_action and plan.next_due_on == follow_up.next_due_on:
        return f"下一步计划已自动生效为客户当前计划：{_plan_text(follow_up.next_action, follow_up.next_due_on)}。"
    current = _plan_text(plan.next_action, plan.next_due_on) if plan is not None else "未安排"
    return f"该记录早于最新跟进，客户当前计划不变：{current}。"


def _follow_up_line(index: int, follow_up: FollowUp) -> str:
    parts = [f"{index}. {follow_up.occurred_on.isoformat()} {follow_up.kind}（id={follow_up.id}）：{follow_up.summary}"]
    if follow_up.contact_name_snapshot:
        parts.append(f"联系人：{follow_up.contact_name_snapshot}")
    if follow_up.next_action or follow_up.next_due_on:
        parts.append(f"下一步：{_plan_text(follow_up.next_action, follow_up.next_due_on)}")
    return "｜".join(parts)
