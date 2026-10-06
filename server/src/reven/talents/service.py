"""Transactional talents mutations and business invariants."""

from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.scheduling import utc_now
from reven.talents.errors import (
    DuplicateTalentNameError,
    InvalidDateRangeError,
    InvalidProfileImportError,
    InvalidRatePairError,
)
from reven.talents.inputs import TalentProfileImport
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction
from reven.talents.repository import TalentsRepository

TalentModel = Talent | TalentInteraction | TalentExperience | TalentEducation

__all__ = [
    "DuplicateTalentNameError",
    "InvalidDateRangeError",
    "InvalidProfileImportError",
    "InvalidRatePairError",
    "TalentImportResult",
    "TalentsService",
]

_IMPORT_FIELD_LABELS = {
    "name": "姓名",
    "organization": "当前单位",
    "tags": "能力/行业标签",
    "phone": "电话",
    "email": "邮箱",
    "wechat": "微信",
    "preferences": "喜好",
    "capability": "能力描述",
    "engagement_terms": "合作条件",
    "availability": "可用时间",
    "rate_amount": "费率金额",
    "rate_unit": "费率单位",
    "rating": "评分",
    "status": "人才状态",
    "notes": "备注",
    "company": "公司",
    "title": "职位",
    "description": "描述",
    "start_on": "开始日期",
    "end_on": "结束日期",
    "school": "学校",
    "degree": "学位",
    "major": "专业",
}


@dataclass(frozen=True)
class TalentImportResult:
    """import_profile 的写入结果：目标人才、是否新建、追加的履历/院校条数。"""

    talent: Talent
    created: bool
    experiences: int
    educations: int


class TalentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TalentsRepository(session)

    async def create_talent(self, values: dict[str, object]) -> Talent:
        talent = await self.repository.add_talent(values)
        await self._commit_and_refresh(talent)
        return talent

    async def update_talent(self, talent: Talent, values: dict[str, object]) -> Talent:
        amount = values.get("rate_amount", talent.rate_amount)
        unit = values.get("rate_unit", talent.rate_unit)
        if (amount is None) != (unit is None):
            raise InvalidRatePairError
        _assign(talent, values)
        await self._commit_and_refresh(talent)
        return talent

    async def delete_talent(self, talent: Talent) -> None:
        await self.session.delete(talent)
        await self.session.commit()

    async def create_interaction(self, talent: Talent, values: dict[str, object]) -> TalentInteraction:
        interaction = await self.repository.add_interaction(talent.id, values)
        talent.updated_at = utc_now()
        await self._commit_and_refresh(interaction)
        return interaction

    async def update_interaction(
        self,
        interaction: TalentInteraction,
        values: dict[str, object],
    ) -> TalentInteraction:
        _assign(interaction, values)
        await self._commit_and_refresh(interaction)
        return interaction

    async def delete_interaction(self, interaction: TalentInteraction) -> None:
        talent = await self.repository.get_talent(interaction.talent_id)
        if talent is not None:
            talent.updated_at = utc_now()
        await self.session.delete(interaction)
        await self.session.commit()

    # 履历/院校修订不等于接洽活跃：写操作均不 bump talent.updated_at（与 CRM 一致）。

    async def create_experience(self, talent: Talent, values: dict[str, object]) -> TalentExperience:
        experience = await self.repository.add_experience(talent.id, values)
        await self._commit_and_refresh(experience)
        return experience

    async def update_experience(
        self,
        experience: TalentExperience,
        values: dict[str, object],
    ) -> TalentExperience:
        _validate_date_range(experience.start_on, experience.end_on, values)
        _assign(experience, values)
        await self._commit_and_refresh(experience)
        return experience

    async def delete_experience(self, experience: TalentExperience) -> None:
        await self.session.delete(experience)
        await self.session.commit()

    async def create_education(self, talent: Talent, values: dict[str, object]) -> TalentEducation:
        education = await self.repository.add_education(talent.id, values)
        await self._commit_and_refresh(education)
        return education

    async def update_education(
        self,
        education: TalentEducation,
        values: dict[str, object],
    ) -> TalentEducation:
        _validate_date_range(education.start_on, education.end_on, values)
        _assign(education, values)
        await self._commit_and_refresh(education)
        return education

    async def delete_education(self, education: TalentEducation) -> None:
        await self.session.delete(education)
        await self.session.commit()

    async def import_profile(self, values: dict[str, object]) -> TalentImportResult:
        """粘贴简介批量落库：全部校验先行（零写入）→ 连续 flush → 单次 commit（任一失败全回滚）。

        按 name 精确匹配已有人才：0 个 → 新建人才并写入全部子项；1 个 → 仅更新提交的画像字段、
        追加履历/院校（不去重）；≥2 个同名 → DuplicateTalentNameError（不猜，交由调用方改用按 ID 更新）。
        """
        payload = _validate_profile_import(values)
        matches = await self.repository.find_talents_by_name(payload.name)
        if len(matches) > 1:
            raise DuplicateTalentNameError(payload.name)
        if matches:
            talent = matches[0]
            profile_values = payload.model_dump(exclude={"experiences", "educations"}, exclude_unset=True)
            amount = profile_values.get("rate_amount", talent.rate_amount)
            unit = profile_values.get("rate_unit", talent.rate_unit)
            if (amount is None) != (unit is None):
                raise InvalidRatePairError
            _assign(talent, profile_values)
            created = False
        else:
            talent = await self.repository.add_talent(payload.model_dump(exclude={"experiences", "educations"}))
            created = True
        for experience in payload.experiences:
            await self.repository.add_experience(talent.id, experience.model_dump())
        for education in payload.educations:
            await self.repository.add_education(talent.id, education.model_dump())
        await self.session.commit()
        await self.session.refresh(talent)
        return TalentImportResult(
            talent=talent,
            created=created,
            experiences=len(payload.experiences),
            educations=len(payload.educations),
        )

    async def _commit_and_refresh(self, model: TalentModel) -> None:
        await self.session.commit()
        await self.session.refresh(model)


def _validate_profile_import(values: dict[str, object]) -> TalentProfileImport:
    """校验批量导入载荷；错误明细带条目序号（第 N 条履历/院校经历）与字段中文名。"""
    try:
        return TalentProfileImport.model_validate(values)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            loc = error["loc"]
            message = error["msg"]
            if message.startswith("Value error, "):
                message = message[len("Value error, ") :]
            prefix = ""
            if len(loc) > 1 and isinstance(loc[1], int) and loc[0] in ("experiences", "educations"):
                noun = "履历" if loc[0] == "experiences" else "院校经历"
                prefix = f"第 {loc[1] + 1} 条{noun}——"
                loc = loc[2:]
            field = ".".join(str(part) for part in loc)
            label = _IMPORT_FIELD_LABELS.get(field, field)
            detail = f"{label}：{message}" if label else message
            messages.append(f"{prefix}{detail}")
        raise InvalidProfileImportError("导入参数校验未通过——" + "；".join(messages)) from exc


def _assign(model: TalentModel, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _validate_date_range(current_start: date, current_end: date | None, values: dict[str, object]) -> None:
    """PATCH 合并语义：未提交字段取现值后校验最终区间（单边提交只能在 service 判）。"""
    start = values.get("start_on", current_start)
    end = values.get("end_on", current_end)
    if isinstance(start, date) and isinstance(end, date) and end < start:
        raise InvalidDateRangeError
