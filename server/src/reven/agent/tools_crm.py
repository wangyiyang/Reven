"""Explicit registration of CRM customer, contact, and follow-up MCP adapters."""

from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.tools_crm_contacts import CrmContactTools
from reven.agent.tools_crm_customers import CrmCustomerTools
from reven.agent.tools_crm_follow_ups import CrmFollowUpTools


def register_crm_tools(mcp: FastMCP, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """把 CRM 人才库能力注册为 MCP 工具（模型侧呈现为 mcp__reven__crm_*）。"""
    customers = CrmCustomerTools(session_factory)
    contacts = CrmContactTools(session_factory)
    follow_ups = CrmFollowUpTools(session_factory)
    mcp.tool(customers.list_customers, name="crm_customer_list")
    mcp.tool(customers.get_customer, name="crm_customer_get")
    mcp.tool(customers.create_customer, name="crm_customer_create")
    mcp.tool(customers.update_customer, name="crm_customer_update")
    mcp.tool(customers.delete_customer, name="crm_customer_delete")
    mcp.tool(contacts.list_contacts, name="crm_contact_list")
    mcp.tool(contacts.create_contact, name="crm_contact_create")
    mcp.tool(contacts.update_contact, name="crm_contact_update")
    mcp.tool(contacts.delete_contact, name="crm_contact_delete")
    mcp.tool(follow_ups.list_follow_ups, name="crm_follow_up_list")
    mcp.tool(follow_ups.create_follow_up, name="crm_follow_up_create")
    mcp.tool(follow_ups.update_follow_up, name="crm_follow_up_update")
    mcp.tool(follow_ups.delete_follow_up, name="crm_follow_up_delete")
    mcp.tool(customers.lead_funnel_stats, name="crm_lead_funnel")
    mcp.tool(customers.list_due_follow_ups, name="crm_due_follow_ups")
