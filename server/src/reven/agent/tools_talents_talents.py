"""Talents talents MCP adapter: input conversion and Chinese output."""

from decimal import Decimal
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field

from reven.agent.talents_tool_support import (
    ConfirmTalentNameParam,
    DueFilterParam,
    RateUnitParam,
    TalentIdParam,
    TalentStatusParam,
    _collect_updates,
    _confirm_talent_name,
    _mutation_errors,
    _plan_text,
    _talent_not_found,
    _today,
    _validate,
)
from reven.agent.tool_binding import ToolSessionBinding
from reven.agent.tools_talents_educations import _education_line
from reven.agent.tools_talents_experiences import _experience_line
from reven.agent.tools_talents_interactions import _interaction_line
from reven.scheduling import SHANGHAI
from reven.talents.inputs import (
    TalentCreate,
    TalentEducationCreate,
    TalentExperienceCreate,
    TalentUpdate,
)
from reven.talents.models import TalentStatus
from reven.talents.repository import TalentPlan, TalentsRepository
from reven.talents.service import TalentsService


class TalentsTalentTools(ToolSessionBinding):
    async def list_talents(
        self,
        query: Annotated[
            str | None,
            Field(
                description="模糊检索词：匹配人才姓名/当前单位/备注/能力描述/联系方式，以及标签/喜好和履历（公司/职位/描述）/院校（学校/学位/专业）"
            ),
        ] = None,
        status: TalentStatusParam | None = None,
        due: DueFilterParam | None = None,
        tag: Annotated[str | None, Field(description="按单个能力/行业标签精确筛选（如：设计）")] = None,
    ) -> str:
        """检索人才列表，可按画像关键词模糊搜索（姓名/单位/能力/标签/喜好/联系方式/履历/院校）、按人才状态筛选、按跟进日期筛选、按能力标签精确筛选。

        返回每个人才的 id、姓名、状态、单位、标签与当前跟进计划（派生自最新一条互动记录）；
        拿到 id 后可调用 talent_get 看完整画像，或 talent_update / talent_delete 做变更。
        """
        today = _today()
        async with self._session() as session:
            plans = await TalentsRepository(session).list_talent_plans(
                status=status,
                due=due,
                query=query,
                tag=tag,
                today=today,
            )
        if not plans:
            return "没有找到符合条件的人才。可调整筛选条件，或用 talent_create 新建人才。"
        header = f"共 {len(plans)} 个人才："
        lines = [f"{index}. {_talent_line(plan)}" for index, plan in enumerate(plans, 1)]
        return "\n".join([header, *lines])

    async def get_talent(self, talent_id: TalentIdParam) -> str:
        """查看人才详情：基本信息与画像（标签/喜好/联系方式/费率）+ 当前跟进计划 + 全部互动记录 + 履历 + 院校经历。"""
        async with self._session() as session:
            repository = TalentsRepository(session)
            plan = await repository.get_talent_plan(talent_id)
            if plan is None:
                raise _talent_not_found(talent_id)
            interactions = await repository.list_interactions(talent_id)
            experiences = await repository.list_experiences(talent_id)
            educations = await repository.list_educations(talent_id)
        lines = [_talent_detail(plan)]
        if interactions:
            lines.append(f"互动记录（{len(interactions)}）：")
            lines.extend(_interaction_line(index, interaction) for index, interaction in enumerate(interactions, 1))
        else:
            lines.append("暂无互动记录。可用 talent_interaction_create 记录第一次接洽并定下当前计划。")
        if experiences:
            lines.append(f"履历（{len(experiences)}）：")
            lines.extend(_experience_line(index, experience) for index, experience in enumerate(experiences, 1))
        else:
            lines.append("暂无履历。")
        if educations:
            lines.append(f"院校经历（{len(educations)}）：")
            lines.extend(_education_line(index, education) for index, education in enumerate(educations, 1))
        else:
            lines.append("暂无院校经历。")
        return "\n".join(lines)

    async def create_talent(
        self,
        name: Annotated[str, Field(description="人才姓名（必填）")],
        organization: Annotated[str | None, Field(description="当前单位（手动维护的快照，不从履历派生）")] = None,
        status: TalentStatusParam = TalentStatus.CANDIDATE,
        tags: Annotated[
            list[str] | None,
            Field(description="能力/行业标签（如：设计、插画、品牌）；与 preferences（喜好/个人）语义不同，不要混用"),
        ] = None,
        preferences: Annotated[
            list[str] | None,
            Field(description="喜好/个人偏好（如：远程工作、不加班）；与 tags（能力/行业）语义不同，不要混用"),
        ] = None,
        phone: Annotated[str | None, Field(description="联系电话")] = None,
        email: Annotated[str | None, Field(description="邮箱")] = None,
        wechat: Annotated[str | None, Field(description="微信号")] = None,
        capability: Annotated[str | None, Field(description="能力描述，如：品牌视觉设计、全栈开发")] = None,
        engagement_terms: Annotated[str | None, Field(description="合作条件，如：预付 50%、签保密协议")] = None,
        availability: Annotated[str | None, Field(description="可用时间，如：每周 20 小时")] = None,
        rate_amount: Annotated[
            Decimal | None,
            Field(description="费率金额（非负，最多两位小数）；必须与 rate_unit 同时填写"),
        ] = None,
        rate_unit: RateUnitParam | None = None,
        rating: Annotated[int | None, Field(description="评分，1-5 的整数")] = None,
        notes: Annotated[str | None, Field(description="备注")] = None,
    ) -> str:
        """新建一个人才（可一并写入画像：标签/喜好/联系方式/费率等）。状态默认为「候选」。

        人才本身不保存跟进计划：创建后可用 talent_interaction_create 记录第一次互动，
        并在互动上写下下一步行动（next_action）与下次跟进日期（next_due_on），即成为该人才的当前计划。
        """
        fields = {
            "name": name,
            "organization": organization,
            "status": status,
            "tags": tags,
            "preferences": preferences,
            "phone": phone,
            "email": email,
            "wechat": wechat,
            "capability": capability,
            "engagement_terms": engagement_terms,
            "availability": availability,
            "rate_amount": rate_amount,
            "rate_unit": rate_unit,
            "rating": rating,
            "notes": notes,
        }
        payload = _validate(TalentCreate, {key: value for key, value in fields.items() if value is not None})
        with _mutation_errors():
            async with self._session() as session:
                talent = await TalentsService(session, commit=self._commits).create_talent(payload.model_dump())
                self._record_entity(talent)
        plan = TalentPlan(talent=talent, next_action=None, next_due_on=None)
        return f"已创建人才：{_talent_line(plan)}。可用 talent_interaction_create 记录第一次接洽并定下当前计划。"

    async def update_talent(
        self,
        talent_id: TalentIdParam,
        name: Annotated[str | None, Field(description="新姓名；不传则不修改")] = None,
        organization: Annotated[str | None, Field(description="新当前单位；传空字符串表示清空")] = None,
        status: TalentStatusParam | None = None,
        tags: Annotated[
            list[str] | None,
            Field(description="新能力/行业标签（整体替换）；传空数组表示清空"),
        ] = None,
        preferences: Annotated[
            list[str] | None,
            Field(description="新喜好/个人偏好（整体替换）；传空数组表示清空"),
        ] = None,
        phone: Annotated[str | None, Field(description="新联系电话；传空字符串表示清空")] = None,
        email: Annotated[str | None, Field(description="新邮箱；传空字符串表示清空")] = None,
        wechat: Annotated[str | None, Field(description="新微信号；传空字符串表示清空")] = None,
        capability: Annotated[str | None, Field(description="新能力描述；传空字符串表示清空")] = None,
        engagement_terms: Annotated[str | None, Field(description="新合作条件；传空字符串表示清空")] = None,
        availability: Annotated[str | None, Field(description="新可用时间；传空字符串表示清空")] = None,
        rate_amount: Annotated[Decimal | None, Field(description="新费率金额；单独修改时人才须已有费率单位")] = None,
        rate_unit: Annotated[
            RateUnitParam | None,
            Field(description="新费率单位；单独修改时人才须已有费率金额"),
        ] = None,
        rating: Annotated[int | None, Field(description="新评分，1-5 的整数")] = None,
        notes: Annotated[str | None, Field(description="新备注；传空字符串表示清空")] = None,
        clear_rate: Annotated[bool, Field(description="为 true 时同时清空费率金额与单位")] = False,
    ) -> str:
        """修改人才信息与画像（部分更新，只传要改的字段）。修改状态即完成人才流转（如 候选 → 接洽中 → 已合作）。

        费率金额与单位必须配对：改其中一个时另一个须已存在，否则一并传入；清空费率用 clear_rate。
        人才的当前跟进计划不可在此直接修改：用 talent_interaction_create 记录新互动并写下
        next_action / next_due_on，或用 talent_interaction_update 修改最新一条互动记录。
        """
        values = _collect_updates(
            {
                "name": name,
                "organization": organization,
                "status": status,
                "tags": tags,
                "preferences": preferences,
                "phone": phone,
                "email": email,
                "wechat": wechat,
                "capability": capability,
                "engagement_terms": engagement_terms,
                "availability": availability,
                "rate_amount": rate_amount,
                "rate_unit": rate_unit,
                "rating": rating,
                "notes": notes,
            }
        )
        if clear_rate:
            if rate_amount is not None or rate_unit is not None:
                raise ToolError("clear_rate 与费率字段不能同时使用")
            values["rate_amount"] = None
            values["rate_unit"] = None
        payload = _validate(TalentUpdate, values)
        with _mutation_errors():
            async with self._session() as session:
                repository = TalentsRepository(session)
                talent = await repository.get_talent(talent_id)
                if talent is None:
                    raise _talent_not_found(talent_id)
                updated = await TalentsService(session, commit=self._commits).update_talent(
                    talent, payload.model_dump(exclude_unset=True)
                )
                self._record_entity(updated)
                plan = await repository.get_talent_plan(updated.id)
        if plan is None:  # pragma: no cover - 刚更新的人才必然存在
            raise _talent_not_found(talent_id)
        return f"已更新人才：{_talent_line(plan)}"

    async def delete_talent(self, talent_id: TalentIdParam, confirm_talent_name: ConfirmTalentNameParam) -> str:
        """删除一个人才，其名下互动记录、履历、院校经历会一并删除，不可恢复。

        调用前必须与用户确认删除意图，并把人才名称逐字填入 confirm_talent_name。
        """
        with _mutation_errors():
            async with self._session() as session:
                await _confirm_talent_name(session, talent_id, confirm_talent_name)
                talent = await TalentsRepository(session).get_talent(talent_id)
                if talent is None:  # pragma: no cover - confirm 已确认存在
                    raise _talent_not_found(talent_id)
                name = talent.name
                await TalentsService(session, commit=self._commits).delete_talent(talent)
                self._record_entity(talent)
        return f"已删除人才「{name}」（id={talent_id}），其名下互动记录、履历与院校经历已一并删除。"

    async def import_profile(
        self,
        name: Annotated[
            str,
            Field(description="人才姓名（必填）；与已有人才精确同名时更新该人才画像并追加履历/院校，不会重复创建"),
        ],
        organization: Annotated[str | None, Field(description="当前单位")] = None,
        status: TalentStatusParam | None = None,
        tags: Annotated[list[str] | None, Field(description="能力/行业标签（如：设计、插画）")] = None,
        preferences: Annotated[list[str] | None, Field(description="喜好/个人偏好（如：远程工作）")] = None,
        phone: Annotated[str | None, Field(description="联系电话")] = None,
        email: Annotated[str | None, Field(description="邮箱")] = None,
        wechat: Annotated[str | None, Field(description="微信号")] = None,
        capability: Annotated[str | None, Field(description="能力描述")] = None,
        engagement_terms: Annotated[str | None, Field(description="合作条件")] = None,
        availability: Annotated[str | None, Field(description="可用时间")] = None,
        rate_amount: Annotated[Decimal | None, Field(description="费率金额；必须与 rate_unit 同时填写")] = None,
        rate_unit: RateUnitParam | None = None,
        rating: Annotated[int | None, Field(description="评分，1-5 的整数")] = None,
        notes: Annotated[str | None, Field(description="备注")] = None,
        experiences: Annotated[
            list[TalentExperienceCreate] | None,
            Field(description="履历条目：company/title/start_on 必填，end_on 可空（至今），YYYY-MM-DD（月精度补 01）"),
        ] = None,
        educations: Annotated[
            list[TalentEducationCreate] | None,
            Field(description="院校条目：school/start_on 必填，degree/major/end_on 可选，YYYY-MM-DD（月精度补 01）"),
        ] = None,
    ) -> str:
        """粘贴简介批量建画像专用：一次调用写入人才基础信息、标签/喜好、联系方式与多条履历、多条院校。

        按姓名精确匹配：人才不存在则新建；已存在则只更新本次提交的画像字段并追加履历/院校（不去重）；
        存在多个同名人才时报错，请改用 talent_update 指定 ID。任一字段或任一条目非法时整体不入库。
        """
        fields = {
            "name": name,
            "organization": organization,
            "status": status,
            "tags": tags,
            "preferences": preferences,
            "phone": phone,
            "email": email,
            "wechat": wechat,
            "capability": capability,
            "engagement_terms": engagement_terms,
            "availability": availability,
            "rate_amount": rate_amount,
            "rate_unit": rate_unit,
            "rating": rating,
            "notes": notes,
        }
        values: dict[str, object] = {key: value for key, value in fields.items() if value is not None}
        values["experiences"] = [item.model_dump() for item in experiences or []]
        values["educations"] = [item.model_dump() for item in educations or []]
        with _mutation_errors():
            async with self._session() as session:
                result = await TalentsService(session, commit=self._commits).import_profile(values)
                self._record_entity(result.talent)
                self.receipt.update(
                    experiences=result.experiences, educations=result.educations, created=result.created
                )
        talent = result.talent
        chunks = []
        if result.experiences:
            chunks.append(f"履历 {result.experiences} 条")
        if result.educations:
            chunks.append(f"院校 {result.educations} 条")
        children = "、".join(chunks) if chunks else "无履历/院校条目"
        if result.created:
            return (
                f"已导入人才「{talent.name}」（id={talent.id}）：画像已创建（状态：{talent.status}），"
                f"写入{children}。可用 talent_interaction_create 记录第一次接洽并定下当前计划。"
            )
        return (
            f"已导入人才「{talent.name}」（id={talent.id}）：画像已更新，追加{children}。可用 talent_get 查看完整画像。"
        )


