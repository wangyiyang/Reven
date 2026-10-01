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
from reven.agent.tools_crm import CrmTools
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


async def _create_customer(tools: CrmTools, name: str = "示例科技", **overrides: object) -> UUID:
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
    tools = CrmTools(session_factory)

    created = await tools.create_customer(
        name="示例科技",
        source="朋友介绍",
        notes="关注内容运营",
        next_action="安排需求访谈",
        next_follow_up_on=_today() + timedelta(days=2),
    )
    assert "已创建客户" in created and "示例科技" in created and "潜在客户" in created
    customer_id = _extract_id(created)

    detail = await tools.get_customer(customer_id)
    assert "客户「示例科技」" in detail
    assert "状态：潜在客户" in detail and "来源：朋友介绍" in detail
    assert "安排需求访谈" in detail
    assert "暂无联系人。" in detail and "暂无跟进记录。" in detail

    updated = await tools.update_customer(customer_id, status="跟进中", source="主动咨询")  # type: ignore[arg-type]
    assert "已更新客户" in updated and "跟进中" in updated and "主动咨询" in updated

    cleared = await tools.update_customer(customer_id, notes="")
    assert "已更新客户" in cleared
    detail_after = await tools.get_customer(customer_id)
    assert "关注内容运营" not in detail_after

    deleted = await tools.delete_customer(customer_id, confirm_customer_name="示例科技")
    assert "已删除客户「示例科技」" in deleted
    with pytest.raises(ToolError, match="客户不存在"):
        await tools.get_customer(customer_id)


@pytest.mark.anyio
async def test_customer_list_supports_query_status_and_due_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tools = CrmTools(session_factory)
    overdue_id = await _create_customer(
        tools,
        name="逾期客户",
        status="跟进中",
        next_action="电话回访",
        next_follow_up_on=_today() - timedelta(days=1),
    )
    await _create_customer(tools, name="无计划客户", status="合作客户")
    await tools.create_contact(overdue_id, name="可搜索联系人", phone="13900000000")

    full = await tools.list_customers()
    assert "共 2 个客户" in full and "逾期客户" in full and "无计划客户" in full

    by_name = await tools.list_customers(query="逾期")
    assert "逾期客户" in by_name and "无计划客户" not in by_name

    by_contact = await tools.list_customers(query="可搜索")
    assert "逾期客户" in by_contact and "无计划客户" not in by_contact

    by_status = await tools.list_customers(status="合作客户")  # type: ignore[arg-type]
    assert "无计划客户" in by_status and "逾期客户" not in by_status

    by_due = await tools.list_customers(due="overdue")
    assert "逾期客户" in by_due and "无计划客户" not in by_due

    empty = await tools.list_customers(query="不存在的关键词")
    assert "没有找到符合条件的客户" in empty


@pytest.mark.anyio
async def test_customer_validation_and_not_found_errors(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)

    with pytest.raises(ToolError, match="设置跟进日期时必须提供下一步行动"):
        await tools.create_customer(name="坏客户", next_follow_up_on=_today())

    customer_id = await _create_customer(tools, name="校验客户")
    with pytest.raises(ToolError, match="设置下次跟进日期时必须提供下一步行动"):
        await tools.update_customer(customer_id, next_action="", next_follow_up_on=_today())

    with pytest.raises(ToolError, match="没有需要修改的字段"):
        await tools.update_customer(customer_id)

    with pytest.raises(ToolError, match="客户不存在"):
        await tools.get_customer(uuid4())
    with pytest.raises(ToolError, match="客户不存在"):
        await tools.update_customer(uuid4(), name="x")
    with pytest.raises(ToolError, match="客户不存在"):
        await tools.delete_customer(uuid4(), confirm_customer_name="任意名称")


@pytest.mark.anyio
async def test_contact_crud_and_primary_switch(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)

    first = await tools.create_contact(customer_id, name="王经理", role="创始人", is_primary=True)
    first_id = _extract_id(first)
    assert "唯一主联系人" in first
    second = await tools.create_contact(customer_id, name="李助理", email="li@example.com")
    second_id = _extract_id(second)
    assert "唯一主联系人" not in second

    listed = await tools.list_contacts(customer_id)
    assert listed.index("王经理") < listed.index("李助理")  # 主联系人排最前
    assert "创始人" in listed and "li@example.com" in listed

    # 设李助理为主联系人后，王经理自动降级（partial unique 约束由 service 保证）
    promoted = await tools.update_contact(customer_id, second_id, is_primary=True)
    assert "已更新联系人" in promoted and "主联系人" in promoted
    listed_after = await tools.list_contacts(customer_id)
    assert listed_after.index("李助理") < listed_after.index("王经理")

    updated = await tools.update_contact(customer_id, first_id, phone="13800000000")
    assert "电话：13800000000" in updated

    deleted = await tools.delete_contact(customer_id, second_id, confirm_customer_name="示例科技")
    assert "已删除联系人「李助理」" in deleted
    with pytest.raises(ToolError, match="联系人不存在"):
        await tools.delete_contact(customer_id, second_id, confirm_customer_name="示例科技")


@pytest.mark.anyio
async def test_contact_email_validation_error(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)

    with pytest.raises(ToolError, match="邮箱格式不正确"):
        await tools.create_contact(customer_id, name="坏邮箱", email="not-an-email")


