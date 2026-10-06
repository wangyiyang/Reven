"""Talents 人才库 MCP 工具测试（#201 P3）：四实体 CRUD、筛选、校验文案、协议面与批量导入。"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import TextContent
from reven.agent.mcp_server import create_agent_mcp_server
from reven.agent.tools_talents_educations import TalentsEducationTools
from reven.agent.tools_talents_experiences import TalentsExperienceTools
from reven.agent.tools_talents_interactions import TalentsInteractionTools
from reven.agent.tools_talents_talents import TalentsTalentTools
from reven.talents.errors import InvalidProfileImportError
from reven.talents.inputs import TalentEducationCreate, TalentExperienceCreate
from reven.talents.service import TalentsService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from talents_tools_support import _create_talent, _extract_id, _today
from talents_tools_support import session_factory as session_factory

EXPECTED_TALENT_TOOL_NAMES = {
    "talent_list",
    "talent_get",
    "talent_create",
    "talent_update",
    "talent_delete",
    "talent_interaction_list",
    "talent_interaction_create",
    "talent_interaction_update",
    "talent_interaction_delete",
    "talent_experience_list",
    "talent_experience_create",
    "talent_experience_update",
    "talent_experience_delete",
    "talent_education_list",
    "talent_education_create",
    "talent_education_update",
    "talent_education_delete",
    "talent_import_profile",
}


@pytest.mark.anyio
async def test_talent_create_get_update_delete_roundtrip(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)

    created = await talents.create_talent(
        name="设计师小李",
        organization="自由职业",
        tags=["设计", "品牌"],
        preferences=["远程工作"],
        phone="13800001111",
        email="designer@example.com",
        capability="品牌视觉设计",
        rate_amount=Decimal("500.00"),
        rate_unit="按天",  # type: ignore[arg-type]
        rating=4,
        notes="朋友推荐",
    )
    assert "已创建人才" in created and "设计师小李" in created and "候选" in created
    assert "talent_interaction_create" in created  # 创建后引导记录第一次接洽
    talent_id = _extract_id(created)

    detail = await talents.get_talent(talent_id)
    assert "人才「设计师小李」" in detail
    assert "状态：候选｜单位：自由职业" in detail
    assert "当前跟进计划：未安排" in detail  # 无互动时派生计划为空
    assert "标签：设计、品牌" in detail and "喜好：远程工作" in detail
    assert "电话 13800001111" in detail and "邮箱 designer@example.com" in detail
    assert "费率：500.00 按天" in detail and "评分：4" in detail
    assert "暂无互动记录。可用 talent_interaction_create 记录第一次接洽并定下当前计划。" in detail
    assert "暂无履历。" in detail and "暂无院校经历。" in detail

    logged = await interactions.create_interaction(
        talent_id,
        channel="面谈",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="初次面谈，确认品牌需求",
        next_action="发送作品集",
        next_due_on=_today() + timedelta(days=2),
    )
    assert "已自动生效为人才当前计划" in logged
    assert "发送作品集" in await talents.get_talent(talent_id)

    updated = await talents.update_talent(talent_id, status="接洽中", notes="已约二面")  # type: ignore[arg-type]
    assert "已更新人才" in updated and "接洽中" in updated
    assert "发送作品集" in updated  # 更新画像不影响派生计划

    retagged = await talents.update_talent(talent_id, tags=["插画"], notes="")
    assert "已更新人才" in retagged
    detail_after = await talents.get_talent(talent_id)
    assert "标签：插画" in detail_after and "朋友推荐" not in detail_after and "已约二面" not in detail_after

    cleared = await talents.update_talent(talent_id, clear_rate=True)
    assert "已更新人才" in cleared
    assert "费率" not in await talents.get_talent(talent_id)

    deleted = await talents.delete_talent(talent_id, confirm_talent_name="设计师小李")
    assert "已删除人才「设计师小李」" in deleted and "互动记录、履历与院校经历已一并删除" in deleted
    with pytest.raises(ToolError, match="人才不存在"):
        await talents.get_talent(talent_id)


@pytest.mark.anyio
async def test_talent_list_supports_query_status_due_and_tag_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    experiences = TalentsExperienceTools(session_factory)
    overdue_id = await _create_talent(talents, name="逾期人才", status="接洽中", tags=["开发"])
    await interactions.create_interaction(
        overdue_id,
        channel="电话",  # type: ignore[arg-type]
        occurred_on=_today() - timedelta(days=2),
        summary="电话沟通",
        next_action="电话回访",
        next_due_on=_today() - timedelta(days=1),
    )
    await _create_talent(
        talents,
        name="无计划人才",
        organization="某科技公司",
        status="已合作",
        tags=["设计"],
        capability="品牌视觉",
    )
    await experiences.create_experience(
        overdue_id,
        company="远山设计",
        title="视觉设计师",
        start_on=_today() - timedelta(days=365),
    )

    full = await talents.list_talents()
    assert "共 2 个人才" in full and "逾期人才" in full and "无计划人才" in full
    assert "电话回访" in full  # 列表行展示派生计划
    assert "标签：开发" in full

    by_name = await talents.list_talents(query="逾期")
    assert "逾期人才" in by_name and "无计划人才" not in by_name

    by_organization = await talents.list_talents(query="科技公司")
    assert "无计划人才" in by_organization and "逾期人才" not in by_organization

    by_capability = await talents.list_talents(query="品牌视觉")
    assert "无计划人才" in by_capability and "逾期人才" not in by_capability

    by_experience_company = await talents.list_talents(query="远山")
    assert "逾期人才" in by_experience_company and "无计划人才" not in by_experience_company

    by_status = await talents.list_talents(status="已合作")  # type: ignore[arg-type]
    assert "无计划人才" in by_status and "逾期人才" not in by_status

    by_due = await talents.list_talents(due="overdue")
    assert "逾期人才" in by_due and "无计划人才" not in by_due

    by_tag = await talents.list_talents(tag="设计")
    assert "无计划人才" in by_tag and "逾期人才" not in by_tag

    empty = await talents.list_talents(query="不存在的关键词")
    assert "没有找到符合条件的人才" in empty


@pytest.mark.anyio
async def test_talent_validation_and_not_found_errors(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)

    with pytest.raises(ToolError, match="费率金额与单位必须同时填写或同时留空"):
        await talents.create_talent(name="只填金额", rate_amount=Decimal("500.00"))
    with pytest.raises(ToolError, match="邮箱格式不正确"):
        await talents.create_talent(name="坏邮箱", email="not-an-email")

    talent_id = await _create_talent(talents, name="校验人才")
    with pytest.raises(ToolError, match="没有需要修改的字段"):
        await talents.update_talent(talent_id)

    # 人才原本无费率，只改金额触发 service 合并校验
    with pytest.raises(ToolError, match="费率金额与单位必须同时填写或同时留空"):
        await talents.update_talent(talent_id, rate_amount=Decimal("500.00"))

    with pytest.raises(ToolError, match="clear_rate 与费率字段不能同时使用"):
        await talents.update_talent(talent_id, rate_amount=Decimal("500.00"), clear_rate=True)

    with pytest.raises(ToolError, match="人才不存在"):
        await talents.get_talent(uuid4())
    with pytest.raises(ToolError, match="人才不存在"):
        await talents.update_talent(uuid4(), name="x")
    with pytest.raises(ToolError, match="人才不存在"):
        await talents.delete_talent(uuid4(), confirm_talent_name="任意名称")


@pytest.mark.anyio
async def test_interaction_crud_and_derived_current_plan(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    talent_id = await _create_talent(talents)

    created = await interactions.create_interaction(
        talent_id,
        channel="微信",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="微信沟通了合作意向",
        next_action="发送报价",
        next_due_on=_today() + timedelta(days=3),
    )
    assert "已为人才「设计师小李」记录" in created and "微信互动" in created
    assert "已自动生效为人才当前计划" in created
    assert "set_as_current" not in created and "min" not in created
    interaction_id = _extract_id(created)

    detail = await talents.get_talent(talent_id)
    assert "发送报价" in detail and "互动记录（1）" in detail

    listed = await interactions.list_interactions(talent_id)
    assert "微信沟通了合作意向" in listed and "下一步：" in listed

    updated = await interactions.update_interaction(talent_id, interaction_id, summary="补充：预算待确认")
    assert "已更新跟进记录" in updated and "预算待确认" in updated

    cleared = await interactions.update_interaction(talent_id, interaction_id, clear_next_due_on=True)
    assert "已更新跟进记录" in cleared
    # 清除日期后派生计划只剩行动（不带日期），旧到期日不再冒泡
    detail_cleared = await talents.get_talent(talent_id)
    due_on_text = (_today() + timedelta(days=3)).isoformat()
    assert "当前跟进计划：发送报价" in detail_cleared and due_on_text not in detail_cleared

    deleted = await interactions.delete_interaction(talent_id, interaction_id, confirm_talent_name="设计师小李")
    assert "已删除" in deleted and "微信互动" in deleted
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await interactions.delete_interaction(talent_id, interaction_id, confirm_talent_name="设计师小李")


@pytest.mark.anyio
async def test_backfilled_interaction_does_not_claim_current_plan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """补录早于最新互动的历史记录：返回文案不得声称计划已生效，派生计划仍取最新一条。"""
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    talent_id = await _create_talent(talents)
    due_on = _today() + timedelta(days=3)
    await interactions.create_interaction(
        talent_id,
        channel="面谈",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="最新面谈",
        next_action="发送合同",
        next_due_on=due_on,
    )

    backfilled = await interactions.create_interaction(
        talent_id,
        channel="电话",  # type: ignore[arg-type]
        occurred_on=_today() - timedelta(days=30),
        summary="补录早期电话",
        next_action="旧约定",
        next_due_on=_today() - timedelta(days=20),
    )

    assert "已自动生效为人才当前计划" not in backfilled
    assert "当前计划不变" in backfilled and "发送合同" in backfilled
    detail = await talents.get_talent(talent_id)
    assert f"当前跟进计划：{due_on.isoformat()} 发送合同" in detail


@pytest.mark.anyio
async def test_interaction_error_paths(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    talent_id = await _create_talent(talents)

    with pytest.raises(ToolError, match="人才不存在"):
        await interactions.create_interaction(
            uuid4(),
            channel="微信",  # type: ignore[arg-type]
            occurred_on=_today(),
        )
    with pytest.raises(ToolError, match="人才不存在"):
        await interactions.list_interactions(uuid4())

    with pytest.raises(ToolError, match="跟进记录不存在"):
        await interactions.update_interaction(talent_id, uuid4(), summary="x")

    # 跨人才访问按“不存在”处理，不泄露记录归属
    other_id = await _create_talent(talents, name="另一人才")
    created = await interactions.create_interaction(
        other_id,
        channel="其他",  # type: ignore[arg-type]
        occurred_on=_today(),
        summary="其他沟通",
    )
    with pytest.raises(ToolError, match="跟进记录不存在"):
        await interactions.update_interaction(talent_id, _extract_id(created), summary="越权")


@pytest.mark.anyio
@pytest.mark.parametrize("conflict", ["date", "empty"])
async def test_interaction_update_clear_flags_validate_complete_input(
    session_factory: async_sessionmaker[AsyncSession], conflict: str
) -> None:
    interactions = TalentsInteractionTools(session_factory)
    if conflict == "date":
        kwargs: dict[str, object] = {"next_due_on": _today(), "clear_next_due_on": True}
        message = "next_due_on 与清除开关不能同时使用"
    else:
        kwargs = {}
        message = "没有需要修改的字段"
    with pytest.raises(ToolError, match=message):
        await interactions.update_interaction(uuid4(), uuid4(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_experience_crud_roundtrip(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    experiences = TalentsExperienceTools(session_factory)
    talent_id = await _create_talent(talents)

    created = await experiences.create_experience(
        talent_id,
        company="远山设计",
        title="视觉设计师",
        start_on=_today().replace(day=1),
        description="负责品牌视觉",
    )
    assert "已为人才「设计师小李」添加履历" in created and "远山设计·视觉设计师" in created
    assert "至今" in created
    experience_id = _extract_id(created)

    listed = await experiences.list_experiences(talent_id)
    assert "人才「设计师小李」的履历（1）" in listed and "负责品牌视觉" in listed
    assert "履历（1）" in await talents.get_talent(talent_id)

    updated = await experiences.update_experience(talent_id, experience_id, title="资深视觉设计师")
    assert "已更新履历" in updated and "资深视觉设计师" in updated

    ended = await experiences.update_experience(
        talent_id, experience_id, end_on=_today().replace(day=1), clear_end_on=False
    )
    assert "至今" not in ended
    reopened = await experiences.update_experience(talent_id, experience_id, clear_end_on=True)
    assert "至今" in reopened

    deleted = await experiences.delete_experience(talent_id, experience_id, confirm_talent_name="设计师小李")
    assert "已删除履历「远山设计·资深视觉设计师」" in deleted
    assert "暂无履历" in await experiences.list_experiences(talent_id)


@pytest.mark.anyio
async def test_experience_date_range_validation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    experiences = TalentsExperienceTools(session_factory)
    talent_id = await _create_talent(talents)

    # 双字段提交非法：schema 直接拒绝
    with pytest.raises(ToolError, match="结束日期不能早于开始日期"):
        await experiences.create_experience(
            talent_id,
            company="远山设计",
            title="视觉设计师",
            start_on=_today().replace(day=1),
            end_on=_today().replace(day=1) - timedelta(days=365),
        )

    experience_id = _extract_id(
        await experiences.create_experience(
            talent_id,
            company="远山设计",
            title="视觉设计师",
            start_on=_today().replace(day=1),
        )
    )
    # 单边提交与现值合并后非法：service 合并校验拒绝
    with pytest.raises(ToolError, match="结束日期不能早于开始日期"):
        await experiences.update_experience(
            talent_id, experience_id, end_on=_today().replace(day=1) - timedelta(days=30)
        )

    with pytest.raises(ToolError, match="履历不存在"):
        await experiences.update_experience(talent_id, uuid4(), title="x")
    with pytest.raises(ToolError, match="end_on 与清除开关不能同时使用"):
        await experiences.update_experience(talent_id, experience_id, end_on=_today(), clear_end_on=True)

    # 跨人才访问按“不存在”处理
    other_id = await _create_talent(talents, name="另一人才")
    with pytest.raises(ToolError, match="履历不存在"):
        await experiences.update_experience(other_id, experience_id, title="越权")


@pytest.mark.anyio
async def test_education_crud_roundtrip(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    educations = TalentsEducationTools(session_factory)
    talent_id = await _create_talent(talents)

    created = await educations.create_education(
        talent_id,
        school="中央美术学院",
        degree="本科",
        major="视觉传达",
        start_on=_today().replace(day=1),
    )
    assert "已为人才「设计师小李」添加院校经历" in created
    assert "中央美术学院·本科·视觉传达" in created and "至今" in created
    education_id = _extract_id(created)

    listed = await educations.list_educations(talent_id)
    assert "人才「设计师小李」的院校经历（1）" in listed
    assert "院校经历（1）" in await talents.get_talent(talent_id)

    with pytest.raises(ToolError, match="结束日期不能早于开始日期"):
        await educations.create_education(
            talent_id,
            school="坏日期大学",
            start_on=_today().replace(day=1),
            end_on=_today().replace(day=1) - timedelta(days=365),
        )

    updated = await educations.update_education(talent_id, education_id, degree="硕士", major="")
    assert "已更新院校经历" in updated and "硕士" in updated and "视觉传达" not in updated

    cleared = await educations.update_education(talent_id, education_id, clear_end_on=True)
    assert "至今" in cleared

    with pytest.raises(ToolError, match="院校经历不存在"):
        await educations.update_education(talent_id, uuid4(), school="x")

    deleted = await educations.delete_education(talent_id, education_id, confirm_talent_name="设计师小李")
    assert "已删除院校经历「中央美术学院」" in deleted
    assert "暂无院校经历" in await educations.list_educations(talent_id)


@pytest.mark.anyio
async def test_delete_talent_cascades_children(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    interactions = TalentsInteractionTools(session_factory)
    experiences = TalentsExperienceTools(session_factory)
    educations = TalentsEducationTools(session_factory)
    talent_id = await _create_talent(talents)
    await interactions.create_interaction(talent_id, channel="微信", occurred_on=_today(), summary="沟通")  # type: ignore[arg-type]
    await experiences.create_experience(
        talent_id, company="远山设计", title="视觉设计师", start_on=_today().replace(day=1)
    )
    await educations.create_education(talent_id, school="中央美术学院", start_on=_today().replace(day=1))

    await talents.delete_talent(talent_id, confirm_talent_name="设计师小李")

    with pytest.raises(ToolError, match="人才不存在"):
        await interactions.list_interactions(talent_id)
    with pytest.raises(ToolError, match="人才不存在"):
        await experiences.list_experiences(talent_id)
    with pytest.raises(ToolError, match="人才不存在"):
        await educations.list_educations(talent_id)
    assert "设计师小李" not in await talents.list_talents()


@pytest.mark.anyio
async def test_import_profile_creates_full_profile_with_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    talents = TalentsTalentTools(session_factory)

    imported = await talents.import_profile(
        name="简介人才",
        organization="自由职业",
        tags=["设计", "品牌"],
        preferences=["远程工作"],
        phone="13800001111",
        capability="品牌视觉设计",
        experiences=[
            TalentExperienceCreate(company="远山设计", title="视觉设计师", start_on=_today().replace(day=1)),
            TalentExperienceCreate(
                company="前一家公司",
                title="设计实习生",
                start_on=_today().replace(day=1) - timedelta(days=730),
                end_on=_today().replace(day=1) - timedelta(days=365),
            ),
        ],
        educations=[TalentEducationCreate(school="中央美术学院", degree="本科", start_on=_today().replace(day=1))],
    )
    assert "已导入人才「简介人才」" in imported and "画像已创建" in imported
    assert "履历 2 条、院校 1 条" in imported
    talent_id = _extract_id(imported)

    detail = await talents.get_talent(talent_id)
    assert "标签：设计、品牌" in detail and "喜好：远程工作" in detail
    assert "履历（2）" in detail and "院校经历（1）" in detail
    assert "远山设计·视觉设计师" in detail

    # 同名再导入：更新提交的画像字段（phone）、追加子项，不重复创建人才
    again = await talents.import_profile(
        name="简介人才",
        email="designer@example.com",
        experiences=[TalentExperienceCreate(company="新一段履历", title="设计总监", start_on=_today().replace(day=1))],
    )
    assert "画像已更新" in again and "追加履历 1 条" in again
    assert _extract_id(again) == talent_id

    detail_after = await talents.get_talent(talent_id)
    assert "邮箱 designer@example.com" in detail_after
    assert "标签：设计、品牌" in detail_after  # 未提交的字段保持不变
    assert "履历（3）" in detail_after  # 追加语义不去重
    assert "共 1 个人才" in await talents.list_talents()


@pytest.mark.anyio
async def test_import_profile_duplicate_name_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)
    await _create_talent(talents, name="重名人才")
    await _create_talent(talents, name="重名人才")

    with pytest.raises(ToolError, match="改用 talent_update"):
        await talents.import_profile(name="重名人才", phone="13800001111")


@pytest.mark.anyio
async def test_import_profile_invalid_item_rolls_back_everything(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """第 K 条子项校验失败时整体不入库：人才与已通过的子项都不落库，错误文案带条目序号。"""
    talents = TalentsTalentTools(session_factory)
    async with session_factory() as session:
        with pytest.raises(InvalidProfileImportError, match="第 2 条履历——结束日期不能早于开始日期"):
            await TalentsService(session).import_profile(
                {
                    "name": "失败导入",
                    "tags": ["设计"],
                    "experiences": [
                        {"company": "远山设计", "title": "视觉设计师", "start_on": "2023-03-01"},
                        {
                            "company": "坏日期公司",
                            "title": "实习生",
                            "start_on": "2024-01-01",
                            "end_on": "2023-01-01",
                        },
                    ],
                    "educations": [{"school": "中央美术学院", "start_on": "2016-09-01"}],
                }
            )

    assert "没有找到符合条件的人才" in await talents.list_talents()


@pytest.mark.anyio
async def test_import_profile_rate_pair_validation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    talents = TalentsTalentTools(session_factory)

    with pytest.raises(ToolError, match="费率金额与单位必须同时填写或同时留空"):
        await talents.import_profile(name="半费率人才", rate_amount=Decimal("500.00"))
    assert "没有找到符合条件的人才" in await talents.list_talents()


@pytest.mark.anyio
async def test_tools_are_callable_over_mcp_protocol(session_factory: async_sessionmaker[AsyncSession]) -> None:
    mcp = create_agent_mcp_server(session_factory, token="test-token")

    async with Client(mcp) as client:
        tools = await client.list_tools()
        talent_tool_names = {tool.name for tool in tools if tool.name.startswith("talent_")}
        assert talent_tool_names == EXPECTED_TALENT_TOOL_NAMES

        # 四个删除工具的 confirm_talent_name 在协议层为必填参数（缺参即被协议拒绝）
        delete_tools = [
            t
            for t in tools
            if t.name
            in {
                "talent_delete",
                "talent_interaction_delete",
                "talent_experience_delete",
                "talent_education_delete",
            }
        ]
        assert len(delete_tools) == 4
        for delete_tool in delete_tools:
            assert "confirm_talent_name" in delete_tool.input_schema.get("required", []), delete_tool.name

        # 批量导入工具的嵌套条目参数在协议层有完整 JSON Schema（spike 结论：list[pydantic] 可用）
        import_tool = next(t for t in tools if t.name == "talent_import_profile")
        item_schema = import_tool.input_schema["properties"]["experiences"]["anyOf"][0]["items"]
        assert {"company", "title", "start_on"} <= set(item_schema["properties"])

        created = await client.call_tool(
            "talent_create",
            {"name": "协议人才", "status": "接洽中", "tags": ["开发"]},
        )
        block = created.content[0]
        assert isinstance(block, TextContent)
        assert "已创建人才" in block.text and "协议人才" in block.text

        imported = await client.call_tool(
            "talent_import_profile",
            {
                "name": "协议导入人才",
                "tags": ["设计"],
                "experiences": [{"company": "远山设计", "title": "视觉设计师", "start_on": "2023-03-01"}],
            },
        )
        import_block = imported.content[0]
        assert isinstance(import_block, TextContent)
        assert "画像已创建" in import_block.text and "履历 1 条" in import_block.text

        listed = await client.call_tool("talent_list", {"query": "协议"})
        list_block = listed.content[0]
        assert isinstance(list_block, TextContent)
        assert "协议人才" in list_block.text and "协议导入人才" in list_block.text

        # 第 K 条子项非法：协议层拒绝且整体不入库
        with pytest.raises(ToolError):
            await client.call_tool(
                "talent_import_profile",
                {
                    "name": "协议失败导入",
                    "experiences": [
                        {"company": "远山设计", "title": "视觉设计师", "start_on": "2023-03-01"},
                        {"company": "坏日期公司", "title": "实习生", "start_on": "2024-01-01", "end_on": "2023-01-01"},
                    ],
                },
            )
        leftover = await client.call_tool("talent_list", {"query": "协议失败导入"})
        leftover_block = leftover.content[0]
        assert isinstance(leftover_block, TextContent)
        assert "没有找到符合条件的人才" in leftover_block.text
