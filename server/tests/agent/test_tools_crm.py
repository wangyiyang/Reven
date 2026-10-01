"""CRM 人才库 MCP 工具测试（#169）：CRUD 行为、筛选、漏斗/待跟进统计、错误映射与 MCP 协议面。"""

import os
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import TextContent
from reven.agent.mcp_server import create_agent_mcp_server
from reven.agent.tools_crm_contacts import CrmContactTools
from reven.agent.tools_crm_customers import CrmCustomerTools
from reven.agent.tools_crm_follow_ups import CrmFollowUpTools
from reven.scheduling import SHANGHAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _today() -> date:
    # 与工具实现同一时钟（上海时区），避免 CI UTC 16:00-24:00 窗口内两侧日期串天
    return datetime.now(SHANGHAI).date()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE crm_follow_ups, crm_contacts, crm_customers RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _create_customer(tools: CrmCustomerTools, name: str = "示例科技", **overrides: object) -> UUID:
    kwargs: dict[str, object] = {"name": name}
    kwargs.update(overrides)
    result = await tools.create_customer(**kwargs)  # type: ignore[arg-type]
    return _extract_id(result)


def _extract_id(text_result: str) -> UUID:
    marker = "id="
    start = text_result.index(marker) + len(marker)
    end = start
    while end < len(text_result) and text_result[end] in "0123456789abcdef-":
        end += 1
    return UUID(text_result[start:end])


@pytest.mark.anyio
async def test_customer_create_get_update_delete_roundtrip(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)

    created = await customers.create_customer(
        name="示例科技",
        source="朋友介绍",
        notes="关注内容运营",
        next_action="安排需求访谈",
        next_follow_up_on=_today() + timedelta(days=2),
    )
    assert "已创建客户" in created and "示例科技" in created and "潜在客户" in created
    customer_id = _extract_id(created)

    detail = await customers.get_customer(customer_id)
    assert "客户「示例科技」" in detail
    assert "状态：潜在客户" in detail and "来源：朋友介绍" in detail
    assert "安排需求访谈" in detail
    assert "暂无联系人。" in detail and "暂无跟进记录。" in detail

    updated = await customers.update_customer(customer_id, status="跟进中", source="主动咨询")  # type: ignore[arg-type]
    assert "已更新客户" in updated and "跟进中" in updated and "主动咨询" in updated

    cleared = await customers.update_customer(customer_id, notes="")
    assert "已更新客户" in cleared
    detail_after = await customers.get_customer(customer_id)
    assert "关注内容运营" not in detail_after

    deleted = await customers.delete_customer(customer_id)
    assert "已删除客户「示例科技」" in deleted
    with pytest.raises(ToolError, match="客户不存在"):
        await customers.get_customer(customer_id)


@pytest.mark.anyio
async def test_customer_list_supports_query_status_and_due_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    overdue_id = await _create_customer(
        customers,
        name="逾期客户",
        status="跟进中",
        next_action="电话回访",
        next_follow_up_on=_today() - timedelta(days=1),
    )
    await _create_customer(customers, name="无计划客户", status="合作客户")
    await contacts.create_contact(overdue_id, name="可搜索联系人", phone="13900000000")

    full = await customers.list_customers()
    assert "共 2 个客户" in full and "逾期客户" in full and "无计划客户" in full

    by_name = await customers.list_customers(query="逾期")
    assert "逾期客户" in by_name and "无计划客户" not in by_name

    by_contact = await customers.list_customers(query="可搜索")
    assert "逾期客户" in by_contact and "无计划客户" not in by_contact

    by_status = await customers.list_customers(status="合作客户")  # type: ignore[arg-type]
    assert "无计划客户" in by_status and "逾期客户" not in by_status

    by_due = await customers.list_customers(due="overdue")
    assert "逾期客户" in by_due and "无计划客户" not in by_due

    empty = await customers.list_customers(query="不存在的关键词")
    assert "没有找到符合条件的客户" in empty


@pytest.mark.anyio
async def test_customer_validation_and_not_found_errors(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)

    with pytest.raises(ToolError, match="设置跟进日期时必须提供下一步行动"):
        await customers.create_customer(name="坏客户", next_follow_up_on=_today())

    customer_id = await _create_customer(customers, name="校验客户")
    with pytest.raises(ToolError, match="设置下次跟进日期时必须提供下一步行动"):
        await customers.update_customer(customer_id, next_action="", next_follow_up_on=_today())

    with pytest.raises(ToolError, match="没有需要修改的字段"):
        await customers.update_customer(customer_id)

    with pytest.raises(ToolError, match="客户不存在"):
        await customers.get_customer(uuid4())
    with pytest.raises(ToolError, match="客户不存在"):
        await customers.update_customer(uuid4(), name="x")
    with pytest.raises(ToolError, match="客户不存在"):
        await customers.delete_customer(uuid4())


