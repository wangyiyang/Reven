import pytest
from reven.agent.models import AgentApproval
from reven.agent.persistence_types import ApprovalStatus, canonical_arguments
from reven.agent.tool_catalog import TOOL_SPECS
from reven.agent.tool_definition import ToolDefinition
from reven.crm.models import Contact, Customer, FollowUp
from reven.rss.models import RssKeyword
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tool_execution_support import ToolRig
from tool_execution_support import tool_rig as tool_rig

WRITE_NAMES = [spec.name for spec in TOOL_SPECS if spec.is_write]
BUSINESS_MODELS = (
    Customer,
    Contact,
    FollowUp,
    Talent,
    TalentInteraction,
    TalentExperience,
    TalentEducation,
    RssKeyword,
)


async def _crm_inputs(rig: ToolRig) -> dict[str, dict[str, object]]:
    await rig.execute("crm_customer_create", {"name": "事务矩阵客户"}, "seed-customer")
    customer_id = str(await rig.entity_id("seed-customer"))
    contact: dict[str, object] = {"customer_id": customer_id, "name": "原联系人", "is_primary": True}
    await rig.execute("crm_contact_create", contact, "seed-contact")
    followup: dict[str, object] = {
        "customer_id": customer_id,
        "kind": "电话",
        "occurred_on": "2026-10-06",
        "summary": "原记录",
    }
    await rig.execute("crm_follow_up_create", followup, "seed-followup")
    contact_id, followup_id = str(await rig.entity_id("seed-contact")), str(await rig.entity_id("seed-followup"))
    confirmation: dict[str, object] = {"customer_id": customer_id, "confirm_customer_name": "事务矩阵客户"}
    return {
        "crm_customer_create": {"name": "新增客户"},
        "crm_customer_update": {"customer_id": customer_id, "notes": "新备注", "status": "跟进中"},
        "crm_customer_delete": confirmation,
        "crm_contact_create": {**contact, "name": "新增主联系人"},
        "crm_contact_update": {"customer_id": customer_id, "contact_id": contact_id, "is_primary": False},
        "crm_contact_delete": {**confirmation, "contact_id": contact_id},
        "crm_follow_up_create": {**followup, "summary": "新增记录"},
        "crm_follow_up_update": {"customer_id": customer_id, "follow_up_id": followup_id, "summary": "修订记录"},
        "crm_follow_up_delete": {**confirmation, "follow_up_id": followup_id},
    }


async def _talent_inputs(rig: ToolRig) -> dict[str, dict[str, object]]:
    await rig.execute("talent_create", {"name": "事务矩阵人才"}, "seed-talent")
    talent_id = str(await rig.entity_id("seed-talent"))
    interaction: dict[str, object] = {"talent_id": talent_id, "channel": "电话", "occurred_on": "2026-10-06"}
    experience: dict[str, object] = {
        "talent_id": talent_id,
        "company": "公司",
        "title": "设计师",
        "start_on": "2020-01-01",
    }
    education: dict[str, object] = {"talent_id": talent_id, "school": "大学", "start_on": "2016-09-01"}
    for name, args in [("interaction", interaction), ("experience", experience), ("education", education)]:
        await rig.execute(f"talent_{name}_create", args, f"seed-{name}")
    confirmation: dict[str, object] = {"talent_id": talent_id, "confirm_talent_name": "事务矩阵人才"}
    inputs: dict[str, dict[str, object]] = {
        "talent_create": {"name": "新增人才"},
        "talent_update": {"talent_id": talent_id, "tags": ["设计"], "organization": "新单位"},
        "talent_delete": confirmation,
        "talent_interaction_create": {**interaction, "summary": "新增互动"},
        "talent_experience_create": {**experience, "company": "新公司"},
        "talent_education_create": {**education, "school": "新大学"},
        "talent_import_profile": {
            "name": "事务矩阵人才",
            "notes": "更新画像",
            "experiences": [{"company": "导入公司", "title": "总监", "start_on": "2025-01-01"}],
            "educations": [{"school": "导入大学", "start_on": "2010-09-01"}],
        },
    }
    for name, changes in [
        ("interaction", {"summary": "修订互动"}),
        ("experience", {"title": "总监"}),
        ("education", {"major": "美术"}),
    ]:
        entity_id = str(await rig.entity_id(f"seed-{name}"))
        inputs[f"talent_{name}_update"] = {"talent_id": talent_id, f"{name}_id": entity_id, **changes}
        inputs[f"talent_{name}_delete"] = {**confirmation, f"{name}_id": entity_id}
    return inputs


async def _all_inputs(rig: ToolRig) -> dict[str, dict[str, object]]:
    inputs = {**await _crm_inputs(rig), **await _talent_inputs(rig)}
    await rig.execute("rss_keyword_create", {"term": "原关键词", "kind": "positive"}, "seed-keyword")
    keyword_id = str(await rig.entity_id("seed-keyword"))
    inputs.update(
        {
            "rss_keyword_create": {"term": "新增词", "kind": "positive"},
            "rss_keyword_update": {"keyword_id": keyword_id, "term": "新词", "kind": "negative", "enabled": False},
            "rss_keyword_delete": {"keyword_id": keyword_id},
        }
    )
    assert set(inputs) == set(WRITE_NAMES) and len(inputs) == 25
    return inputs


async def _snapshot(rig: ToolRig) -> dict[str, object]:
    tables: dict[str, object] = {}
    async with rig.factory() as session:
        for model in BUSINESS_MODELS:
            rows = list(await session.scalars(select(model).order_by(model.id)))
            tables[model.__tablename__] = [
                {column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows
            ]
    return canonical_arguments(tables)


@pytest.mark.anyio
@pytest.mark.parametrize("name", WRITE_NAMES)
async def test_all_25_writes_rollback_commit_and_replay_with_real_business_transaction(
    tool_rig: ToolRig, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = (await _all_inputs(tool_rig))[name]
    approval_id = (
        await tool_rig.approval(name, args, "mutation") if name in tool_rig.registry.confirmation_tools() else None
    )
    before = await _snapshot(tool_rig)
    original = ToolDefinition.invoke

    async def fail_before_ledger(
        self: ToolDefinition, arguments: dict[str, object], *, session: AsyncSession | None = None
    ):
        await original(self, arguments, session=session)
        raise RuntimeError("领域 mutation 已 flush，账本未写入")

    monkeypatch.setattr(ToolDefinition, "invoke", fail_before_ledger)
    with pytest.raises(RuntimeError, match="账本未写入"):
        await tool_rig.execute(name, args, "mutation")
    assert await _snapshot(tool_rig) == before
    assert await tool_rig.operation("mutation") is None
    monkeypatch.setattr(ToolDefinition, "invoke", original)
    result = await tool_rig.execute(name, args, "mutation")
    after = await _snapshot(tool_rig)
    assert after != before
    assert await tool_rig.execute(name, args, "mutation") == result
    assert await _snapshot(tool_rig) == after
    saved = await tool_rig.operation("mutation")
    assert saved is not None and saved.result["output"] == result
    assert saved.result["entities"]["records"]
    if approval_id is not None:
        async with tool_rig.factory() as session:
            approval = await session.get(AgentApproval, approval_id)
            assert approval is not None and approval.status == ApprovalStatus.CONSUMED
