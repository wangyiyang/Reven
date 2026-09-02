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

- [x] 正常文本和文字按钮对比度至少 4.5:1；大文本/非文字 UI 满足 WCAG AA 对应阈值。
- [x] `/crm`、`/articles` 及共用侧栏在浅色/深色下 axe-core `color-contrast` 无 serious/critical 违规。
- [x] focus、hover、disabled、active 状态仍可辨识。
- [x] token/组件测试、视觉回归、web lint/test/build 通过。

## Out of Scope

- 未经批准的整站品牌重构或新增第四套主题。

## Key Decision

- 用户确认保留当前 Notion 风格蓝灰主题；本任务只做必要的可访问性修复，并同步纠正已过期的 Brand VI 规范。

## Verification

- 红灯复现：旧 token、固定白字和固定 emerald 断言失败；首次 opacity hover 的真实有效对比度仅 4.49:1。
- 定向 CRM/theme/finance 测试：20/20 通过。
- 完整 Web 测试：设置 Node `--localstorage-file` 后 19 个文件、170/170 通过；默认环境仅 `app-shell` 10 项因 Node 未提供 localStorage 文件而失败，相关测试与配置相对 HEAD 无差异。
- Web ESLint、TypeScript build、Vite build、`git diff --check`：全部通过；仅有既存的大包体积提示。
- axe-core 4.10.3：`/articles`、`/crm`、共用侧栏、登录、primary/danger hover 在浅色和深色下均为 0 violations。
- 浏览器确认两主题 focus 可见、hover 为 `-1px`、active 为 `1px` 位移，颜色与 opacity 保持；disabled 仍可识别。
- CRM notes textarea 的 axe 结果为原生 resize 覆盖导致的 `incomplete`，不是 violation；placeholder 已显式使用不透明 `--muted`。
- 4 张截图确认继续保持 Notion 蓝灰视觉；详细证据见 `research/contrast-evidence.md`。
