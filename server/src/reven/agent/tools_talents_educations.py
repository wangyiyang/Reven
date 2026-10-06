"""Talents educations MCP adapter: input conversion and Chinese output."""

from datetime import date
from typing import Annotated

from pydantic import Field

from reven.agent.talents_tool_support import (
    ConfirmTalentNameParam,
    EducationIdParam,
    TalentIdParam,
    _collect_updates,
    _confirm_talent_name,
    _education_not_found,
    _mutation_errors,
    _period_text,
    _talent_not_found,
    _validate,
)
from reven.agent.tool_binding import ToolSessionBinding
from reven.talents.inputs import TalentEducationCreate, TalentEducationUpdate
from reven.talents.models import TalentEducation
from reven.talents.repository import TalentsRepository
from reven.talents.service import TalentsService


class TalentsEducationTools(ToolSessionBinding):
    async def list_educations(self, talent_id: TalentIdParam) -> str:
        """列出指定人才的全部院校经历，在读（至今）的排最前，其余按开始日期倒序。"""
        async with self._session() as session:
            repository = TalentsRepository(session)
            talent = await repository.get_talent(talent_id)
            if talent is None:
                raise _talent_not_found(talent_id)
            educations = await repository.list_educations(talent_id)
        if not educations:
            return f"人才「{talent.name}」暂无院校经历，可用 talent_education_create 添加。"
        header = f"人才「{talent.name}」的院校经历（{len(educations)}）："
        lines = [_education_line(index, education) for index, education in enumerate(educations, 1)]
        return "\n".join([header, *lines])

    async def create_education(
        self,
        talent_id: TalentIdParam,
        school: Annotated[str, Field(description="学校名称（必填）")],
        start_on: Annotated[
            date,
            Field(description="入学日期，格式 YYYY-MM-DD（院校经历只精确到月，日补 01，如 2016-09-01）"),
        ],
        degree: Annotated[str | None, Field(description="学位，如：本科、硕士、博士")] = None,
        major: Annotated[str | None, Field(description="专业，如：视觉传达")] = None,
        end_on: Annotated[
            date | None,
            Field(description="毕业日期，格式 YYYY-MM-DD（月精度补 01）；在读则不传，表示至今"),
        ] = None,
    ) -> str:
        """为人才添加一条院校经历。毕业日期必须不早于入学日期；添加院校经历不影响人才的当前跟进计划。"""
        payload = _validate(
            TalentEducationCreate,
            {
                "school": school,
                "degree": degree,
                "major": major,
                "start_on": start_on,
                "end_on": end_on,
            },
        )
        with _mutation_errors():
            async with self._session() as session:
                repository = TalentsRepository(session)
                talent = await repository.get_talent(talent_id)
                if talent is None:
                    raise _talent_not_found(talent_id)
                education = await TalentsService(session, commit=self._commits).create_education(
                    talent, payload.model_dump()
                )
                self._record_entity(education)
        return f"已为人才「{talent.name}」添加院校经历：{_education_line(0, education).removeprefix('0. ')}"

    async def update_education(
        self,
        talent_id: TalentIdParam,
        education_id: EducationIdParam,
        school: Annotated[str | None, Field(description="新学校名称；不传则不修改")] = None,
        degree: Annotated[str | None, Field(description="新学位；传空字符串表示清空")] = None,
        major: Annotated[str | None, Field(description="新专业；传空字符串表示清空")] = None,
        start_on: Annotated[date | None, Field(description="新入学日期，格式 YYYY-MM-DD（月精度补 01）")] = None,
        end_on: Annotated[date | None, Field(description="新毕业日期，格式 YYYY-MM-DD（月精度补 01）")] = None,
        clear_end_on: Annotated[bool, Field(description="为 true 时清除毕业日期，表示至今在读")] = False,
    ) -> str:
        """修改一条院校经历（部分更新，只传要改的字段）。毕业日期与现值合并校验，必须不早于入学日期。"""
        values = _collect_updates(
            {"school": school, "degree": degree, "major": major, "start_on": start_on},
            date_value=end_on,
            clear_date=clear_end_on,
            date_key="end_on",
        )
        payload = _validate(TalentEducationUpdate, values)
        with _mutation_errors():
            async with self._session() as session:
                repository = TalentsRepository(session)
                education = await repository.get_education(talent_id, education_id)
                if education is None:
                    raise _education_not_found(education_id)
                updated = await TalentsService(session, commit=self._commits).update_education(
                    education, payload.model_dump(exclude_unset=True)
                )
                self._record_entity(updated)
        return f"已更新院校经历：{_education_line(0, updated).removeprefix('0. ')}"

    async def delete_education(
        self,
        talent_id: TalentIdParam,
        education_id: EducationIdParam,
        confirm_talent_name: ConfirmTalentNameParam,
    ) -> str:
        """删除一条院校经历，不可恢复。

        调用前必须与用户确认删除意图，并把所属人才名称逐字填入 confirm_talent_name。
        """
        with _mutation_errors():
            async with self._session() as session:
                await _confirm_talent_name(session, talent_id, confirm_talent_name)
                repository = TalentsRepository(session)
                education = await repository.get_education(talent_id, education_id)
                if education is None:
                    raise _education_not_found(education_id)
                label = education.school
                await TalentsService(session, commit=self._commits).delete_education(education)
                self._record_entity(education)
        return f"已删除院校经历「{label}」（id={education_id}）。"


def _education_line(index: int, education: TalentEducation) -> str:
    title_parts = [education.school]
    if education.degree:
        title_parts.append(education.degree)
    if education.major:
        title_parts.append(education.major)
    period = _period_text(education.start_on, education.end_on)
    return f"{index}. {'·'.join(title_parts)}（id={education.id}，{period}）"
