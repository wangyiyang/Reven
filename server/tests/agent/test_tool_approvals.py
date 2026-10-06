from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import ToolError
from reven.agent.models import AgentApproval
from reven.agent.persistence_types import ApprovalStatus
from reven.agent.tool_errors import AgentToolApprovalError, AgentToolContextError
from reven.crm.models import Contact, Customer, FollowUp
from reven.rss.models import RssKeyword
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from tool_execution_support import ToolRig
from tool_execution_support import tool_rig as tool_rig

DELETE_TOOLS = (
    "rss_keyword_delete",
    "crm_customer_delete",
    "crm_contact_delete",
    "crm_follow_up_delete",
    "talent_delete",
    "talent_interaction_delete",
    "talent_experience_delete",
    "talent_education_delete",
)


@dataclass(frozen=True)
class DeleteCase:
    name: str
    args: dict[str, object]
    model: Any
    entity_id: UUID


async def _seed_customer(rig: ToolRig, name: str) -> DeleteCase:
    await rig.execute("crm_customer_create", {"name": "客户甲"}, "customer")
    customer_id = str(await rig.entity_id("customer"))
    await rig.execute("crm_contact_create", {"customer_id": customer_id, "name": "联系人乙"}, "contact")
    contact_id = str(await rig.entity_id("contact"))
    await rig.execute(
        "crm_follow_up_create",
        {
            "customer_id": customer_id,
            "contact_id": contact_id,
            "kind": "电话",
            "occurred_on": "2026-10-06",
            "summary": "核对需求",
        },
        "followup",
    )
    args: dict[str, object] = {"customer_id": customer_id, "confirm_customer_name": "客户甲"}
    if name == "crm_customer_delete":
        return DeleteCase(name, args, Customer, UUID(customer_id))
    if name == "crm_contact_delete":
        return DeleteCase(name, {**args, "contact_id": contact_id}, Contact, UUID(contact_id))
    followup_id = await rig.entity_id("followup")
    return DeleteCase(name, {**args, "follow_up_id": str(followup_id)}, FollowUp, followup_id)


async def _seed_talent(rig: ToolRig, name: str) -> DeleteCase:
    await rig.execute("talent_create", {"name": "人才丙"}, "talent")
    talent_id = str(await rig.entity_id("talent"))
    await rig.execute(
        "talent_interaction_create",
        {"talent_id": talent_id, "channel": "面谈", "occurred_on": "2026-10-06"},
        "interaction",
    )
    await rig.execute(
        "talent_experience_create",
        {"talent_id": talent_id, "company": "设计公司", "title": "设计师", "start_on": "2023-01-01"},
        "experience",
    )
    await rig.execute(
        "talent_education_create", {"talent_id": talent_id, "school": "设计学院", "start_on": "2018-09-01"}, "education"
    )
    args: dict[str, object] = {"talent_id": talent_id, "confirm_talent_name": "人才丙"}
    if name == "talent_delete":
        return DeleteCase(name, args, Talent, UUID(talent_id))
    suffix = name.removeprefix("talent_").removesuffix("_delete")
    entity_id = await rig.entity_id(suffix)
    models = {"interaction": TalentInteraction, "experience": TalentExperience, "education": TalentEducation}
    return DeleteCase(name, {**args, f"{suffix}_id": str(entity_id)}, models[suffix], entity_id)


async def seed_delete_case(rig: ToolRig, name: str) -> DeleteCase:
    if name == "rss_keyword_delete":
        await rig.execute("rss_keyword_create", {"term": "产业关键词", "kind": "positive"}, "keyword")
        entity_id = await rig.entity_id("keyword")
        return DeleteCase(name, {"keyword_id": str(entity_id)}, RssKeyword, entity_id)
    if name.startswith("crm_"):
        return await _seed_customer(rig, name)
    return await _seed_talent(rig, name)


@pytest.mark.anyio
@pytest.mark.parametrize("name", DELETE_TOOLS)
@pytest.mark.parametrize("status", [None, ApprovalStatus.PENDING, ApprovalStatus.REJECTED, ApprovalStatus.APPROVED])
async def test_all_eight_deletes_require_host_approval_and_consume_once(
    tool_rig: ToolRig, name: str, status: ApprovalStatus | None
) -> None:
    case = await seed_delete_case(tool_rig, name)
    approval_id = await tool_rig.approval(name, case.args, "delete", status=status) if status is not None else None
    if status == ApprovalStatus.APPROVED:
        result = await tool_rig.execute(name, case.args, "delete")
        assert await tool_rig.execute(name, case.args, "delete") == result
        operation = await tool_rig.operation("delete")
        assert operation is not None and operation.result["output"] == result
    else:
        with pytest.raises(AgentToolApprovalError):
            await tool_rig.execute(name, case.args, "delete")
        assert await tool_rig.operation("delete") is None
    async with tool_rig.factory() as session:
        target = await session.get(case.model, case.entity_id)
        assert (target is None) == (status == ApprovalStatus.APPROVED)
        if approval_id is not None:
            approval = await session.get(AgentApproval, approval_id)
            assert approval is not None
            assert approval.status == (ApprovalStatus.CONSUMED if status == ApprovalStatus.APPROVED else status)
            assert (approval.consumed_at is not None) == (status == ApprovalStatus.APPROVED)