@pytest.mark.anyio
async def test_contact_crud_and_primary_switch(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    customer_id = await _create_customer(customers)

    first = await contacts.create_contact(customer_id, name="王经理", role="创始人", is_primary=True)
    first_id = _extract_id(first)
    assert "唯一主联系人" in first
    second = await contacts.create_contact(customer_id, name="李助理", email="li@example.com")
    second_id = _extract_id(second)
    assert "唯一主联系人" not in second

    listed = await contacts.list_contacts(customer_id)
    assert listed.index("王经理") < listed.index("李助理")  # 主联系人排最前
    assert "创始人" in listed and "li@example.com" in listed

    # 设李助理为主联系人后，王经理自动降级（partial unique 约束由 service 保证）
    promoted = await contacts.update_contact(customer_id, second_id, is_primary=True)
    assert "已更新联系人" in promoted and "主联系人" in promoted
    listed_after = await contacts.list_contacts(customer_id)
    assert listed_after.index("李助理") < listed_after.index("王经理")

    updated = await contacts.update_contact(customer_id, first_id, phone="13800000000")
    assert "电话：13800000000" in updated

    deleted = await contacts.delete_contact(customer_id, second_id)
    assert "已删除联系人「李助理」" in deleted
    with pytest.raises(ToolError, match="联系人不存在"):
        await contacts.delete_contact(customer_id, second_id)


@pytest.mark.anyio
async def test_contact_email_validation_error(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    customer_id = await _create_customer(customers)

    with pytest.raises(ToolError, match="邮箱格式不正确"):
        await contacts.create_contact(customer_id, name="坏邮箱", email="not-an-email")


@pytest.mark.anyio
async def test_follow_up_crud_and_set_as_current(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)
    contact = await contacts.create_contact(customer_id, name="王经理")
    contact_id = _extract_id(contact)

    created = await follow_ups.create_follow_up(
        customer_id,
        kind="会议",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="上门拜访，确认了内容运营需求",
        contact_id=contact_id,
        next_action="发送方案",
        next_follow_up_on=_today() + timedelta(days=3),
        set_as_current=True,
    )
    assert "已为客户「示例科技」记录" in created and "会议跟进" in created
    assert "已同步为当前跟进计划" in created
    follow_up_id = _extract_id(created)

    # set_as_current 同步了客户当前跟进计划
    detail = await customers.get_customer(customer_id)
    assert "发送方案" in detail

    listed = await follow_ups.list_follow_ups(customer_id)
    assert "上门拜访，确认了内容运营需求" in listed and "联系人：王经理" in listed

    updated = await follow_ups.update_follow_up(customer_id, follow_up_id, summary="拜访后补充：预算待确认")
    assert "已更新跟进记录" in updated and "预算待确认" in updated

    deleted = await follow_ups.delete_follow_up(customer_id, follow_up_id)
    assert "已删除" in deleted and "会议跟进" in deleted
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await follow_ups.delete_follow_up(customer_id, follow_up_id)


@pytest.mark.anyio
@pytest.mark.parametrize("clear_contact", [False, True])
async def test_follow_up_contact_only_update(
    session_factory: async_sessionmaker[AsyncSession], clear_contact: bool
) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)
    contact_id = _extract_id(await contacts.create_contact(customer_id, name="王经理"))
    follow_up_id = _extract_id(
        await follow_ups.create_follow_up(
            customer_id,
            kind="电话",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="电话沟通",
            contact_id=contact_id if clear_contact else None,
        )
    )

    updated = await follow_ups.update_follow_up(
        customer_id,
        follow_up_id,
        contact_id=None if clear_contact else contact_id,
        clear_contact=clear_contact,
    )

    assert "已更新跟进记录" in updated and "电话沟通" in updated
    assert ("联系人：王经理" in updated) is not clear_contact


@pytest.mark.anyio
@pytest.mark.parametrize("conflict", ["contact", "date", "empty"])
async def test_follow_up_update_clear_flags_validate_complete_input(
    session_factory: async_sessionmaker[AsyncSession], conflict: str
) -> None:
    follow_ups = CrmFollowUpTools(session_factory)
    kwargs: dict[str, object] = {}
    if conflict == "contact":
        kwargs = {"contact_id": uuid4(), "clear_contact": True}
        message = "contact_id 与 clear_contact 不能同时使用"
    elif conflict == "date":
        kwargs = {"next_follow_up_on": _today(), "clear_next_follow_up_on": True}
        message = "next_follow_up_on 与清除开关不能同时使用"
    else:
        message = "没有需要修改的字段"
    with pytest.raises(ToolError, match=message):
        await follow_ups.update_follow_up(uuid4(), uuid4(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_follow_up_contact_update_is_callable_over_mcp_protocol(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)
    contact_id = _extract_id(await contacts.create_contact(customer_id, name="王经理"))
    follow_up_id = _extract_id(
        await follow_ups.create_follow_up(
            customer_id,
            kind="电话",
            occurred_on=_today(),
            summary="电话沟通",  # type: ignore[arg-type]
        )
    )
    mcp = create_agent_mcp_server(session_factory, token="test-token")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "crm_follow_up_update",
            {"customer_id": str(customer_id), "follow_up_id": str(follow_up_id), "contact_id": str(contact_id)},
        )
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "已更新跟进记录" in block.text and "联系人：王经理" in block.text


@pytest.mark.anyio
async def test_follow_up_error_paths(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)

    with pytest.raises(ToolError, match="联系人不存在"):
        await follow_ups.create_follow_up(
            customer_id,
            kind="电话",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="电话沟通",
            contact_id=uuid4(),
        )

    with pytest.raises(ToolError, match="设置跟进日期时必须提供下一步行动"):
        await follow_ups.create_follow_up(
            customer_id,
            kind="微信",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="微信沟通",
            next_follow_up_on=_today(),
        )

    with pytest.raises(ToolError, match="跟进记录不存在"):
        await follow_ups.update_follow_up(customer_id, uuid4(), summary="x")

    # 跨客户访问按“不存在”处理，不泄露记录归属
    other_id = await _create_customer(customers, name="另一客户")
    created = await follow_ups.create_follow_up(
        other_id,
        kind="其他",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="其他沟通",
    )
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await follow_ups.update_follow_up(customer_id, _extract_id(created), summary="越权")


@pytest.mark.anyio
async def test_lead_funnel_stats_counts_by_status(session_factory: async_sessionmaker[AsyncSession]) -> None:
    customers = CrmCustomerTools(session_factory)
    assert "暂无客户" in await customers.lead_funnel_stats()

    await _create_customer(customers, name="客户A")
    await _create_customer(customers, name="客户B", status="跟进中")
    await _create_customer(customers, name="客户C", status="跟进中")
    await _create_customer(customers, name="客户D", status="已流失")

    funnel = await customers.lead_funnel_stats()
    assert "共 4 个客户" in funnel
    assert "潜在客户 1" in funnel
    assert "跟进中 2" in funnel
    assert "合作客户 0" in funnel
    assert "暂停跟进 0" in funnel
    assert "已流失 1" in funnel


@pytest.mark.anyio
async def test_due_follow_ups_lists_overdue_and_today_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = CrmCustomerTools(session_factory)
    assert "没有到期或逾期的待跟进客户" in await customers.list_due_follow_ups()

    await _create_customer(
        customers,
        name="逾期客户",
        next_action="补打电话",
        next_follow_up_on=_today() - timedelta(days=2),
    )
    await _create_customer(
        customers,
        name="今日客户",
        next_action="发送方案",
        next_follow_up_on=_today(),
    )
    await _create_customer(
        customers,
        name="未来客户",
        next_action="约见",
        next_follow_up_on=_today() + timedelta(days=5),
    )
    await _create_customer(customers, name="无计划客户")

    due = await customers.list_due_follow_ups()
    assert "共 2 个客户" in due
    assert "逾期客户" in due and "已逾期 2 天" in due
    assert "今日客户" in due and "今天到期" in due
    assert "未来客户" not in due and "无计划客户" not in due
    # 逾期排在今天到期之前
    assert due.index("逾期客户") < due.index("今日客户")


@pytest.mark.anyio
async def test_delete_customer_cascades_contacts_and_follow_ups(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)
    await contacts.create_contact(customer_id, name="王经理")
    await follow_ups.create_follow_up(
        customer_id,
        kind="会议",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="拜访记录",
    )

    await customers.delete_customer(customer_id)

    with pytest.raises(ToolError, match="客户不存在"):
        await contacts.list_contacts(customer_id)
    with pytest.raises(ToolError, match="客户不存在"):
        await follow_ups.list_follow_ups(customer_id)
    assert "共 0 个客户" not in await customers.list_customers()  # 列表不再包含已删客户
    assert "示例科技" not in await customers.list_customers()


@pytest.mark.anyio
async def test_tools_are_callable_over_mcp_protocol(session_factory: async_sessionmaker[AsyncSession]) -> None:
    mcp = create_agent_mcp_server(session_factory, token="test-token")

    async with Client(mcp) as client:
        tools = await client.list_tools()
        crm_tool_names = {tool.name for tool in tools if tool.name.startswith("crm_")}
        assert crm_tool_names == {
            "crm_customer_list",
            "crm_customer_get",
            "crm_customer_create",
            "crm_customer_update",
            "crm_customer_delete",
            "crm_contact_list",
            "crm_contact_create",
            "crm_contact_update",
            "crm_contact_delete",
            "crm_follow_up_list",
            "crm_follow_up_create",
            "crm_follow_up_update",
            "crm_follow_up_delete",
            "crm_lead_funnel",
            "crm_due_follow_ups",
        }

        created = await client.call_tool(
            "crm_customer_create",
            {"name": "协议客户", "status": "跟进中"},
        )
        block = created.content[0]
        assert isinstance(block, TextContent)
        assert "已创建客户" in block.text and "协议客户" in block.text

        listed = await client.call_tool("crm_customer_list", {"query": "协议"})
        list_block = listed.content[0]
        assert isinstance(list_block, TextContent)
        assert "协议客户" in list_block.text and "跟进中" in list_block.text

        funnel = await client.call_tool("crm_lead_funnel", {})
        funnel_block = funnel.content[0]
        assert isinstance(funnel_block, TextContent)
        assert "跟进中 1" in funnel_block.text
