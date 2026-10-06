# Talent 画像扩展（#201 P2）

## Goal

让 `Talent` 承载完整人才画像：联系方式、喜好、工作履历（哪年到哪年在哪个公司任什么职务）、毕业院校，web 可结构化录入与展示（issue #201 P2）。

## Background

- 决策已在 issue #201 锁定：客户（公司）与人才（人）分离，画像全部加到 Talent；简历=结构化履历数据，与附件无关；履历/院校建 1—N 子表，喜好多值走 JSONB；organization 保留手动快照不派生；无存量数据，migration 可破坏性重建。
- talents 域现状：`Talent` 无联系方式、无画像扩展点；`tags`（JSONB 数组）是现成先例；`talent_interactions` 是现成 1—N 子表范式。
- 顺带落地横切项：talents 到期语义从 `min(next_due_on)` 改为「最新记录」语义，与 P1 后的 CRM 对齐（issue #201 Q13/横切条款）。

## Requirements

- R1 `Talent` 加列 `phone` / `email` / `wechat`（均可空，trim、空串归 null、email 格式校验，规则与 CRM Contact 一致）。
- R2 `Talent` 加列 `preferences`：JSONB 字符串数组，默认空数组，元素 trim 去重；语义=喜好/个人标签，与 `tags`（能力/行业）并列，二者不混用。
- R3 新子表 `TalentExperience`（Talent 1—N，CASCADE）：`start_on`(date，必填) / `end_on`(date，可空=至今) / `company` / `title` / `description`(可空)。校验：`end_on >= start_on`。录入精度到月（允许 YYYY-MM，补 01 落库），展示到月；倒序排列（至今在前）。
- R4 新子表 `TalentEducation`（Talent 1—N，CASCADE）：`school` / `degree`(自由文本) / `major` / `start_on` / `end_on`(可空=至今)，校验与排序同 R3。
- R5 REST 嵌套端点与 web 界面：履历/院校走 `/api/talents/{id}/experiences|educations` 嵌套 CRUD（与 contacts/follow-ups 同范式）；talent 表单加联系方式与喜好字段；详情页新增画像区（联系方式、喜好）+ 履历/院校时间线（倒序、至今在前、逐条增删改）。
- R6 `organization` 保留手动维护，不从履历派生（最新履历 ≠ 用户认知的当前单位）。
- R7 talents 到期语义改「最新记录」：`_earliest_due_subquery`(min) → 最新一条 interaction 的 `next_due_on`（occurred_on desc, created_at desc, id desc），`due` 过滤四档语义与 SHANGHAI 时区规则不变，与 CRM P1 后的口径一致。
- R8 `.trellis/spec/reven-server/backend/talents-contract.md` 同步（Phase 3.3）。

## Non-Goals

- talents agent 工具全套（P3）、画像字段搜索扩展（P4）、方式枚举合并（P3 前后）。
- CRM 域的任何改动。
- 简历附件/文件存储（决策：与附件无关，结构化履历即全部）。
- 履历/院校的 agent 批量导入（`talent_import_profile`，P3）。

## Acceptance Criteria

- [ ] migration `0026`：Talent 新列（3 联系方式 + preferences JSONB 默认值）+ 两张子表（FK CASCADE、必要索引、check 约束、RLS 惯例与 0015 一致）；upgrade/downgrade 双向通过；`FINAL_REVISION` 更新。
- [ ] REST：talent 创建/更新接受并校验联系方式与 preferences；experience/education 嵌套 CRUD 完整，越父访问 404；`end_on < start_on` 与缺必填字段 422。
- [ ] web：talent 表单可填联系方式/喜好；详情页画像区与两条时间线展示正确（倒序、至今在前、精度到月）；逐条增删改可用；空态有引导。
- [ ] 到期语义：某人才最新 interaction 无 `next_due_on` 时，旧日期不再冒泡（due=overdue 查不到）；最新有日期时按最新日期分档。
- [ ] `organization` 与履历互不联动（改履历不改 organization）。
- [ ] server 与 web 测试全绿；lint、typecheck、覆盖率门禁通过。

## Notes

- 决策依据与四期全貌见 issue #201：https://github.com/wangyiyang/Reven/issues/201