@pytest.mark.anyio
async def test_approved_delete_is_bound_to_original_actor_session_and_arguments(tool_rig: ToolRig) -> None:
    case = await seed_delete_case(tool_rig, "crm_customer_delete")
    approval_id = await tool_rig.approval(case.name, case.args, "delete")
    for context in [replace(tool_rig.context, owner_id="other"), replace(tool_rig.context, session_id=uuid4())]:
        with pytest.raises(AgentToolContextError):
            await tool_rig.registry.execute(case.name, case.args, context, "delete")
    with pytest.raises(AgentToolApprovalError):
        await tool_rig.execute(case.name, {**case.args, "confirm_customer_name": "其他客户"}, "delete")
    with pytest.raises(AgentToolApprovalError):
        await tool_rig.execute(case.name, case.args, "different-call")
    async with tool_rig.factory() as session:
        assert await session.get(Customer, case.entity_id) is not None
        approval = await session.get(AgentApproval, approval_id)
        assert approval is not None and approval.status == ApprovalStatus.APPROVED


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["rss_keyword_delete", "crm_customer_delete", "talent_delete"])
async def test_actual_target_change_invalidates_existing_approval(tool_rig: ToolRig, name: str) -> None:
    case = await seed_delete_case(tool_rig, name)
    approval_id = await tool_rig.approval(name, case.args, "delete")
    async with tool_rig.factory() as session, session.begin():
        row = await session.get(case.model, case.entity_id)
        assert row is not None
        if isinstance(row, RssKeyword):
            row.term = "审批后变化的词"
        else:
            row.name = "审批后变化的姓名"
    with pytest.raises(AgentToolApprovalError):
        await tool_rig.execute(name, case.args, "delete")
    async with tool_rig.factory() as session:
        assert await session.get(case.model, case.entity_id) is not None
        approval = await session.get(AgentApproval, approval_id)
        assert approval is not None and approval.status == ApprovalStatus.APPROVED


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["crm_customer_delete", "talent_delete"])
async def test_cascade_child_change_invalidates_approval(tool_rig: ToolRig, name: str) -> None:
    case = await seed_delete_case(tool_rig, name)
    approval_id = await tool_rig.approval(name, case.args, "delete")
    if name == "crm_customer_delete":
        await tool_rig.execute(
            "crm_contact_create", {"customer_id": str(case.entity_id), "name": "新联系人"}, "new-child"
        )
    else:
        await tool_rig.execute(
            "talent_experience_create",
            {"talent_id": str(case.entity_id), "company": "新公司", "title": "总监", "start_on": "2026-01-01"},
            "new-child",
        )
    with pytest.raises(AgentToolApprovalError):
        await tool_rig.execute(name, case.args, "delete")
    async with tool_rig.factory() as session:
        assert await session.get(case.model, case.entity_id) is not None
        approval = await session.get(AgentApproval, approval_id)
        assert approval is not None and approval.status == ApprovalStatus.APPROVED


@pytest.mark.anyio
async def test_confirmation_summary_uses_actual_targets_and_cascade_counts(tool_rig: ToolRig) -> None:
    case = await seed_delete_case(tool_rig, "talent_delete")
    target = await tool_rig.registry.confirmation_target(case.name, case.args)
    assert f"人才「人才丙」（id={case.entity_id}）" in target.summary
    assert "1 条互动、1 条履历、1 条院校经历" in target.summary
    assert target.fingerprint not in target.summary
    case = replace(
        case,
        name="talent_experience_delete",
        args={**case.args, "talent_id": str(uuid4()), "experience_id": str(await tool_rig.entity_id("experience"))},
    )
    with pytest.raises(ToolError):
        await tool_rig.registry.confirmation_target(case.name, case.args)


@pytest.mark.anyio
async def test_approval_consumption_rolls_back_when_domain_delete_fails(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reven.agent.tool_definition import ToolDefinition

    case = await seed_delete_case(tool_rig, "crm_customer_delete")
    approval_id = await tool_rig.approval(case.name, case.args, "delete")
    original = ToolDefinition.invoke

    async def fail_after_delete(self: ToolDefinition, args: dict[str, object], *, session=None):
        await original(self, args, session=session)
        raise RuntimeError("删除后账本前故障")

    monkeypatch.setattr(ToolDefinition, "invoke", fail_after_delete)
    with pytest.raises(RuntimeError, match="账本前"):
        await tool_rig.execute(case.name, case.args, "delete")
    assert await tool_rig.operation("delete") is None
    async with tool_rig.factory() as session:
        assert await session.get(Customer, case.entity_id) is not None
        assert await session.scalar(select(Contact).where(Contact.customer_id == case.entity_id)) is not None
        assert await session.scalar(select(FollowUp).where(FollowUp.customer_id == case.entity_id)) is not None
        approval = await session.get(AgentApproval, approval_id)
        assert approval is not None and approval.status == ApprovalStatus.APPROVED and approval.consumed_at is None


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["crm_customer_delete", "talent_delete"])
async def test_locked_confirmation_parent_blocks_new_cascade_child_until_transaction_ends(
    tool_rig: ToolRig, name: str
) -> None:
    from reven.agent.tool_confirmations import confirmation_target

    case = await seed_delete_case(tool_rig, name)
    normalized = tool_rig.registry.canonical_tool_arguments(name, case.args)
    async with tool_rig.factory() as locked, locked.begin():
        await confirmation_target(locked, name, normalized, lock=True)
        async with tool_rig.factory() as concurrent, concurrent.begin():
            await concurrent.execute(text("SET LOCAL lock_timeout = '100ms'"))
            if name == "crm_customer_delete":
                concurrent.add(Contact(customer_id=case.entity_id, name="批准期间新增联系人"))
            else:
                concurrent.add(
                    TalentInteraction(talent_id=case.entity_id, channel="电话", occurred_on=date(2026, 10, 6))
                )
            with pytest.raises(DBAPIError) as caught:
                await concurrent.flush()
            assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
