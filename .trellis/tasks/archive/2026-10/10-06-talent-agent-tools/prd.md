# talents agent 工具全套与方式枚举统一（#201 P3）

## Goal

让 AI agent 能完整操作 talents 域（人才/互动/履历/院校的 CRUD 与搜索 + 简介批量导入），并把两域「跟进方式」枚举合并为一套，agent 工具面术语统一（issue #201 P3）。

## Background

- 决策已锁定（issue #201 Q10）：对称 CRM 工具面 ≈15 个 CRUD 工具 + 1 个 `talent_import_profile` 批量工具（服务「粘贴简介一次解析落库」场景）；画像字段并入 talent 创建/更新。
- 现状：agent 层只有 `tools_crm_*` 与 `tools_rss`，talents 无 MCP 工具；P1/P2 完成后 talents 的 REST/服务层已具备全部能力（嵌套端点、画像、派生到期语义）。
- 横切债：CRM `FollowUpKind`（含「会议」）与 talents `InteractionChannel`（含「电话语音」「面谈」，无「其他」）两套枚举并存，agent 跨域操作时术语分裂；决策（issue #201 横切条款）：合并为「电话/面谈/微信/邮件/其他」。

## Requirements

- R1 talents MCP 工具全套（对称 CRM 命名与模式：session 注入、`_validate`、`_mutation_errors`、delete 需逐字确认人才名、中文文案）：
  - talent：list（q/status/due/tag 过滤）、get（详情+画像+互动+履历+院校）、create、update、delete（级联提示）
  - interaction：list、create、update（含 clear_next_due_on）、delete
  - experience / education：各 list、create、update、delete
- R2 `talent_import_profile` 批量工具：一次调用写入人才基础信息 + tags/preferences + 多条履历 + 多条院校；已有人才按名称匹配时更新画像、追加子表（不重复创建同名人才）；整体单事务（任一部分失败全回滚）；返回各项写入/追加计数。
- R3 方式枚举两域合并为「电话/面谈/微信/邮件/其他」：CRM「会议」并入「面谈」，talents「电话语音」并入「电话」、补「其他」；migration 0027 改写两表 check 约束（无存量数据）；web 常量/表单/筛选、agent 工具参数与文案、测试同步。
- R4 工具话术对齐新语义：`next_due_on` 即当前计划（自动生效，派生）；tags=能力/行业 vs preferences=喜好/个人；日期参数 YYYY-MM-DD（履历/院校提示月精度补 01）。
- R5 spec 同步：tool-contracts 相关文件 + 两个域契约的枚举条款（Phase 3.3）。

## Non-Goals

- P4 搜索扩展到画像字段（repository `_customer_search`/`q` 的画像覆盖）。
- web UI 功能新增（除枚举值同步引起的必要改动）。
- talents interactions REST 路由形状重构（扁平 PATCH 保留）。
- CRM 工具面除枚举值外的行为改动。

## Acceptance Criteria

- [ ] agent 可完成 talents 全域 CRUD：创建人才（含画像）、更新画像、按 q/status/due/tag 搜索、记录互动（计划自动生效）、增删改履历与院校；删除人才需逐字确认名称并提示级联范围。
- [ ] `talent_import_profile` 一次调用落成完整画像（基础+标签+喜好+多履历+多院校）；已存在同名人才时更新画像并追加子表；任一部分非法输入时整体不入库；返回各项计数。
- [ ] 枚举合并后：两域创建/更新跟进只接受「电话/面谈/微信/邮件/其他」，旧值（会议/电话语音）在 REST 与 MCP 均 422；DB check 约束与新集合一致；web 下拉/筛选为新集合。
- [ ] talents 工具话术符合 R4；LLM 可见描述中无 `set_as_current` / min 语义等过时表述。
- [ ] server 测试（agent/api/migrations）全绿；web 测试全绿；lint、typecheck、覆盖率门禁通过。

## Notes

- 决策依据与四期全貌见 issue #201：https://github.com/wangyiyang/Reven/issues/201
