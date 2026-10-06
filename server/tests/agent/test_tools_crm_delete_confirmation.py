"""拆分后的 CRM MCP 删除工具保留精确名称确认。"""

import pytest
from crm_tools_support import _create_customer, _extract_id, _today
from crm_tools_support import session_factory as session_factory
from fastmcp.exceptions import ToolError
from reven.agent.tools_crm_contacts import CrmContactTools
from reven.agent.tools_crm_customers import CrmCustomerTools
from reven.agent.tools_crm_follow_ups import CrmFollowUpTools
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_delete_customer_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """#176 server 侧防呆：confirm_customer_name 与客户名称逐字不等时拒绝删除，记录仍在。"""
    tools = CrmCustomerTools(session_factory)
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
    customers = CrmCustomerTools(session_factory)
    tools = CrmContactTools(session_factory)
    customer_id = await _create_customer(customers)
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
    customers = CrmCustomerTools(session_factory)
    tools = CrmFollowUpTools(session_factory)
    customer_id = await _create_customer(customers)
    follow_up_id = _extract_id(
        await tools.create_follow_up(
            customer_id,
            kind="面谈",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="拜访记录",
        )
    )

    with pytest.raises(ToolError, match="confirm_customer_name 与客户名称不完全一致"):
        await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="")

    assert "拜访记录" in await tools.list_follow_ups(customer_id)  # 未删除
    deleted = await tools.delete_follow_up(customer_id, follow_up_id, confirm_customer_name="示例科技")
    assert "已删除" in deleted
