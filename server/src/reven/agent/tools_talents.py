"""Explicit registration of talents talent, interaction, experience, and education MCP adapters."""

from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.tools_talents_educations import TalentsEducationTools
from reven.agent.tools_talents_experiences import TalentsExperienceTools
from reven.agent.tools_talents_interactions import TalentsInteractionTools
from reven.agent.tools_talents_talents import TalentsTalentTools


def register_talents_tools(mcp: FastMCP, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """把 talents 人才库能力注册为 MCP 工具（模型侧呈现为 mcp__reven__talent_*）。"""
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    experiences = TalentsExperienceTools(session_factory)
    educations = TalentsEducationTools(session_factory)
    mcp.tool(talents.list_talents, name="talent_list")
    mcp.tool(talents.get_talent, name="talent_get")
    mcp.tool(talents.create_talent, name="talent_create")
    mcp.tool(talents.update_talent, name="talent_update")
    mcp.tool(talents.delete_talent, name="talent_delete")
    mcp.tool(interactions.list_interactions, name="talent_interaction_list")
    mcp.tool(interactions.create_interaction, name="talent_interaction_create")
    mcp.tool(interactions.update_interaction, name="talent_interaction_update")
    mcp.tool(interactions.delete_interaction, name="talent_interaction_delete")
    mcp.tool(experiences.list_experiences, name="talent_experience_list")
    mcp.tool(experiences.create_experience, name="talent_experience_create")
    mcp.tool(experiences.update_experience, name="talent_experience_update")
    mcp.tool(experiences.delete_experience, name="talent_experience_delete")
    mcp.tool(educations.list_educations, name="talent_education_list")
    mcp.tool(educations.create_education, name="talent_education_create")
    mcp.tool(educations.update_education, name="talent_education_update")
    mcp.tool(educations.delete_education, name="talent_education_delete")
    mcp.tool(talents.import_profile, name="talent_import_profile")
