"""Actual deletion targets, scoped row locks and immutable approval fingerprints."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from fastmcp.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from reven.agent.persistence_types import arguments_hash
from reven.crm.models import Contact, Customer, FollowUp
from reven.db import Base
from reven.rss.models import RssKeyword
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction


@dataclass(frozen=True, slots=True)
class ConfirmationTarget:
    summary: str
    fingerprint: str


async def confirmation_target(
    session: AsyncSession,
    tool_name: str,
    arguments: dict[str, object],
    *,
    lock: bool = False,
) -> ConfirmationTarget:
    if tool_name == "rss_keyword_delete":
        keyword = await _load(session, RssKeyword, arguments["keyword_id"], lock=lock)
        snapshot = {"id": str(keyword.id), "term": keyword.term, "kind": keyword.kind, "enabled": keyword.enabled}
        return ConfirmationTarget(
            f"删除 RSS 关键词「{keyword.term}」（id={keyword.id}，类型={keyword.kind}）；该关键词将不再参与筛选。",
            arguments_hash(snapshot),
        )
    if tool_name.startswith("crm_"):
        return await _customer_target(session, tool_name, arguments, lock=lock)
    if tool_name.startswith("talent_"):
        return await _talent_target(session, tool_name, arguments, lock=lock)
    raise ToolError("该工具没有删除确认策略")


async def _customer_target(
    session: AsyncSession, name: str, arguments: dict[str, object], *, lock: bool
) -> ConfirmationTarget:
    customer = await _load(session, Customer, arguments["customer_id"], lock=lock)
    if arguments.get("confirm_customer_name") != customer.name:
        raise ToolError("confirm_customer_name 与客户名称不完全一致，请重新核对目标")
    rows: list[Base] = [customer]
    owner = f"客户「{customer.name}」（id={customer.id}）"
    if name == "crm_customer_delete":
        contacts = await _rows(session, Contact, Contact.customer_id == customer.id, lock=lock)
        follow_ups = await _rows(session, FollowUp, FollowUp.customer_id == customer.id, lock=lock)
        rows.extend([*contacts, *follow_ups])
        summary = f"删除{owner}，一并删除 {len(contacts)} 个联系人、{len(follow_ups)} 条跟进记录；不可恢复。"
    elif name == "crm_contact_delete":
        contact = await _load(session, Contact, arguments["contact_id"], lock=lock)
        _require_owner(contact.customer_id, customer.id)
        follow_ups = await _rows(session, FollowUp, FollowUp.contact_id == contact.id, lock=lock)
        rows.extend([contact, *follow_ups])
        summary = (
            f"删除{owner}的联系人「{contact.name}」（id={contact.id}）；"
            f"{len(follow_ups)} 条关联跟进保留联系人姓名快照；不可恢复。"
        )
    elif name == "crm_follow_up_delete":
        follow_up = await _load(session, FollowUp, arguments["follow_up_id"], lock=lock)
        _require_owner(follow_up.customer_id, customer.id)
        rows.append(follow_up)
        summary = (
            f"删除{owner}的 {follow_up.occurred_on.isoformat()} {follow_up.kind}跟进（id={follow_up.id}）；"
            "若为最新跟进，当前计划回退到次新记录或清空；不可恢复。"
        )
    else:
        raise ToolError("该工具没有删除确认策略")
    return _target(summary, rows)


async def _talent_target(
    session: AsyncSession, name: str, arguments: dict[str, object], *, lock: bool
) -> ConfirmationTarget:
    talent = await _load(session, Talent, arguments["talent_id"], lock=lock)
    if arguments.get("confirm_talent_name") != talent.name:
        raise ToolError("confirm_talent_name 与人才名称不完全一致，请重新核对目标")
    rows: list[Base] = [talent]
    owner = f"人才「{talent.name}」（id={talent.id}）"
    if name == "talent_delete":
        interactions = await _rows(session, TalentInteraction, TalentInteraction.talent_id == talent.id, lock=lock)
        experiences = await _rows(session, TalentExperience, TalentExperience.talent_id == talent.id, lock=lock)
        educations = await _rows(session, TalentEducation, TalentEducation.talent_id == talent.id, lock=lock)
        rows.extend([*interactions, *experiences, *educations])
        summary = (
            f"删除{owner}，一并删除 {len(interactions)} 条互动、{len(experiences)} 条履历、"
            f"{len(educations)} 条院校经历；不可恢复。"
        )
    else:
        summary, child = await _talent_child(session, name, arguments, talent, lock=lock)
        rows.append(child)
    return _target(summary, rows)


async def _talent_child(
    session: AsyncSession, name: str, arguments: dict[str, object], talent: Talent, *, lock: bool
) -> tuple[str, Base]:
    owner = f"人才「{talent.name}」（id={talent.id}）"
    if name == "talent_interaction_delete":
        interaction = await _load(session, TalentInteraction, arguments["interaction_id"], lock=lock)
        _require_owner(interaction.talent_id, talent.id)
        return (
            f"删除{owner}的 {interaction.occurred_on.isoformat()} {interaction.channel}互动（id={interaction.id}）；"
            "若为最新互动，当前计划回退到次新记录或清空；不可恢复。",
            interaction,
        )
    if name == "talent_experience_delete":
        experience = await _load(session, TalentExperience, arguments["experience_id"], lock=lock)
        _require_owner(experience.talent_id, talent.id)
        return (
            f"删除{owner}的履历「{experience.company}·{experience.title}」（id={experience.id}）；不可恢复。",
            experience,
        )
    if name == "talent_education_delete":
        education = await _load(session, TalentEducation, arguments["education_id"], lock=lock)
        _require_owner(education.talent_id, talent.id)
        return f"删除{owner}的院校经历「{education.school}」（id={education.id}）；不可恢复。", education
    raise ToolError("该工具没有删除确认策略")


async def _load[ModelT: Base](session: AsyncSession, model: type[ModelT], entity_id: object, *, lock: bool) -> ModelT:
    row = await session.get(model, UUID(str(entity_id)), with_for_update=lock)
    if row is None:
        raise ToolError("删除目标不存在，请重新查询后发起操作")
    return row


async def _rows[ModelT: Base](
    session: AsyncSession, model: type[ModelT], condition: ColumnElement[bool], *, lock: bool
) -> list[ModelT]:
    query = select(model).where(condition).order_by(getattr(model, "id"))
    if lock:
        query = query.with_for_update()
    return list(await session.scalars(query))


def _require_owner(actual: UUID, expected: UUID) -> None:
    if actual != expected:
        raise ToolError("删除目标不存在或不属于所选客户/人才")


def _target(summary: str, rows: list[Base]) -> ConfirmationTarget:
    snapshots = [
        {"table": row.__tablename__, **{column.name: getattr(row, column.name) for column in row.__table__.columns}}
        for row in rows
    ]
    return ConfirmationTarget(summary, arguments_hash(cast(dict[str, object], {"records": snapshots})))
