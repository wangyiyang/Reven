# 统一抽屉组件重构：Notion 风视觉、动效与表单单列

## Goal

重构全站共用的 Drawer 组件（`web/src/components/ui/drawer.tsx`），解决"开关生硬无动画、视觉平板无层次、表单在抽屉里拥挤"三大痛点，风格参照 Notion；顺带重新构建 `web/dist` 解决本地看不到 talents 抽屉的问题（dist 为 10-01 旧构建，抽屉代码 10-05 才合入）。

## Background

需求来源于一次 grilling 访谈（2026-10-05），已与需求方达成完整共识：

- 全站 7 个表单抽屉共用唯一自研 `Drawer`（底层 Radix Dialog）：talents、CRM 客户、项目、SOP、RSS 源、RSS 关键词、财务记账
- 现状病因：零动画（调用方 `if (!open) return null` 直接卸载导致退出动画无法播放）、宽度写死 448px 与 `md:grid-cols-3` 宽屏表单冲突、无圆角无层次、按钮规范分裂（talent 左对齐无取消 vs 其他右对齐有取消）、缺 `Dialog.Description`（a11y 警告）、SOP 查看弹窗与财务结算确认框两处内联手写弹窗重复造轮子

## Requirements

### 视觉（Notion 风）

- 面板大圆角（左侧上下圆角）、柔和扩散阴影，摆脱"一块平板拍在屏幕上"
- 遮罩从 `bg-black/55` 降为极浅（约 `bg-black/20`），保留轻微聚焦感，点外部可关闭
- 与项目现有 token 体系（`web/src/index.css`）保持一致

### 动效

- 右侧滑入滑出动画（Notion 式平滑过渡）
- 修复所有调用方 `if (!open) return null` 的卸载模式，保证退出动画可播放

### 布局与规范

- 抽屉内表单强制单列纵向排布（Notion 式：标签在上、输入框在下），消除三列挤压
- 按钮规范统一：右对齐 + 必有「取消」，收敛 talent 表单的左对齐异类
- 补 `Dialog.Description`（或 `aria-describedby`），消除 Radix a11y 警告

### 收敛重复实现

- SOP 查看弹窗（`sops-page.tsx` 内联手写）与财务结算确认框（`confirm-settle-dialog.tsx` 内联手写）并入统一组件（Drawer 或 ConfirmDialog，按语义选择）

### 环境修复

- 重新构建 `web/dist`（或起 dev server），验证 talents「新建人才」抽屉在本地可见可用

## Out of Scope（明确不做）

- 移动端下拉关闭手势（vaul）
- 原生 select 替换为 Radix Select
- 抽屉宽度档位体系（本任务统一单列，不需要多档宽度）

## Acceptance Criteria

- [ ] 本地 dev server / 新构建上，7 个抽屉全部可打开，视觉统一为 Notion 风（圆角、柔阴影、浅遮罩）
- [ ] 抽屉开关有平滑滑入滑出动画，退出动画正常播放
- [ ] 抽屉内表单单列排布，无字段挤压
- [ ] 所有抽屉按钮右对齐且带「取消」
- [ ] 控制台无 Radix Description 相关 a11y 警告
- [ ] SOP 查看弹窗与财务结算确认框不再使用内联手写 Overlay 结构
- [ ] talents 页「新建人才」抽屉在本地环境实际可见（用户亲验）
- [ ] `web/` 现有测试与构建通过

## Notes

- 轻量任务，PRD-only，无需 design.md / implement.md
- 改动抓手集中：`web/src/components/ui/drawer.tsx`（33 行）+ 各调用方卸载模式微调
