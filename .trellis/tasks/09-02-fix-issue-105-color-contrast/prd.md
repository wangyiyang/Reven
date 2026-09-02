# PRD · #105 WCAG AA 颜色对比度

## Goal

消除浅色和深色模式中的 serious 级 color-contrast 违规，使正常文本、按钮和状态信息满足 WCAG AA。

## Confirmed Facts

- 当前实际 UI 来自 2026-08-19 已合并的 PR #40（`9c9b0f8`）Notion 风格重设：浅色 signal `#2383E2`、muted `#9B9A97`，深色 signal `#529CCA`、muted `#8B8B89`。该 PR 明确以可读性和日常工具密度取代更早的终端绿海报风。
- 默认按钮使用 signal 大面积背景 + 白字；浅色侧栏大量使用 muted 小字，均存在不足 4.5:1 的组合。
- `.trellis/spec/web/frontend/brand-vi.md` 仍记录更早的终端绿 VI，但 `#00E676` 在冷白背景上同样不足 4.5:1，直接恢复不能解决可访问性问题。

## Requirements

- 以当前 Notion 风格蓝灰主题为视觉基线，不恢复旧终端绿 VI。
- 采用语义化的前景/背景 token，避免用一个 signal 值同时承担“文本色”和“按钮底色”而产生互斥对比度要求。
- 提升浅/深色 muted 文本，保证在页面背景与侧栏背景上均达 4.5:1。
- 覆盖筛选按钮、已发布徽标、侧栏导航及 axe 报告命中的同类节点。
- 推荐色值需保留安全余量而不只卡在 4.5:1：浅色 signal `#0B65A3`（白底 6.17:1）、muted `#6B6A67`（panel 5.04:1）；深色 signal `#6EB6E8`（panel 7.39:1）、muted `#A7A7A4`（panel 6.76:1）。按钮前景按主题使用白色/深色，分别达到 6.17:1/7.97:1。

## Acceptance Criteria

- [ ] 正常文本和文字按钮对比度至少 4.5:1；大文本/非文字 UI 满足 WCAG AA 对应阈值。
- [ ] `/crm`、`/articles` 及共用侧栏在浅色/深色下 axe-core `color-contrast` 无 serious/critical 违规。
- [ ] focus、hover、disabled、active 状态仍可辨识。
- [ ] token/组件测试、视觉回归、web lint/test/build 通过。

## Out of Scope

- 未经批准的整站品牌重构或新增第四套主题。

## Key Decision

- 用户确认保留当前 Notion 风格蓝灰主题；本任务只做必要的可访问性修复，并同步纠正已过期的 Brand VI 规范。
