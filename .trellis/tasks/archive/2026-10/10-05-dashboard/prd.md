# 工作台 Dashboard 首页

## Goal

新增"工作台"首页（路由 `/`，导航第一项），聚合财务待收款、RSS 待审核、CRM 待跟进、进行中项目四类经营事项与集成配置缺失提醒，回答用户"我现在该干什么"；取代 `/rss/candidates` 成为默认落地页。

## Background

需求经 grilling 访谈（2026-10-05）三轮达成共识：

- 产品定位即 README 原话"聚合需要判断和处理的经营事项"，Dashboard 以**行动中枢为主、经营概览为辅**
- 现状无首页：通配符路由直接重定向到 `/rss/candidates`，等于默认"每天第一件事是审 RSS"，假设不成立
- 已有 `/finance/overview` 与 `/system` 覆盖部分概览/监控职能，Dashboard 不重复造这两块
- 后端调查（见 `research/api-surface.md`）：无任何聚合端点，但 CRM 已有 `due=overdue/today` 过滤与 `list_due_follow_ups`（飞书每日提醒同源逻辑），RSS 候选接口带 `total`，财务有 `due_on` 但全站无逾期计算

## Requirements

### 后端：聚合端点

- 新增 `GET /api/dashboard/summary`，一次请求返回四模块聚合数据 + 集成缺失清单
- 财务：待收款总额、笔数；按 `due_on < 今日且未收` 计算逾期金额与笔数（"今日"按 Asia/Shanghai，与全站业务时间约定一致）
- RSS：待审核候选数（`status=candidate`）、已保存素材数（`status=saved`）、最近一次抓取运行状态（成功/失败、失败数、完成时间）
- CRM：逾期跟进数、今日待跟进数、待跟进 Top 5 清单（最逾期在前，**复用 `CrmRepository.list_due_follow_ups`**，与飞书每日提醒同源，不新写查询逻辑）
- 项目：进行中项目数、进行中项目 Top 5（含 `due_on`）
- 集成：5 个 DB provider（feishu_bot / translate_baidu / translate_aliyun / embedding / agent-llm）中未配置或 `secret_configured=false` 的清单；外加 COS 环境变量配置检查（`cos_configured`）

### 前端：工作台页面

- 新建 `web/src/features/dashboard/`，路由 `/`，导航第一项"工作台"；`*` 通配符改为重定向到 `/`
- 布局：顶部集成缺失横幅（可关闭）；第一行两张数字卡（财务待收款、RSS 待审核）；第二行两张清单卡（CRM 待跟进 Top 5、进行中项目 Top 5）；移动端单列堆叠，顺序 财务 → RSS → CRM → 项目
- 财务卡：待收款总额 + 笔数；逾期金额/笔数用 destructive 色突出
- RSS 卡：待审核候选数 + 已保存素材数；最近抓取失败时状态点显眼提示
- CRM 卡：标题带"逾期 N / 今日 N"，清单项含客户姓名 + 下次跟进日期，逾期红色
- 项目卡：标题带进行中总数，清单项含项目名 + 到期日，逾期红色
- 每张卡片整体可点击跳转对应模块（`/finance/pending`、`/rss/candidates`、`/crm`、`/projects`）；CRM 清单项可跳到客户详情
- 集成横幅：列出全部缺失项（含 COS），可关闭；关闭状态记 localStorage，出现新的缺失项时重新弹出
- 零值正常显示 0，不隐藏卡片；仅当模块完全未起步（如无任何 RSS 源）时显示引导文案 + 跳转链接
- 纯只读聚合，不做卡片内快捷操作、不做图表、不做布局自定义

## Out of Scope（明确不做）

- 卡片内快捷操作（采纳、标记已跟进等）
- 图表趋势分析、可配置布局/卡片自选
- 本月收支概览（已在 `/finance/overview`）
- 系统健康监控（已在 `/system`）
- 多用户/权限相关任何考虑

## Acceptance Criteria

- [ ] 打开 `/` 看到四张卡片，数字与对应模块页面实际数据一致
- [ ] 逾期项（财务应收、CRM 跟进、项目到期）以红色突出
- [ ] CRM 清单与飞书每日提醒数据一致（同一 Repository 方法）
- [ ] 集成横幅列出所有缺失 provider 与 COS（未配置时），可关闭；新增缺失项时重新弹出
- [ ] 卡片与 CRM 清单项点击跳转到对应页面
- [ ] 默认落地页（含未知路径重定向）为 `/`
- [ ] 移动端单列堆叠正常
- [ ] 后端聚合端点有 pytest 覆盖；前端页面有组件测试；`uv run ruff check server`、`uv run mypy server/src`、`pytest`、`pnpm test`、`pnpm build` 全绿

## Notes

- 复杂任务：需 design.md + implement.md
- API 现状调查见 `research/api-surface.md`
