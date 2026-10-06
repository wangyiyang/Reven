"""拆分后的 Talents MCP 删除工具保留精确名称确认（对齐 #176 CRM 防呆）。"""

import pytest
from fastmcp.exceptions import ToolError
from reven.agent.tools_talents_educations import TalentsEducationTools
from reven.agent.tools_talents_experiences import TalentsExperienceTools
from reven.agent.tools_talents_interactions import TalentsInteractionTools
from reven.agent.tools_talents_talents import TalentsTalentTools
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from talents_tools_support import _create_talent, _extract_id, _today
from talents_tools_support import session_factory as session_factory


@pytest.mark.anyio
async def test_delete_talent_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """confirm_talent_name 与人才名称逐字不等时拒绝删除，记录仍在。"""
    tools = TalentsTalentTools(session_factory)
    talent_id = await _create_talent(tools)

    with pytest.raises(ToolError, match="confirm_talent_name 与人才名称不完全一致"):
        await tools.delete_talent(talent_id, confirm_talent_name="设计师")
    with pytest.raises(ToolError, match="confirm_talent_name 与人才名称不完全一致"):
        await tools.delete_talent(talent_id, confirm_talent_name="设计师小李 ")

    assert "人才「设计师小李」" in await tools.get_talent(talent_id)  # 未删除
    deleted = await tools.delete_talent(talent_id, confirm_talent_name="设计师小李")
    assert "已删除人才「设计师小李」" in deleted


@pytest.mark.anyio
async def test_delete_interaction_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """删除互动记录也须逐字确认所属人才名称。"""
    talents = TalentsTalentTools(session_factory)
    tools = TalentsInteractionTools(session_factory)
    talent_id = await _create_talent(talents)
    interaction_id = _extract_id(
        await tools.create_interaction(
            talent_id,
            channel="面谈",  # type: ignore[arg-type]
            occurred_on=_today(),
            summary="面谈记录",
        )
    )

    with pytest.raises(ToolError, match="confirm_talent_name 与人才名称不完全一致"):
        await tools.delete_interaction(talent_id, interaction_id, confirm_talent_name="")

    assert "面谈记录" in await tools.list_interactions(talent_id)  # 未删除
    deleted = await tools.delete_interaction(talent_id, interaction_id, confirm_talent_name="设计师小李")
    assert "已删除" in deleted


@pytest.mark.anyio
async def test_delete_experience_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """删除履历也须逐字确认所属人才名称。"""
    talents = TalentsTalentTools(session_factory)
    tools = TalentsExperienceTools(session_factory)
    talent_id = await _create_talent(talents)
    experience_id = _extract_id(
        await tools.create_experience(
            talent_id,
            company="远山设计",
            title="视觉设计师",
            start_on=_today().replace(day=1),
        )
    )

    with pytest.raises(ToolError, match="confirm_talent_name 与人才名称不完全一致"):
        await tools.delete_experience(talent_id, experience_id, confirm_talent_name="别的人才")

    assert "远山设计" in await tools.list_experiences(talent_id)  # 未删除
    deleted = await tools.delete_experience(talent_id, experience_id, confirm_talent_name="设计师小李")
    assert "已删除履历「远山设计·视觉设计师」" in deleted


@pytest.mark.anyio
async def test_delete_education_requires_exact_name_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """删除院校经历也须逐字确认所属人才名称。"""
    talents = TalentsTalentTools(session_factory)
    tools = TalentsEducationTools(session_factory)
    talent_id = await _create_talent(talents)
    education_id = _extract_id(
        await tools.create_education(
            talent_id,
            school="中央美术学院",
            start_on=_today().replace(day=1),
        )
    )

    with pytest.raises(ToolError, match="confirm_talent_name 与人才名称不完全一致"):
        await tools.delete_education(talent_id, education_id, confirm_talent_name="别的人才")

    assert "中央美术学院" in await tools.list_educations(talent_id)  # 未删除
    deleted = await tools.delete_education(talent_id, education_id, confirm_talent_name="设计师小李")
    assert "已删除院校经历「中央美术学院」" in deleted
