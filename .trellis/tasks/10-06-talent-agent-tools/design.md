# 技术设计：talents agent 工具与枚举统一

## 核心原则

工具面是 LLM 契约：形状对称 CRM（agent 跨域操作心智一致）、文案说人话、删除必须逐字确认；校验层不重复——agent 与 REST 共用同一份输入模型。

## 1. 校验层落位（关键架构决策）

CRM 的先例：域层 `crm/inputs.py` 持有校验，`api/schemas/crm.py` 重导出，agent 工具 import 域层——agent 不依赖 api 层。talents 现状：校验写在 `api/schemas/talents.py`，若 agent 直接 import api 层会造成层次倒置。

**决策**：把 talents 的输入校验抽到域层 `server/src/reven/talents/inputs.py`（Pydantic 模型原样平移：TalentCreate/Update、InteractionCreate/Update、ExperienceCreate/Update、EducationCreate/Update 及别名/validator），`api/schemas/talents.py` 改为重导出 + 保留响应模型（对齐 `api/schemas/crm.py:8-13` 形状）。REST 路由行为零变化（同名同校验）。若 research 发现依赖方向另有约束，以其结论为准并在 implement.md 修正。

## 2. 工具清单与命名（新增 `server/src/reven/agent/tools_talents*.py`）

| 工具 | 说明 |
|---|---|
| `talent_list` | q/status/due/tag 过滤；行文案含派生计划与画像摘要 |
| `talent_get` | 详情：画像（tags/preferences/联系方式）+ 互动 + 履历 + 院校 |
| `talent_create` / `talent_update` | 画像字段并入；`clear_*` 开关对齐 CRM 模式 |
| `talent_delete` | `confirm_talent_name` 逐字确认；文案提示级联（互动/履历/院校） |
| `talent_interaction_list/create/update/delete` | create 话术「next_due_on 即当前计划，自动生效」；update 含 `clear_next_due_on` |
| `talent_experience_list/create/update/delete` | 日期描述注明月精度补 01 |
| `talent_education_list/create/update/delete` | 同上 |
| `talent_import_profile` | 见 §3 |

注册方式照 CRM（research 补确切挂载点）。枚举参数用 Annotated Literal 风格对齐 `CustomerStatusParam`。删除互动/履历/院校不需要名称确认（与 CRM follow-up 删除的 confirm 模式对齐——CRM 对 follow-up 删除也要 confirm_customer_name，talents 侧对 interaction 删除同样要求 confirm_talent_name，保持对称）。

## 3. `talent_import_profile` 设计

入参（单 JSON 对象）：

```
name (必填) + organization? + status? + tags[]? + preferences[]? +
phone?/email?/wechat? + capability? + notes? +
experiences[]?: {company, title, start_on, end_on?, description?} +
educations[]?: {school, degree?, major?, start_on, end_on?}
```

行为：
- 按 `name` 精确匹配已有人才：存在 → 更新画像字段（仅提交的字段）、追加 experiences/educations；不存在 → 创建。同名多个人才（重名）→ 报 ToolError 要求改用 talent_update（不猜）。
- 单事务：任一子项校验失败（如 date_range）→ 整体回滚，返回错误明细（第几条履历/院校、原因）。
- 追加语义不去重（用户/agent 负责），返回文案给各项计数（新建/更新、标签数、履历 N 条、院校 N 条）。

实现：`TalentsService` 增加 `import_profile(payload)` 聚合写入口，内部复用现有 create/update 子表方法，一个 commit。

## 4. 枚举统一（migration 0027）

目标集合（两域共用）：`电话 / 面谈 / 微信 / 邮件 / 其他`。

- 映射：CRM「会议」→「面谈」；talents「电话语音」→「电话」；talents 补「其他」。
- 0027：对 `crm_follow_ups` 与 `talent_interactions` 的 kind/channel check 约束 drop 旧 + add 新（确切约束名以 research 为准）；无存量数据，不做数据 UPDATE（若有数据，downgrade 前需手工处理——在 migration docstring 注明）。
- `FollowUpKind` 与 `InteractionChannel` 两个 StrEnum 保留各自类名（减少 diff），值集合改为同一组；是否抽共享枚举：不抽（两域各自枚举类是现状结构，统一值即可）。
- web：`types.ts`（crm 与 talents 两侧常量数组）、表单/筛选下拉、测试 fixture 同步。
- agent：`FollowUpKindParam` 与 talents 侧新参数的 Literal 集合同步。

## 5. 兼容与回滚

- 枚举值变更是破坏性协议变更（旧值 422），REST+MCP+web 同 PR 发布；无存量数据。
- 回滚 = revert + downgrade 0027。

## 6. 风险与对策

- 工具面 +16 个，LLM 选择困难：工具描述首句写清「什么时候用这个工具」，talent_import_profile 描述明确「粘贴简介批量建画像专用」。
- 校验层平移引入行为漂移：平移前后跑同一套 API 测试（不改为绿），再叠加 MCP 测试。
- 重名人才：import 精确匹配遇多个同名即报错，不静默选一个。
