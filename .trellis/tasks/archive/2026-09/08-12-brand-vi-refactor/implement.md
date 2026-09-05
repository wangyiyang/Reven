# Implement · 应用界面品牌 VI 重构

按序执行，每步完成后跑对应验证命令，全绿再进下一步。

## Step 1 · 资产与字体依赖

- [x] 拷贝 `/tmp/brand/logo-assets/yixing-logo-v2-assets/` 中 `yixing-logo-v2-master.svg`、`yixing-logo-v2-mono-white.svg`、`yixing-logo-v2-mono-black.svg`、`yixing-logo-v2-favicon-16.png`、`yixing-logo-v2-favicon-32.png` → `web/public/brand/`
- [x] `pnpm -C web add @fontsource/noto-sans-sc @fontsource/inter @fontsource/jetbrains-mono`
- 验证：`ls web/public/brand/` 五个文件齐全；`pnpm -C web build` 通过

## Step 2 · 令牌层重写（`web/src/index.css`）

- [x] 按 design.md §1.1 重写颜色变量（含 `[data-theme="dark"]` 与 `prefers-color-scheme` 深色块），删除 `--red` / `--red-soft` / `--blue` / `--line-strong` 与纸纹背景
- [x] 引入三个 @fontsource 字体 import，定义 `--font-sans` / `--font-mono`，`:root` font-family 切换；删除 `.font-display`
- [x] 更新 `.section-kicker` / `.nav-link` / `.integration-card` / `.candidate-card` 样式块按 design.md §3 映射
- [x] 新增全局链接 / 引用块基础样式（绿链接 + hover 下划线；blockquote 绿竖线）
- 验证：`grep -n "red\|blue\|f3efe5\|171714\|KaiTi\|Noto Serif" web/src/index.css` 无残留；`pnpm -C web build` 通过

## Step 3 · 深色模式开关

- [x] `main.tsx` 启动读 `localStorage.theme`（缺省跟随系统）设 `document.documentElement.dataset.theme`
- [x] `app-shell.tsx` 侧栏底部加切换按钮（lucide Sun/Moon），点击翻转并持久化
- 验证：`pnpm -C web build` 通过；手动切换 `data-theme` 两模式 CSS 变量均生效

## Step 4 · 品牌出场

- [x] `index.html`：favicon 换 `/brand/yixing-logo-v2-favicon-32.png`（+16）
- [x] `app-shell.tsx`：REVEN 楷体字标 + 红方块 → `<img src="/brand/yixing-logo-v2-master.svg">`（深色用 mono-white，可用 `picture`/`data-theme` CSS 切换）+ Inter SemiBold「Reven」；底部小字改 `CODE, ONE STROKE AT A TIME.`
- 验证：`pnpm -C web build` 通过；浏览器走查 logo 无拉伸、深色切反白版

## Step 5 · 组件与页面清理

- [x] `components/ui/button.tsx`：default hover 去红；focus ring `--blue` → `--signal`；danger → `--danger`；outline hover `bg-white/50` → `var(--faint)`
- [x] 全仓 grep 清单逐项清零：`var(--red)`、`var(--red-soft)`、`var(--blue)`、`var(--line-strong)`、`white/50`、`black/5`、`font-display`
- [x] 页面标题/分区去彩色 emoji（如有），状态徽标按 design.md §3 上色
- [x] 相关快照/类名断言测试同步更新
- 验证：`pnpm -C web lint && pnpm -C web test && pnpm -C web build` 全绿

## Step 6 · 渲染器主题（`renderer/src/render.ts`）

- [x] `--md-primary-color` → `#00E676`
- [x] `wechatBaseCSS` 追加引用块（绿竖线 + 5% 灰底 + 倾斜）与代码块（`#0A0A0A` 底 / `#FAFAFA` 字 / 绿关键字 / JetBrains Mono 栈）规则
- 验证：`pnpm -C renderer test`（如有）与 `pnpm -C renderer build` 通过；`web` 全量测试仍绿

## Step 7 · 终验

- [x] `pnpm -C web lint && pnpm -C web test && pnpm -C web build && pnpm -C renderer build` 全绿
- [x] 残留扫描：`grep -rn "f3efe5\|b62a1d\|155cad\|0F4C81\|KaiTi\|Noto Serif" web/src renderer/src` 为空
- [x] 启动 dev server，浅/深两模式走查 4 页面（稿件 / 稿件详情 / RSS 候选 / 集成设置），单屏静态绿色元素 ≤ 3 处，截图存档到任务目录

## 回滚点

每个 Step 一个 commit（`refactor(web): ...` / `refactor(renderer): ...`），任一验证失败就地修复，修复两次仍失败 → 回滚该 Step 并重审 design.md 对应决策。