def _talent_line(plan: TalentPlan) -> str:
    talent = plan.talent
    parts = [f"「{talent.name}」（id={talent.id}，状态：{talent.status}）"]
    if talent.organization:
        parts.append(f"单位：{talent.organization}")
    if talent.tags:
        parts.append(f"标签：{'、'.join(talent.tags)}")
    if plan.next_action or plan.next_due_on:
        parts.append(f"当前计划：{_plan_text(plan.next_action, plan.next_due_on)}")
    return "｜".join(parts)


def _talent_detail(plan: TalentPlan) -> str:
    talent = plan.talent
    created_on = talent.created_at.astimezone(SHANGHAI).date().isoformat()
    parts = [
        f"人才「{talent.name}」（id={talent.id}）",
        f"状态：{talent.status}｜单位：{talent.organization or '未填写'}｜创建于：{created_on}",
        f"当前跟进计划：{_plan_text(plan.next_action, plan.next_due_on)}",
    ]
    taxonomies = []
    if talent.tags:
        taxonomies.append(f"标签：{'、'.join(talent.tags)}")
    if talent.preferences:
        taxonomies.append(f"喜好：{'、'.join(talent.preferences)}")
    if taxonomies:
        parts.append("｜".join(taxonomies))
    contacts = []
    if talent.phone:
        contacts.append(f"电话 {talent.phone}")
    if talent.email:
        contacts.append(f"邮箱 {talent.email}")
    if talent.wechat:
        contacts.append(f"微信 {talent.wechat}")
    if contacts:
        parts.append(f"联系方式：{'｜'.join(contacts)}")
    commercial = []
    if talent.rate_amount is not None and talent.rate_unit:
        commercial.append(f"费率：{talent.rate_amount} {talent.rate_unit}")
    if talent.rating is not None:
        commercial.append(f"评分：{talent.rating}")
    if commercial:
        parts.append("｜".join(commercial))
    if talent.capability:
        parts.append(f"能力：{talent.capability}")
    if talent.engagement_terms:
        parts.append(f"合作条件：{talent.engagement_terms}")
    if talent.availability:
        parts.append(f"可用时间：{talent.availability}")
    if talent.notes:
        parts.append(f"备注：{talent.notes}")
    return "\n".join(parts)
