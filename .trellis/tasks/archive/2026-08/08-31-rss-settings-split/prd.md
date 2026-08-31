# RSS 配置拆分：源与关键词独立路由

## Goal

把 RSS 配置页按"源管理 / 关键词管理"拆成两个独立路由与导航入口。纯前端信息架构调整：数据模型、筛选逻辑、后端 API 零改动。

## Background

- 现状 `/rss` 为单页堆叠结构：上方 SourcesPanel（源列表），下方 KeywordSettings（正/负关键词双面板 + 表单），页面冗长、职责混杂（`web/src/features/rss/rss-settings-page.tsx`）。
- 经 grilling 共识确认：关键词维持**全局**作用域，不做按源配词；`rss_keywords` 表不加 `source_id`。

## Requirements

- 新增 `/rss/sources` 与 `/rss/keywords` 两个独立路由，分别承载现有 SourcesPanel 与 KeywordSettings（含正/负双面板），交互与功能保持原样。
- `/rss` 改为重定向到 `/rss/sources`，兼容旧书签。
- 侧边栏导航将 RSS 相关入口收进一个**可折叠子菜单**：父项“RSS”可展开/收起，子项为“候选 / 源 / 关键词”（指向 `/rss/candidates`、`/rss/sources`、`/rss/keywords`）。
- 移动端横向 tab 条不支持层级，子项在移动端保持平铺展示（不折叠）。
- 组件拆分复用现有代码，不重构、不美化、不改交互细节（含关键词表单的"类型"下拉）。

## Out of Scope

- 后端 `server` 包零改动；筛选引擎、API、数据模型均不动。
- 不做按源关键词、关键词豁免等任何数据层能力。

## Acceptance Criteria

- [x] 访问 `/rss` 自动跳转到 `/rss/sources`
- [x] 侧边栏出现“RSS”可折叠父项，展开后可见“候选 / 源 / 关键词”三个子入口；移动端 tab 条中三项平铺可见
- [x] `/rss/sources` 与 `/rss/keywords` 两页的增删改查功能与原 `/rss` 页面完全一致
- [x] `web` 包测试全绿（含更新后的 `app-shell.test.tsx` 导航断言与拆分后的设置页测试）
