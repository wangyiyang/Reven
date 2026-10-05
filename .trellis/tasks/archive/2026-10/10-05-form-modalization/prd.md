# 各资源页面创建/编辑表单弹窗化（#189）

## 目的/结论

将各资源页面的「创建/添加」表单从固定在页面顶部的内联卡片改为弹窗承载；页面顶部仅保留「新建 XX」按钮。创建/编辑交互全站统一。

来源：GitHub issue [#189](https://github.com/wangyiyang/Reven/issues/189)

## 背景

- 表单常驻首屏，压缩列表可视区域；而创建属于低频操作，常驻曝光收益低
- 各页面交互不统一，需要全站拉齐

## 涉及页面

| 页面 | 路由 | 现状 |
| --- | --- | --- |
| CRM | `/crm` | 「添加客户」卡片固定顶部（`crm-page.tsx` 的 `CustomerEditorCard`） |
| 人才库 | `/talents` | 同上（已在 #186 单独跟踪，见下） |
| 项目 | `/projects` | 内联「添加项目」表单 |
| SOP | `/sops` | 内联「添加 SOP」表单 |
| RSS | `/rss/sources`、`/rss/keywords` | 内联表单 |

注：`/talents` 的去表单化已在 #186 单独跟踪（本地 main 工作区有抽屉 Drawer 实现草稿，任务 `10-01-talents-page-split`）。本任务关注全站统一改造：talents 页面可参照 #186 模式核对/收尾，其余页面参照该模式落地。

## 方案（已决策）

- **窗口形式：全站统一 Drawer**（`web/src/components/ui/drawer.tsx`，Radix Dialog 右侧滑出）
- 列表页顶部仅保留「新建 XX」按钮，点击弹出 Drawer 承载表单
- **编辑入口按 spec convention 分两类**（对齐已合并的 `.trellis/spec/web/frontend/component-guidelines.md`「列表页去表单化拆分」约定）：
  - 有详情页的实体（CRM 客户）：列表行「编辑」跳详情页 `/:id?edit=1`，详情页页内切换编辑态
  - 无详情页的实体（项目、SOP、RSS 源/关键词）：编辑复用同一个 Drawer
- talents 页面由 #186 单独落地（草稿已在 main 工作区），本任务不做重复改造，仅核对模式一致
- 基线：`issue/gh-189-feat-web` 分支，worktree 于 `../worktrees/Reven/issue/gh-189-feat-web`

## 验收标准

- 上述页面的创建/编辑均通过弹窗完成，页面顶部不再常驻表单
- 弹窗的打开、提交、取消、关闭交互正常，提交后列表正确刷新
