"""Talents interactions MCP adapter: input conversion and Chinese output."""

from datetime import date
from typing import Annotated

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.talents_tool_support import (
    ConfirmTalentNameParam,
    InteractionChannelParam,
    InteractionIdParam,
    TalentIdParam,
    _collect_updates,
    _confirm_talent_name,
    _interaction_not_found,
    _mutation_errors,
    _plan_text,
    _talent_not_found,
    _validate,
)
from reven.talents.inputs import TalentInteractionCreate, TalentInteractionUpdate
from reven.talents.models import TalentInteraction
from reven.talents.repository import TalentPlan, TalentsRepository
from reven.talents.service import TalentsService


class TalentsInteractionTools:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_interactions(self, talent_id: TalentIdParam) -> str:
        """列出指定人才的全部互动（跟进）记录，按互动日期倒序。"""
        async with self._session_factory() as session:
            repository = TalentsRepository(session)
            talent = await repository.get_talent(talent_id)
            if talent is None:
                raise _talent_not_found(talent_id)
            interactions = await repository.list_interactions(talent_id)
        if not interactions:
            return f"人才「{talent.name}」暂无互动记录，可用 talent_interaction_create 记录一次接洽。"
        header = f"人才「{talent.name}」的互动记录（{len(interactions)}）："
        lines = [_interaction_line(index, interaction) for index, interaction in enumerate(interactions, 1)]
        return "\n".join([header, *lines])

    async def create_interaction(
        self,
        talent_id: TalentIdParam,
        channel: InteractionChannelParam,
        occurred_on: Annotated[date, Field(description="互动发生日期，格式 YYYY-MM-DD")],
        summary: Annotated[str | None, Field(description="互动内容纪要，如沟通要点")] = None,
        next_action: Annotated[str | None, Field(description="下一步行动，如：发送作品集、约二面")] = None,
        next_due_on: Annotated[date | None, Field(description="下次跟进日期，格式 YYYY-MM-DD")] = None,
    ) -> str:
        """为人才记录一次互动（跟进）：方式（电话/面谈/微信/邮件/其他）、日期、内容纪要，可选下一步计划。

        最新一条互动上的 next_action / next_due_on 即该人才的当前计划：记录后自动生效，无需额外同步。
        """
        payload = _validate(
            TalentInteractionCreate,
            {
                "occurred_on": occurred_on,
                "channel": channel,
                "summary": summary,
                "next_action": next_action,
                "next_due_on": next_due_on,
            },
        )
        with _mutation_errors():
            async with self._session_factory() as session:
                repository = TalentsRepository(session)
                talent = await repository.get_talent(talent_id)
                if talent is None:
                    raise _talent_not_found(talent_id)
                interaction = await TalentsService(session).create_interaction(talent, payload.model_dump())
                plan = await repository.get_talent_plan(talent_id)
        occurred = interaction.occurred_on.isoformat()
        text = f"已为人才「{talent.name}」记录 {occurred} 的{interaction.channel}互动（id={interaction.id}）。"
        if interaction.next_action or interaction.next_due_on:
            text += _plan_effect_text(plan, interaction)
        return text

    async def update_interaction(
        self,
        talent_id: TalentIdParam,
        interaction_id: InteractionIdParam,
        channel: InteractionChannelParam | None = None,
        occurred_on: Annotated[date | None, Field(description="新互动日期，格式 YYYY-MM-DD")] = None,
        summary: Annotated[str | None, Field(description="新互动内容纪要；传空字符串表示清空")] = None,
        next_action: Annotated[str | None, Field(description="新下一步行动；传空字符串表示清空")] = None,
        next_due_on: Annotated[date | None, Field(description="新下次跟进日期，格式 YYYY-MM-DD")] = None,
        clear_next_due_on: Annotated[bool, Field(description="为 true 时清除下次跟进日期")] = False,
    ) -> str:
        """修改一条互动（跟进）记录（部分更新，只传要改的字段）。

        若该记录是人才最新一条互动，修改其下一步行动/日期即更新人才的当前计划。
        """
        values = _collect_updates(
            {"channel": channel, "occurred_on": occurred_on, "summary": summary, "next_action": next_action},
            date_value=next_due_on,
            clear_date=clear_next_due_on,
            date_key="next_due_on",
        )
        payload = _validate(TalentInteractionUpdate, values)
        with _mutation_errors():
            async with self._session_factory() as session:
                repository = TalentsRepository(session)
                interaction = await repository.get_interaction(interaction_id)
                if interaction is None or interaction.talent_id != talent_id:
                    raise _interaction_not_found(interaction_id)
                updated = await TalentsService(session).update_interaction(
                    interaction, payload.model_dump(exclude_unset=True)
                )
        return f"已更新跟进记录：{_interaction_line(0, updated).removeprefix('0. ')}"

    async def delete_interaction(
        self,
        talent_id: TalentIdParam,
        interaction_id: InteractionIdParam,
        confirm_talent_name: ConfirmTalentNameParam,
    ) -> str:
        """删除一条互动（跟进）记录，不可恢复；若删除的是最新一条，人才当前计划回退到次新互动或为空。

        调用前必须与用户确认删除意图，并把所属人才名称逐字填入 confirm_talent_name。
        """
        with _mutation_errors():
            async with self._session_factory() as session:
                await _confirm_talent_name(session, talent_id, confirm_talent_name)
                repository = TalentsRepository(session)
                interaction = await repository.get_interaction(interaction_id)
                if interaction is None or interaction.talent_id != talent_id:
                    raise _interaction_not_found(interaction_id)
                label = f"{interaction.occurred_on.isoformat()} 的{interaction.channel}互动"
                await TalentsService(session).delete_interaction(interaction)
        return f"已删除{label}（id={interaction_id}）。"


def _plan_effect_text(plan: TalentPlan | None, interaction: TalentInteraction) -> str:
    """创建互动后的计划生效文案：派生计划取自最新一条互动，只有新记录真正给出派生值时才能声称已生效。"""
    if plan is not None and plan.next_action == interaction.next_action and plan.next_due_on == interaction.next_due_on:
        return f"下一步计划已自动生效为人才当前计划：{_plan_text(interaction.next_action, interaction.next_due_on)}。"
    current = _plan_text(plan.next_action, plan.next_due_on) if plan is not None else "未安排"
    return f"该记录早于最新互动，人才当前计划不变：{current}。"


def _interaction_line(index: int, interaction: TalentInteraction) -> str:
    head = f"{index}. {interaction.occurred_on.isoformat()} {interaction.channel}（id={interaction.id}）"
    if interaction.summary:
        head += f"：{interaction.summary}"
    parts = [head]
    if interaction.next_action or interaction.next_due_on:
        parts.append(f"下一步：{_plan_text(interaction.next_action, interaction.next_due_on)}")
    return "｜".join(parts)
