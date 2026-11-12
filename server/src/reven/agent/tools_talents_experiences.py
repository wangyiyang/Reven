"""Talents experiences MCP adapter: input conversion and Chinese output."""

from datetime import date
from typing import Annotated

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.talents_tool_support import (
    ConfirmTalentNameParam,
    ExperienceIdParam,
    TalentIdParam,
    _collect_updates,
    _confirm_talent_name,
    _experience_not_found,
    _mutation_errors,
    _period_text,
    _talent_not_found,
    _validate,
)
from reven.talents.inputs import TalentExperienceCreate, TalentExperienceUpdate
from reven.talents.models import TalentExperience
from reven.talents.repository import TalentsRepository
from reven.talents.service import TalentsService


class TalentsExperienceTools:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_experiences(self, talent_id: TalentIdParam) -> str:
        """列出指定人才的全部工作履历，在职（至今）的排最前，其余按开始日期倒序。"""
        async with self._session_factory() as session:
            repository = TalentsRepository(session)
            talent = await repository.get_talent(talent_id)
            if talent is None:
                raise _talent_not_found(talent_id)
            experiences = await repository.list_experiences(talent_id)
        if not experiences:
            return f"人才「{talent.name}」暂无履历，可用 talent_experience_create 添加。"
        header = f"人才「{talent.name}」的履历（{len(experiences)}）："
        lines = [_experience_line(index, experience) for index, experience in enumerate(experiences, 1)]
        return "\n".join([header, *lines])

    async def create_experience(
        self,
        talent_id: TalentIdParam,
        company: Annotated[str, Field(description="公司/组织名称（必填）")],
        title: Annotated[str, Field(description="职位/角色（必填）")],
        start_on: Annotated[
            date,
            Field(description="开始日期，格式 YYYY-MM-DD（履历只精确到月，日补 01，如 2023-03-01）"),
        ],
        end_on: Annotated[
            date | None,
            Field(description="结束日期，格式 YYYY-MM-DD（月精度补 01）；在职则不传，表示至今"),
        ] = None,
        description: Annotated[str | None, Field(description="工作内容描述")] = None,
    ) -> str:
        """为人才添加一条工作履历。结束日期必须不早于开始日期；添加履历不影响人才的当前跟进计划。"""
        payload = _validate(
            TalentExperienceCreate,
            {
                "company": company,
                "title": title,
                "description": description,
                "start_on": start_on,
                "end_on": end_on,
            },
        )
        with _mutation_errors():
            async with self._session_factory() as session:
                repository = TalentsRepository(session)
                talent = await repository.get_talent(talent_id)
                if talent is None:
                    raise _talent_not_found(talent_id)
                experience = await TalentsService(session).create_experience(talent, payload.model_dump())
        return f"已为人才「{talent.name}」添加履历：{_experience_line(0, experience).removeprefix('0. ')}"

    async def update_experience(
        self,
        talent_id: TalentIdParam,
        experience_id: ExperienceIdParam,
        company: Annotated[str | None, Field(description="新公司/组织名称；不传则不修改")] = None,
        title: Annotated[str | None, Field(description="新职位/角色；不传则不修改")] = None,
        description: Annotated[str | None, Field(description="新工作内容描述；传空字符串表示清空")] = None,
        start_on: Annotated[date | None, Field(description="新开始日期，格式 YYYY-MM-DD（月精度补 01）")] = None,
        end_on: Annotated[date | None, Field(description="新结束日期，格式 YYYY-MM-DD（月精度补 01）")] = None,
        clear_end_on: Annotated[bool, Field(description="为 true 时清除结束日期，表示至今在职")] = False,
    ) -> str:
        """修改一条履历（部分更新，只传要改的字段）。结束日期与现值合并校验，必须不早于开始日期。"""
        values = _collect_updates(
            {"company": company, "title": title, "description": description, "start_on": start_on},
            date_value=end_on,
            clear_date=clear_end_on,
            date_key="end_on",
        )
        payload = _validate(TalentExperienceUpdate, values)
        with _mutation_errors():
            async with self._session_factory() as session:
                repository = TalentsRepository(session)
                experience = await repository.get_experience(talent_id, experience_id)
                if experience is None:
                    raise _experience_not_found(experience_id)
                updated = await TalentsService(session).update_experience(
                    experience, payload.model_dump(exclude_unset=True)
                )
        return f"已更新履历：{_experience_line(0, updated).removeprefix('0. ')}"

    async def delete_experience(
        self,
        talent_id: TalentIdParam,
        experience_id: ExperienceIdParam,
        confirm_talent_name: ConfirmTalentNameParam,
    ) -> str:
        """删除一条履历，不可恢复。

        调用前必须与用户确认删除意图，并把所属人才名称逐字填入 confirm_talent_name。
        """
        with _mutation_errors():
            async with self._session_factory() as session:
                await _confirm_talent_name(session, talent_id, confirm_talent_name)
                repository = TalentsRepository(session)
                experience = await repository.get_experience(talent_id, experience_id)
                if experience is None:
                    raise _experience_not_found(experience_id)
                label = f"{experience.company}·{experience.title}"
                await TalentsService(session).delete_experience(experience)
        return f"已删除履历「{label}」（id={experience_id}）。"


def _experience_line(index: int, experience: TalentExperience) -> str:
    period = _period_text(experience.start_on, experience.end_on)
    head = f"{index}. {experience.company}·{experience.title}（id={experience.id}，{period}）"
    if experience.description:
        head += f"：{experience.description}"
    return head
