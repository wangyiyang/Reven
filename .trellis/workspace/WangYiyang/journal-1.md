# Journal - WangYiyang (Part 1)

> AI development session journal
> Started: 2026-08-12

---


## 2026-08-12 · 品牌 VI 重构（08-12-brand-vi-refactor）
- 分支 refactor/brand-vi，4 commit：资产+字体 / web 全面换肤+深色模式 / renderer 主题 / 质检修复
- 三色系统落地：--bg/--ink/--signal/--muted/--faint/--line + --danger 语义例外；字体 fontsource 本地打包（Inter/Noto Sans SC/JetBrains Mono）
- 深色模式 data-theme 驱动 + theme.ts（localStorage try/catch）；Logo {翊} master/mono-white 双版切换 + favicon
- renderer 微信预览：主色 #00E676、标题全碳黑、引用绿竖线、代码块深色+绿关键字；新增 render-brand.test.ts 回归锁
- 规范沉淀：.trellis/spec/web/frontend/brand-vi.md（令牌契约 + VI 铁律 + 链接/卡片/徽标口径）
- 验证：web lint/test(64)/build、renderer test(32) 全绿；走查截图存任务 assets/（后端未启动，数据页为空态，组件态由测试覆盖）
