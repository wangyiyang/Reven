"""Shared talents MCP parameter conversion and transport error messages."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.scheduling import SHANGHAI
from reven.talents.errors import (
    DuplicateTalentNameError,
    InvalidDateRangeError,
    InvalidProfileImportError,
    InvalidRatePairError,
)
from reven.talents.models import InteractionChannel, RateUnit, TalentStatus
from reven.talents.repository import TalentsRepository

TalentIdParam = Annotated[UUID, Field(description="人才 ID（由 talent_list / talent_get 返回）")]
InteractionIdParam = Annotated[UUID, Field(description="跟进记录 ID（由 talent_interaction_list / talent_get 返回）")]
ExperienceIdParam = Annotated[UUID, Field(description="履历 ID（由 talent_experience_list / talent_get 返回）")]
EducationIdParam = Annotated[UUID, Field(description="院校经历 ID（由 talent_education_list / talent_get 返回）")]
TalentStatusParam = Annotated[
    TalentStatus,
    Field(description="人才状态：候选 / 接洽中 / 已合作 / 搁置"),
]
InteractionChannelParam = Annotated[
    InteractionChannel,
    Field(description="互动方式：电话 / 面谈 / 微信 / 邮件 / 其他"),
]
RateUnitParam = Annotated[
    RateUnit,
    Field(description="费率单位：按小时 / 按天 / 按项目；必须与费率金额同时填写"),
]
DueFilterParam = Annotated[
    Literal["overdue", "today", "upcoming", "none"],
    Field(description="跟进日期筛选：overdue=已逾期，today=今天到期，upcoming=未来到期，none=未安排跟进日期"),
]
ConfirmTalentNameParam = Annotated[
    str,
    Field(description="删除确认（必填）：逐字填写要删除实体所属人才的名称，与人才实际名称不完全相等时拒绝执行"),
]
_FIELD_LABELS = {
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
    "occurred_on": "互动日期",
    "channel": "互动方式",
    "summary": "互动内容",
    "next_action": "下一步行动",
    "next_due_on": "下次跟进日期",
    "company": "公司",
    "title": "职位",
    "description": "描述",
    "start_on": "开始日期",
    "end_on": "结束日期",
    "school": "学校",
    "degree": "学位",
    "major": "专业",
}


def _today() -> date:
    # “今天”必须取上海时区（见 .trellis/spec talents-contract：CI UTC 16:00-24:00 窗口防日期串天）
    return datetime.now(SHANGHAI).date()


def _collect_updates(
    fields: dict[str, object],
    *,
    date_value: date | None = None,
    clear_date: bool = False,
    date_key: str = "next_due_on",
) -> dict[str, object]:
    """汇总部分更新字段：None 表示不修改；空字符串由 schema 归一为 None（即清空）；日期用 clear 开关清除。"""
    values = {key: value for key, value in fields.items() if value is not None}
    if clear_date:
        if date_value is not None:
            raise ToolError(f"{date_key} 与清除开关不能同时使用")
        values[date_key] = None
    elif date_value is not None:
        values[date_key] = date_value
    return values


def _validate[ModelT: BaseModel](model_type: type[ModelT], values: dict[str, object]) -> ModelT:
    """校验完整领域输入；失败时映射为中文 ToolError。"""
    if not values:
        raise ToolError("没有需要修改的字段：请至少传入一个要更新的字段")
    try:
        return model_type.model_validate(values)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            if message.startswith("Value error, "):
                message = message[len("Value error, ") :]
            label = _FIELD_LABELS.get(field, field)
            messages.append(f"{label}：{message}" if label else message)
        raise ToolError("参数校验未通过——" + "；".join(messages)) from exc


def _plan_text(next_action: str | None, next_due_on: date | None) -> str:
    if next_due_on is not None:
        return f"{next_due_on.isoformat()} {next_action or ''}".strip()
    return next_action or "未安排"


def _period_text(start_on: date, end_on: date | None) -> str:
    """履历/院校区间展示：月精度 YYYY-MM，end_on 为空表示「至今」（对齐 talents-contract 月精度约定）。"""
    start = start_on.isoformat()[:7]
    end = end_on.isoformat()[:7] if end_on is not None else "至今"
    return f"{start} 至 {end}"


def _talent_not_found(talent_id: UUID) -> ToolError:
    return ToolError(f"人才不存在（id={talent_id}），请先调用 talent_list 确认可用的人才 ID")


async def _confirm_talent_name(session: AsyncSession, talent_id: UUID, confirm: str) -> None:
    talent = await TalentsRepository(session).get_talent(talent_id)
    if talent is None:
        raise _talent_not_found(talent_id)
    if confirm != talent.name:
        raise ToolError("删除未执行：confirm_talent_name 与人才名称不完全一致，请先用 talent_get 核对后重试")


def _interaction_not_found(interaction_id: UUID) -> ToolError:
    return ToolError(f"跟进记录不存在或不属于该人才（id={interaction_id}），请先调用 talent_interaction_list 确认")


def _experience_not_found(experience_id: UUID) -> ToolError:
    return ToolError(f"履历不存在或不属于该人才（id={experience_id}），请先调用 talent_experience_list 确认")


def _education_not_found(education_id: UUID) -> ToolError:
    return ToolError(f"院校经历不存在或不属于该人才（id={education_id}），请先调用 talent_education_list 确认")


@contextmanager
def _mutation_errors() -> Iterator[None]:
    try:
        yield
    except InvalidRatePairError as exc:
        raise ToolError("费率金额与单位必须同时填写或同时留空（rate_amount 与 rate_unit 需一起传值）") from exc
    except InvalidDateRangeError as exc:
        raise ToolError("结束日期不能早于开始日期") from exc
    except InvalidProfileImportError as exc:
        raise ToolError(str(exc)) from exc
    except DuplicateTalentNameError as exc:
        name = exc.args[0] if exc.args else ""
        raise ToolError(f"存在多个同名人才「{name}」，无法确定更新目标，请改用 talent_update 指定人才 ID 更新") from exc
