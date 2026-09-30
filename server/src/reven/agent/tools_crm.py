"""CRM 人才库 dsh 工具集：客户/联系人/跟进（拜访）增删改查 + 线索漏斗 + 今日待跟进。

设计约定：
- 业务规则（主联系人唯一、下一步行动与跟进日期配对、contact_id 归属校验、set_as_current
  同事务同步）全部复用 reven.crm.service.CrmService 与 API 层 schemas，工具层不重写业务逻辑。
- 入参校验复用 reven.api.schemas.crm 的请求模型（空串归一为 None、邮箱格式、行动/日期配对），
  校验失败映射为模型可读的中文 ToolError。
- 返回值是紧凑中文文本，由 LLM 直接转述给用户；文本中附带实体 id，供后续修改/删除工具引用。
- CRM 数据（联系人方式、跟进内容）属于敏感经营信息，按 CRM 契约不写入应用日志，本模块不记日志。
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.api.schemas.crm import (
    ContactCreate,
    ContactUpdate,
    CustomerCreate,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpUpdate,
)
from reven.crm.models import Contact, Customer, CustomerStatus, FollowUp, FollowUpKind
from reven.crm.repository import CrmRepository
from reven.crm.service import ContactNotFoundError, CrmService, InvalidActionPairError
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

# 参数中文标签：把 pydantic 校验错误的字段路径翻译成用户可读的字段名
_FIELD_LABELS = {
    "name": "名称",
    "status": "客户状态",
    "source": "来源",
    "notes": "备注",
    "next_action": "下一步行动",
    "next_follow_up_on": "下次跟进日期",
    "role": "职务",
    "phone": "电话",
    "email": "邮箱",
    "wechat": "微信",
    "kind": "跟进方式",
    "occurred_on": "跟进日期",
    "summary": "跟进内容",
    "contact_id": "联系人 ID",
    "set_as_current": "set_as_current",
}


def register_crm_tools(mcp: FastMCP, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """把 CRM 人才库能力注册为 MCP 工具（模型侧呈现为 mcp__reven__crm_*）。"""
    tools = CrmTools(session_factory)
    mcp.tool(tools.list_customers, name="crm_customer_list")
    mcp.tool(tools.get_customer, name="crm_customer_get")
    mcp.tool(tools.create_customer, name="crm_customer_create")
    mcp.tool(tools.update_customer, name="crm_customer_update")
    mcp.tool(tools.delete_customer, name="crm_customer_delete")
    mcp.tool(tools.list_contacts, name="crm_contact_list")
    mcp.tool(tools.create_contact, name="crm_contact_create")
    mcp.tool(tools.update_contact, name="crm_contact_update")
    mcp.tool(tools.delete_contact, name="crm_contact_delete")
    mcp.tool(tools.list_follow_ups, name="crm_follow_up_list")
    mcp.tool(tools.create_follow_up, name="crm_follow_up_create")
    mcp.tool(tools.update_follow_up, name="crm_follow_up_update")
    mcp.tool(tools.delete_follow_up, name="crm_follow_up_delete")
    mcp.tool(tools.lead_funnel_stats, name="crm_lead_funnel")
    mcp.tool(tools.list_due_follow_ups, name="crm_due_follow_ups")


class CrmTools:
    """CRM 工具实现；每次调用独立开库会话，写路径经 CrmService 提交，与 API 路由语义一致。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ 客户

    async def list_customers(
        self,
        query: Annotated[
            str | None,
            Field(description="模糊检索词：匹配客户名称/来源/备注，以及联系人的姓名/电话/邮箱/微信"),
        ] = None,
        status: CustomerStatusParam | None = None,
        due: DueFilterParam | None = None,
    ) -> str:
        """检索客户列表，可按名称等关键词模糊搜索、按客户状态筛选、按跟进日期筛选。

        返回每个客户的 id、名称、状态、来源与下次跟进计划；拿到 id 后可调用
        crm_customer_get 看详情，或 crm_customer_update / crm_customer_delete 做变更。
        """
        today = _today()
        async with self._session_factory() as session:
            customers = await CrmRepository(session).list_customers(
                status=status,
                due=due,
                query=query,
                today=today,
            )
        if not customers:
            return "没有找到符合条件的客户。可调整筛选条件，或用 crm_customer_create 新建客户。"
        header = f"共 {len(customers)} 个客户："
        lines = [f"{index}. {_customer_line(customer)}" for index, customer in enumerate(customers, 1)]
        return "\n".join([header, *lines])

    async def get_customer(self, customer_id: CustomerIdParam) -> str:
        """查看客户详情：基本信息 + 全部联系人 + 全部跟进（拜访）记录。"""
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            customer = await repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            contacts = await repository.list_contacts(customer_id)
            follow_ups = await repository.list_follow_ups(customer_id)
        lines = [_customer_detail(customer)]
        if contacts:
            lines.append(f"联系人（{len(contacts)}）：")
            lines.extend(_contact_line(index, contact) for index, contact in enumerate(contacts, 1))
        else:
            lines.append("暂无联系人。")
        if follow_ups:
            lines.append(f"跟进记录（{len(follow_ups)}）：")
            lines.extend(_follow_up_line(index, follow_up) for index, follow_up in enumerate(follow_ups, 1))
        else:
            lines.append("暂无跟进记录。")
        return "\n".join(lines)

    async def create_customer(
        self,
        name: Annotated[str, Field(description="客户名称（必填，如公司名或人才姓名）")],
        status: CustomerStatusParam = CustomerStatus.PROSPECT,
        source: Annotated[str | None, Field(description="客户来源，如：朋友介绍、主动咨询、展会")] = None,
        notes: Annotated[str | None, Field(description="备注")] = None,
        next_action: Annotated[str | None, Field(description="下一步行动；设置下次跟进日期时必填")] = None,
        next_follow_up_on: Annotated[date | None, Field(description="下次跟进日期，格式 YYYY-MM-DD")] = None,
    ) -> str:
        """新建一个客户。状态默认为「潜在客户」，可指定为漏斗中的其他状态。"""
        payload = _validate(
            CustomerCreate,
            {
                "name": name,
                "status": status,
                "source": source,
                "notes": notes,
                "next_action": next_action,
                "next_follow_up_on": next_follow_up_on,
            },
        )
        async with self._session_factory() as session:
            customer = await CrmService(session).create_customer(payload.model_dump())
        return f"已创建客户：{_customer_line(customer)}"

    async def update_customer(
        self,
        customer_id: CustomerIdParam,
        name: Annotated[str | None, Field(description="新名称；不传则不修改")] = None,
        status: CustomerStatusParam | None = None,
        source: Annotated[str | None, Field(description="新来源；传空字符串表示清空")] = None,
        notes: Annotated[str | None, Field(description="新备注；传空字符串表示清空")] = None,
        next_action: Annotated[str | None, Field(description="新下一步行动；传空字符串表示清空")] = None,
        next_follow_up_on: Annotated[date | None, Field(description="新下次跟进日期，格式 YYYY-MM-DD")] = None,
        clear_next_follow_up_on: Annotated[bool, Field(description="为 true 时清除下次跟进日期")] = False,
    ) -> str:
        """修改客户信息（部分更新，只传要改的字段）。修改状态即完成线索流转（如 潜在客户 → 跟进中 → 合作客户）。

        设置下次跟进日期时必须同时保证客户有下一步行动（可在本次一并传入）。
        """
        values = _collect_updates(
            {"name": name, "status": status, "source": source, "notes": notes, "next_action": next_action},
            date_value=next_follow_up_on,
            clear_date=clear_next_follow_up_on,
            date_key="next_follow_up_on",
        )
        payload = _validate(CustomerUpdate, values)
        async with self._session_factory() as session:
            service = CrmService(session)
            customer = await service.repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            try:
                updated = await service.update_customer(customer, payload.model_dump(exclude_unset=True))
            except InvalidActionPairError as exc:
                raise _action_pair_error() from exc
        return f"已更新客户：{_customer_line(updated)}"

    async def delete_customer(self, customer_id: CustomerIdParam) -> str:
        """删除一个客户，其名下联系人、跟进（拜访）记录会一并删除，不可恢复。

        调用前必须在对话中与用户确认删除意图，得到明确同意后再执行。
        """
        async with self._session_factory() as session:
            service = CrmService(session)
            customer = await service.repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            name = customer.name
            await service.delete_customer(customer)
        return f"已删除客户「{name}」（id={customer_id}），其名下联系人与跟进记录已一并删除。"

    # ------------------------------------------------------------------ 联系人

    async def list_contacts(self, customer_id: CustomerIdParam) -> str:
        """列出指定客户的全部联系人（主联系人排在最前）。"""
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            customer = await repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            contacts = await repository.list_contacts(customer_id)
        if not contacts:
            return f"客户「{customer.name}」暂无联系人，可用 crm_contact_create 添加。"
        header = f"客户「{customer.name}」的联系人（{len(contacts)}）："
        lines = [_contact_line(index, contact) for index, contact in enumerate(contacts, 1)]
        return "\n".join([header, *lines])

    async def create_contact(
        self,
        customer_id: CustomerIdParam,
        name: Annotated[str, Field(description="联系人姓名（必填）")],
        role: Annotated[str | None, Field(description="职务，如：创始人、HR 总监")] = None,
        phone: Annotated[str | None, Field(description="电话")] = None,
        email: Annotated[str | None, Field(description="邮箱")] = None,
        wechat: Annotated[str | None, Field(description="微信号")] = None,
        is_primary: Annotated[bool, Field(description="是否设为主联系人（每个客户最多一个）")] = False,
        notes: Annotated[str | None, Field(description="备注")] = None,
    ) -> str:
        """为客户新增联系人。设为主联系人时，原主联系人会自动降级为普通联系人。"""
        payload = _validate(
            ContactCreate,
            {
                "name": name,
                "role": role,
                "phone": phone,
                "email": email,
                "wechat": wechat,
                "is_primary": is_primary,
                "notes": notes,
            },
        )
        async with self._session_factory() as session:
            service = CrmService(session)
            customer = await service.repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            contact = await service.create_contact(customer_id, payload.model_dump())
        suffix = "，已设为该客户唯一主联系人" if contact.is_primary else ""
        return f"已为客户「{customer.name}」新增联系人「{contact.name}」（id={contact.id}）{suffix}。"

    async def update_contact(
        self,
        customer_id: CustomerIdParam,
        contact_id: ContactIdParam,
        name: Annotated[str | None, Field(description="新姓名；不传则不修改")] = None,
        role: Annotated[str | None, Field(description="新职务；传空字符串表示清空")] = None,
        phone: Annotated[str | None, Field(description="新电话；传空字符串表示清空")] = None,
        email: Annotated[str | None, Field(description="新邮箱；传空字符串表示清空")] = None,
        wechat: Annotated[str | None, Field(description="新微信号；传空字符串表示清空")] = None,
        is_primary: Annotated[bool | None, Field(description="true=设为主联系人，false=取消主联系人")] = None,
        notes: Annotated[str | None, Field(description="新备注；传空字符串表示清空")] = None,
    ) -> str:
        """修改联系人信息（部分更新，只传要改的字段）。设为主联系人时自动顶替原主联系人。"""
        values = _collect_updates(
            {
                "name": name,
                "role": role,
                "phone": phone,
                "email": email,
                "wechat": wechat,
                "is_primary": is_primary,
                "notes": notes,
            }
        )
        payload = _validate(ContactUpdate, values)
        async with self._session_factory() as session:
            service = CrmService(session)
            contact = await service.repository.get_contact(customer_id, contact_id)
            if contact is None:
                raise _contact_not_found(contact_id)
            updated = await service.update_contact(contact, payload.model_dump(exclude_unset=True))
        return f"已更新联系人：{_contact_line(0, updated).removeprefix('0. ')}"

    async def delete_contact(self, customer_id: CustomerIdParam, contact_id: ContactIdParam) -> str:
        """删除一个联系人；相关跟进记录会保留，其中的联系人信息以姓名快照形式留存。

        调用前必须在对话中与用户确认删除意图，得到明确同意后再执行。
        """
        async with self._session_factory() as session:
            service = CrmService(session)
            contact = await service.repository.get_contact(customer_id, contact_id)
            if contact is None:
                raise _contact_not_found(contact_id)
            name = contact.name
            await service.delete_contact(contact)
        return f"已删除联系人「{name}」（id={contact_id}）；相关跟进记录已保留，联系人信息以快照留存。"

    # ------------------------------------------------------------------ 跟进（拜访）记录

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
        next_follow_up_on: Annotated[date | None, Field(description="下次跟进日期，格式 YYYY-MM-DD")] = None,
        set_as_current: Annotated[
            bool,
            Field(description="为 true 时把下一步行动/下次跟进日期同步为客户的当前跟进计划"),
        ] = False,
    ) -> str:
        """为客户记录一次跟进（拜访）记录：方式（会议=拜访/面谈）、日期、内容纪要，可选下一步计划。"""
        payload = _validate(
            FollowUpCreate,
            {
                "contact_id": contact_id,
                "kind": kind,
                "occurred_on": occurred_on,
                "summary": summary,
                "next_action": next_action,
                "next_follow_up_on": next_follow_up_on,
                "set_as_current": set_as_current,
            },
        )
        async with self._session_factory() as session:
            service = CrmService(session)
            customer = await service.repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            try:
                follow_up = await service.create_follow_up(customer, payload.model_dump())
            except ContactNotFoundError as exc:
                raise _contact_not_found(contact_id) from exc
        occurred = follow_up.occurred_on.isoformat()
        text = f"已为客户「{customer.name}」记录 {occurred} 的{follow_up.kind}跟进（id={follow_up.id}）。"
        if set_as_current:
            text += f"已同步为当前跟进计划：{_plan_text(follow_up.next_action, follow_up.next_follow_up_on)}。"
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
        next_follow_up_on: Annotated[date | None, Field(description="新下次跟进日期，格式 YYYY-MM-DD")] = None,
        clear_next_follow_up_on: Annotated[bool, Field(description="为 true 时清除下次跟进日期")] = False,
    ) -> str:
        """修改一条跟进（拜访）记录（部分更新，只传要改的字段）。不会改动客户的当前跟进计划。"""
        values = _collect_updates(
            {"kind": kind, "occurred_on": occurred_on, "summary": summary, "next_action": next_action},
            date_value=next_follow_up_on,
            clear_date=clear_next_follow_up_on,
            date_key="next_follow_up_on",
        )
        if clear_contact:
            if contact_id is not None:
                raise ToolError("contact_id 与 clear_contact 不能同时使用")
            values["contact_id"] = None
        elif contact_id is not None:
            values["contact_id"] = contact_id
        payload = _validate(FollowUpUpdate, values)
        async with self._session_factory() as session:
            service = CrmService(session)
            follow_up = await service.repository.get_follow_up(customer_id, follow_up_id)
            if follow_up is None:
                raise _follow_up_not_found(follow_up_id)
            try:
                updated = await service.update_follow_up(follow_up, payload.model_dump(exclude_unset=True))
            except ContactNotFoundError as exc:
                raise _contact_not_found(contact_id) from exc
            except InvalidActionPairError as exc:
                raise _action_pair_error() from exc
        return f"已更新跟进记录：{_follow_up_line(0, updated).removeprefix('0. ')}"

    async def delete_follow_up(self, customer_id: CustomerIdParam, follow_up_id: FollowUpIdParam) -> str:
        """删除一条跟进（拜访）记录，不可恢复；不影响客户的当前跟进计划。

        调用前必须在对话中与用户确认删除意图，得到明确同意后再执行。
        """
        async with self._session_factory() as session:
            service = CrmService(session)
            follow_up = await service.repository.get_follow_up(customer_id, follow_up_id)
            if follow_up is None:
                raise _follow_up_not_found(follow_up_id)
            label = f"{follow_up.occurred_on.isoformat()} 的{follow_up.kind}跟进"
            await service.delete_follow_up(follow_up)
        return f"已删除{label}（id={follow_up_id}）。"

    # ------------------------------------------------------------------ 线索跟踪

    async def lead_funnel_stats(self) -> str:
        """线索漏斗统计：按客户状态（潜在客户/跟进中/合作客户/暂停跟进/已流失）统计各阶段客户数量。"""
        async with self._session_factory() as session:
            customers = await CrmRepository(session).list_customers(
                status=None,
                due=None,
                query=None,
                today=_today(),
            )
        if not customers:
            return "线索库暂无客户，可用 crm_customer_create 新建第一个客户。"
        counts = {status.value: 0 for status in CustomerStatus}
        for customer in customers:
            counts[customer.status] = counts.get(customer.status, 0) + 1
        stages = "｜".join(f"{status.value} {counts[status.value]}" for status in CustomerStatus)
        return f"线索漏斗（共 {len(customers)} 个客户）：{stages}"

    async def list_due_follow_ups(self) -> str:
        """今日待跟进清单：下次跟进日期已到期（今天）或已逾期的客户，含下一步行动，按日期升序。"""
        today = _today()
        async with self._session_factory() as session:
            repository = CrmRepository(session)
            overdue = await repository.list_customers(status=None, due="overdue", query=None, today=today)
            due_today = await repository.list_customers(status=None, due="today", query=None, today=today)
        customers = sorted(
            [*overdue, *due_today],
            key=lambda customer: (customer.next_follow_up_on or today, customer.name.lower()),
        )
        if not customers:
            return f"今天（{today.isoformat()}）没有到期或逾期的待跟进客户。"
        lines = [f"今日待跟进（{today.isoformat()}，共 {len(customers)} 个客户）："]
        for index, customer in enumerate(customers, 1):
            due_on = customer.next_follow_up_on
            if due_on is not None and due_on < today:
                marker = f"已逾期 {(today - due_on).days} 天（原定 {due_on.isoformat()}）"
            else:
                marker = "今天到期"
            action = customer.next_action or "未填写下一步行动"
            lines.append(
                f"{index}. {customer.name}（id={customer.id}）｜状态：{customer.status}｜{marker}｜下一步：{action}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------- 辅助函数


def _today() -> date:
    # “今天”必须取上海时区（见 .trellis/spec crm-contract：CI UTC 16:00-24:00 窗口防日期串天）
    return datetime.now(SHANGHAI).date()


def _collect_updates(
    fields: dict[str, object],
    *,
    date_value: date | None = None,
    clear_date: bool = False,
    date_key: str = "next_follow_up_on",
) -> dict[str, object]:
    """汇总部分更新字段：None 表示不修改；空字符串由 schema 归一为 None（即清空）；日期用 clear 开关清除。"""
    values = {key: value for key, value in fields.items() if value is not None}
    if clear_date:
        if date_value is not None:
            raise ToolError(f"{date_key} 与清除开关不能同时使用")
        values[date_key] = None
    elif date_value is not None:
        values[date_key] = date_value
    if not values:
        raise ToolError("没有需要修改的字段：请至少传入一个要更新的字段")
    return values


def _validate[ModelT: BaseModel](model_type: type[ModelT], values: dict[str, object]) -> ModelT:
    """复用 API 层 schema 校验；失败时映射为中文 ToolError（字段路径翻译成中文标签）。"""
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


def _plan_text(next_action: str | None, next_follow_up_on: date | None) -> str:
    if next_follow_up_on is not None:
        return f"{next_follow_up_on.isoformat()} {next_action or ''}".strip()
    return next_action or "未安排"


def _customer_line(customer: Customer) -> str:
    parts = [f"「{customer.name}」（id={customer.id}，状态：{customer.status}）"]
    if customer.source:
        parts.append(f"来源：{customer.source}")
    if customer.next_action or customer.next_follow_up_on:
        parts.append(f"下次跟进：{_plan_text(customer.next_action, customer.next_follow_up_on)}")
    return "｜".join(parts)


def _customer_detail(customer: Customer) -> str:
    created_on = customer.created_at.astimezone(SHANGHAI).date().isoformat()
    parts = [
        f"客户「{customer.name}」（id={customer.id}）",
        f"状态：{customer.status}｜来源：{customer.source or '未填写'}｜创建于：{created_on}",
        f"当前跟进计划：{_plan_text(customer.next_action, customer.next_follow_up_on)}",
    ]
    if customer.notes:
        parts.append(f"备注：{customer.notes}")
    return "\n".join(parts)


def _contact_line(index: int, contact: Contact) -> str:
    primary = "，主联系人" if contact.is_primary else ""
    parts = [f"{index}. {contact.name}（id={contact.id}{primary}）"]
    if contact.role:
        parts.append(contact.role)
    if contact.phone:
        parts.append(f"电话：{contact.phone}")
    if contact.email:
        parts.append(f"邮箱：{contact.email}")
    if contact.wechat:
        parts.append(f"微信：{contact.wechat}")
    if contact.notes:
        parts.append(f"备注：{contact.notes}")
    return "｜".join(parts)


def _follow_up_line(index: int, follow_up: FollowUp) -> str:
    parts = [f"{index}. {follow_up.occurred_on.isoformat()} {follow_up.kind}（id={follow_up.id}）：{follow_up.summary}"]
    if follow_up.contact_name_snapshot:
        parts.append(f"联系人：{follow_up.contact_name_snapshot}")
    if follow_up.next_action or follow_up.next_follow_up_on:
        parts.append(f"下一步：{_plan_text(follow_up.next_action, follow_up.next_follow_up_on)}")
    return "｜".join(parts)


def _customer_not_found(customer_id: UUID) -> ToolError:
    return ToolError(f"客户不存在（id={customer_id}），请先调用 crm_customer_list 确认可用的客户 ID")


def _contact_not_found(contact_id: UUID | None) -> ToolError:
    return ToolError(f"联系人不存在或不属于该客户（id={contact_id}），请先调用 crm_contact_list 确认可用的联系人 ID")


def _follow_up_not_found(follow_up_id: UUID) -> ToolError:
    return ToolError(f"跟进记录不存在或不属于该客户（id={follow_up_id}），请先调用 crm_follow_up_list 确认")


def _action_pair_error() -> ToolError:
    return ToolError("设置下次跟进日期时必须提供下一步行动（next_action）")