@pytest.mark.anyio
async def test_follow_up_crud_and_set_as_current(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)
    contact = await tools.create_contact(customer_id, name="王经理")
    contact_id = _extract_id(contact)

    created = await tools.create_follow_up(
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
    detail = await tools.get_customer(customer_id)
    assert "发送方案" in detail

    listed = await tools.list_follow_ups(customer_id)
    assert "上门拜访，确认了内容运营需求" in listed and "联系人：王经理" in listed

    updated = await tools.update_follow_up(customer_id, follow_up_id, summary="拜访后补充：预算待确认")
    assert "已更新跟进记录" in updated and "预算待确认" in updated

    deleted = await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="示例科技")
    assert "已删除" in deleted and "会议跟进" in deleted
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="示例科技")


@pytest.mark.anyio
async def test_follow_up_error_paths(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)

    with pytest.raises(ToolError, match="联系人不存在"):
        await tools.create_follow_up(
            customer_id,
            kind="电话",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="电话沟通",
            contact_id=uuid4(),
        )

    with pytest.raises(ToolError, match="设置跟进日期时必须提供下一步行动"):
        await tools.create_follow_up(
            customer_id,
            kind="微信",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="微信沟通",
            next_follow_up_on=_today(),
        )

    with pytest.raises(ToolError, match="跟进记录不存在"):
        await tools.update_follow_up(customer_id, uuid4(), summary="x")

    # 跨客户访问按“不存在”处理，不泄露记录归属
    other_id = await _create_customer(tools, name="另一客户")
    created = await tools.create_follow_up(
        other_id,
        kind="其他",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="其他沟通",
    )
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await tools.update_follow_up(customer_id, _extract_id(created), summary="越权")


@pytest.mark.anyio
async def test_lead_funnel_stats_counts_by_status(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = CrmTools(session_factory)
    assert "暂无客户" in await tools.lead_funnel_stats()

    await _create_customer(tools, name="客户A")
    await _create_customer(tools, name="客户B", status="跟进中")
    await _create_customer(tools, name="客户C", status="跟进中")
    await _create_customer(tools, name="客户D", status="已流失")

    funnel = await tools.lead_funnel_stats()
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
    tools = CrmTools(session_factory)
    assert "没有到期或逾期的待跟进客户" in await tools.list_due_follow_ups()

    await _create_customer(
        tools,
        name="逾期客户",
        next_action="补打电话",
        next_follow_up_on=_today() - timedelta(days=2),
    )
    await _create_customer(
        tools,
        name="今日客户",
        next_action="发送方案",
        next_follow_up_on=_today(),
    )
    await _create_customer(
        tools,
        name="未来客户",
        next_action="约见",
        next_follow_up_on=_today() + timedelta(days=5),
    )
    await _create_customer(tools, name="无计划客户")

    due = await tools.list_due_follow_ups()
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
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)
    await tools.create_contact(customer_id, name="王经理")
    await tools.create_follow_up(
        customer_id,
        kind="会议",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="拜访记录",
    )

    await tools.delete_customer(customer_id, confirm_customer_name="示例科技")

    with pytest.raises(ToolError, match="客户不存在"):
        await tools.list_contacts(customer_id)
    with pytest.raises(ToolError, match="客户不存在"):
        await tools.list_follow_ups(customer_id)
    assert "共 0 个客户" not in await tools.list_customers()  # 列表不再包含已删客户
    assert "示例科技" not in await tools.list_customers()


@pytest.mark.anyio
async def test_delete_customer_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#176 server 侧防呆：confirm_customer_name 与客户名称逐字不等时拒绝删除，记录仍在。"""
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)

    with pytest.raises(ToolError, match="confirm_customer_name 与客户名称不完全一致"):
        await tools.delete_customer(customer_id, confirm_customer_name="示例")
    with pytest.raises(ToolError, match="confirm_customer_name 与客户名称不完全一致"):
        await tools.delete_customer(customer_id, confirm_customer_name="示例科技 ")

    assert "客户「示例科技」" in await tools.get_customer(customer_id)  # 未删除
    deleted = await tools.delete_customer(customer_id, confirm_customer_name="示例科技")
    assert "已删除客户「示例科技」" in deleted


@pytest.mark.anyio
async def test_delete_contact_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#176 server 侧防呆：删除联系人也须逐字确认所属客户名称。"""
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)
    contact_id = _extract_id(await tools.create_contact(customer_id, name="王经理"))

    with pytest.raises(ToolError, match="confirm_customer_name 与客户名称不完全一致"):
        await tools.delete_contact(customer_id, contact_id, confirm_customer_name="别的客户")

    assert "王经理" in await tools.list_contacts(customer_id)  # 未删除
    deleted = await tools.delete_contact(customer_id, contact_id, confirm_customer_name="示例科技")
    assert "已删除联系人「王经理」" in deleted


@pytest.mark.anyio
async def test_delete_follow_up_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#176 server 侧防呆：删除跟进记录也须逐字确认所属客户名称。"""
    tools = CrmTools(session_factory)
    customer_id = await _create_customer(tools)
    follow_up_id = _extract_id(
        await tools.create_follow_up(
            customer_id,
            kind="会议",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="拜访记录",
        )
    )

    with pytest.raises(ToolError, match="confirm_customer_name 与客户名称不完全一致"):
        await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="")

    assert "拜访记录" in await tools.list_follow_ups(customer_id)  # 未删除
    deleted = await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="示例科技")
    assert "已删除" in deleted


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

        # #176：三个 CRM 删除工具的 confirm_customer_name 在协议层为必填参数（缺参即被协议拒绝）
        crm_delete_tools = [
            t for t in tools if t.name in {"crm_customer_delete", "crm_contact_delete", "crm_follow_up_delete"}
        ]
        assert len(crm_delete_tools) == 3
        for delete_tool in crm_delete_tools:
            assert "confirm_customer_name" in delete_tool.input_schema.get("required", []), delete_tool.name

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
