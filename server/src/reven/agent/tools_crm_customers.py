"""CRM customers MCP adapter: input conversion and Chinese output."""

from typing import Annotated

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.crm_tool_support import (
    ConfirmCustomerNameParam,
    CustomerIdParam,
    CustomerStatusParam,
    DueFilterParam,
    _collect_updates,
    _confirm_customer_name,
    _customer_not_found,
    _mutation_errors,
    _plan_text,
    _today,
    _validate,
)
from reven.agent.tools_crm_contacts import _contact_line
from reven.agent.tools_crm_follow_ups import _follow_up_line
from reven.crm.inputs import CustomerCreate, CustomerUpdate
from reven.crm.models import CustomerStatus
from reven.crm.repository import CrmRepository, CustomerPlan
from reven.crm.service import CrmService
from reven.scheduling import SHANGHAI


class CrmCustomerTools:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_customers(
        self,
        query: Annotated[
            str | None,
            Field(description="模糊检索词：匹配客户名称/来源/备注，以及联系人的姓名/职务/电话/邮箱/微信/备注"),
        ] = None,
        status: CustomerStatusParam | None = None,
        due: DueFilterParam | None = None,
    ) -> str:
        """检索客户列表，可按名称等关键词模糊搜索、按客户状态筛选、按跟进日期筛选。

        返回每个客户的 id、名称、状态、来源与下次跟进计划（派生自最新一条跟进记录）；
        拿到 id 后可调用 crm_customer_get 看详情，或 crm_customer_update / crm_customer_delete 做变更。
        """
        today = _today()
        async with self._session_factory() as session:
            plans = await CrmRepository(session).list_customers(
                status=status,
                due=due,
                query=query,
                today=today,
            )
        if not plans:
            return "没有找到符合条件的客户。可调整筛选条件，或用 crm_customer_create 新建客户。"
        header = f"共 {len(plans)} 个客户："
        lines = [f"{index}. {_customer_line(plan)}" for index, plan in enumerate(plans, 1)]
        return "\n".join([header, *lines])

    async def get_customer(self, customer_id: CustomerIdParam) -> str:
        """查看客户详情：基本信息 + 当前跟进计划（派生自最新跟进记录）+ 全部联系人 + 全部跟进（拜访）记录。"""
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            plan = await repository.get_customer_plan(customer_id)
            if plan is None:
                raise _customer_not_found(customer_id)
            contacts = await repository.list_contacts(customer_id)
            follow_ups = await repository.list_follow_ups(customer_id)
        lines = [_customer_detail(plan)]
        if contacts:
            lines.append(f"联系人（{len(contacts)}）：")
            lines.extend(_contact_line(index, contact) for index, contact in enumerate(contacts, 1))
        else:
            lines.append("暂无联系人。")
        if follow_ups:
            lines.append(f"跟进记录（{len(follow_ups)}）：")
            lines.extend(_follow_up_line(index, follow_up) for index, follow_up in enumerate(follow_ups, 1))
        else:
            lines.append("暂无跟进记录。可用 crm_follow_up_create 记录第一次跟进并定下当前计划。")
        return "\n".join(lines)

    async def create_customer(
        self,
        name: Annotated[str, Field(description="客户名称（必填，如公司名或人才姓名）")],
        status: CustomerStatusParam = CustomerStatus.PROSPECT,
        source: Annotated[str | None, Field(description="客户来源，如：朋友介绍、主动咨询、展会")] = None,
        notes: Annotated[str | None, Field(description="备注")] = None,
    ) -> str:
        """新建一个客户。状态默认为「潜在客户」，可指定为漏斗中的其他状态。

        客户本身不保存跟进计划：创建后可用 crm_follow_up_create 记录第一次跟进，
        并在跟进上写下下一步行动（next_action）与下次跟进日期（next_due_on），即成为该客户的当前计划。
        """
        payload = _validate(
            CustomerCreate,
            {
                "name": name,
                "status": status,
                "source": source,
                "notes": notes,
            },
        )
        with _mutation_errors():
            async with self._session_factory() as session:
                customer = await CrmService(session).create_customer(payload)
        plan = CustomerPlan(customer=customer, next_action=None, next_due_on=None)
        return f"已创建客户：{_customer_line(plan)}。可用 crm_follow_up_create 记录第一次跟进并定下当前计划。"

    async def update_customer(
        self,
        customer_id: CustomerIdParam,
        name: Annotated[str | None, Field(description="新名称；不传则不修改")] = None,
        status: CustomerStatusParam | None = None,
        source: Annotated[str | None, Field(description="新来源；传空字符串表示清空")] = None,
        notes: Annotated[str | None, Field(description="新备注；传空字符串表示清空")] = None,
    ) -> str:
        """修改客户信息（部分更新，只传要改的字段）。修改状态即完成线索流转（如 潜在客户 → 跟进中 → 合作客户）。

        客户的当前跟进计划不可在此直接修改：用 crm_follow_up_create 记录新跟进并写下
        next_action / next_due_on，或用 crm_follow_up_update 修改最新一条跟进记录。
        """
        values = _collect_updates({"name": name, "status": status, "source": source, "notes": notes})
        payload = _validate(CustomerUpdate, values)
        with _mutation_errors():
            async with self._session_factory() as session:
                updated = await CrmService(session).update_customer(customer_id, payload)
                plan = await CrmRepository(session).get_customer_plan(updated.id)
        if plan is None:  # pragma: no cover - 刚更新的客户必然存在
            raise _customer_not_found(customer_id)
        return f"已更新客户：{_customer_line(plan)}"

    async def delete_customer(
        self, customer_id: CustomerIdParam, confirm_customer_name: ConfirmCustomerNameParam
    ) -> str:
        """删除一个客户，其名下联系人、跟进（拜访）记录会一并删除，不可恢复。

        调用前必须与用户确认删除意图，并把客户名称逐字填入 confirm_customer_name。
        """
        with _mutation_errors():
            async with self._session_factory() as session:
                await _confirm_customer_name(session, customer_id, confirm_customer_name)
                customer = await CrmService(session).delete_customer(customer_id)
                name = customer.name
        return f"已删除客户「{name}」（id={customer_id}），其名下联系人与跟进记录已一并删除。"

    async def lead_funnel_stats(self) -> str:
        """线索漏斗统计：按客户状态（潜在客户/跟进中/合作客户/暂停跟进/已流失）统计各阶段客户数量。"""
        async with self._session_factory() as session:
            plans = await CrmRepository(session).list_customers(
                status=None,
                due=None,
                query=None,
                today=_today(),
            )
        if not plans:
            return "线索库暂无客户，可用 crm_customer_create 新建第一个客户。"
        counts = {status.value: 0 for status in CustomerStatus}
        for plan in plans:
            counts[plan.customer.status] = counts.get(plan.customer.status, 0) + 1
        stages = "｜".join(f"{status.value} {counts[status.value]}" for status in CustomerStatus)
        return f"线索漏斗（共 {len(plans)} 个客户）：{stages}"

    async def list_due_follow_ups(self) -> str:
        """今日待跟进清单：下次跟进日期已到期（今天）或已逾期的客户，含下一步行动，按日期升序。"""
        today = _today()
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            overdue = await repository.list_customers(status=None, due="overdue", query=None, today=today)
            due_today = await repository.list_customers(status=None, due="today", query=None, today=today)
        plans = sorted(
            [*overdue, *due_today],
            key=lambda plan: (plan.next_due_on or today, plan.customer.name.lower()),
        )
        if not plans:
            return f"今天（{today.isoformat()}）没有到期或逾期的待跟进客户。"
        lines = [f"今日待跟进（{today.isoformat()}，共 {len(plans)} 个客户）："]
        for index, plan in enumerate(plans, 1):
            due_on = plan.next_due_on
            if due_on is not None and due_on < today:
                marker = f"已逾期 {(today - due_on).days} 天（原定 {due_on.isoformat()}）"
            else:
                marker = "今天到期"
            action = plan.next_action or "未填写下一步行动"
            lines.append(
                f"{index}. {plan.customer.name}（id={plan.customer.id}）"
                f"｜状态：{plan.customer.status}｜{marker}｜下一步：{action}"
            )
        return "\n".join(lines)


def _customer_line(plan: CustomerPlan) -> str:
    customer = plan.customer
    parts = [f"「{customer.name}」（id={customer.id}，状态：{customer.status}）"]
    if customer.source:
        parts.append(f"来源：{customer.source}")
    if plan.next_action or plan.next_due_on:
        parts.append(f"下次跟进：{_plan_text(plan.next_action, plan.next_due_on)}")
    return "｜".join(parts)


def _customer_detail(plan: CustomerPlan) -> str:
    customer = plan.customer
    created_on = customer.created_at.astimezone(SHANGHAI).date().isoformat()
    parts = [
        f"客户「{customer.name}」（id={customer.id}）",
        f"状态：{customer.status}｜来源：{customer.source or '未填写'}｜创建于：{created_on}",
        f"当前跟进计划：{_plan_text(plan.next_action, plan.next_due_on)}",
    ]
    if customer.notes:
        parts.append(f"备注：{customer.notes}")
    return "\n".join(parts)
