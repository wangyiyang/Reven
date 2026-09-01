# Design · 应用界面品牌 VI 重构

## 总体思路

当前组件全部通过 Tailwind 任意值引用 CSS 变量（`bg-[var(--ink)]`），因此重构以**令牌层重写**为支点：先替换 `index.css` 的变量与字体，再逐组件清理硬编码色（`--red` / `--blue` / `white/50` 等），最后改渲染器主题与品牌出场（Logo / favicon / 深色模式）。

## 1. 设计令牌（`web/src/index.css` 重写）

### 1.1 颜色

| 令牌 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--paper` → `--bg` | `#FAFAFA` | `#0A0A0A` | 页面背景 |
| `--ink` | `#0A0A0A` | `#FAFAFA` | 主文字 / 主按钮 |
| `--signal`（新增） | `#00E676` | `#00E676` | 终端绿点睛：链接、hover、CTA 细节、状态灯 |
| `--muted` | `rgb(10 10 10 / 0.5)` | `rgb(250 250 250 / 0.5)` | 次要文字（VI：中间色只用主色透明度） |
| `--faint`（新增） | `rgb(10 10 10 / 0.1)` | `rgb(250 250 250 / 0.1)` | 分隔底、hover 底 |
| `--line` | `#E5E5E5` | `rgb(250 250 250 / 0.14)` | 1px 细边框（博客规范钦定 `#E5E5E5`） |

- **废除**：`--red` / `--red-soft` / `--blue` / `--line-strong` / 纸纹网格背景。
- **语义色例外（待审）**：VI 禁第 4 色，但表单错误 / 危险操作需要可辨识的错误色。提案：保留单一功能红 `--danger: #D92D20`，仅用于错误提示与 danger 按钮，**绝不用于装饰**。若要求 VI 绝对纯净，则错误态改用碳黑 + 图标 + 文字说明（可用性下降，不推荐）。
- 成功态用 `--signal` 兼任，不另立绿色。

### 1.2 字体

本地打包（离线可用，不依赖 CDN），pnpm 依赖：`@fontsource/noto-sans-sc`（400/500/700）、`@fontsource/inter`（400/600）、`@fontsource/jetbrains-mono`（400）。

```
--font-sans: "Inter", "Noto Sans SC", "Source Han Sans SC", system-ui, sans-serif
--font-mono: "JetBrains Mono", ui-monospace, monospace
```

- 正文/标题统一 `--font-sans`，以字重建层级（H 700 / 强调 600 / 正文 400），**删除** `.font-display`（楷体）。
- `.section-kicker`、数据/状态文字、Logo 旁小字用 `--font-mono`。
- 字号阶梯沿用 VI 参考：H1 32 / H2 24 / H3 20 / 正文 16（web 现有 14px 正文保留，属应用 UI 密度需求，不机械套博客规范）；行高标题 1.3、正文 1.7。

### 1.3 深色模式

- 实现：`html[data-theme="dark"]` + `prefers-color-scheme` 媒体查询兜底，默认跟随系统。
- 侧栏底部放切换按钮（太阳/月亮图标，lucide 已有），选择写入 `localStorage`，`main.tsx` 启动时读取并设 `data-theme`。
- 深色下 Logo 自动切 `mono-white.svg`；终端绿不变。

## 2. Logo 与品牌出场

1. 资产拷贝：`yixing-logo-v2-{master,mono-white,mono-black}.svg`、`favicon-{16,32}.png` → `web/public/brand/`。
2. `index.html`：favicon 换 32/16 PNG；`<title>` 保持产品名。
3. `app-shell.tsx` 侧栏品牌位：`{翊}` master.svg（≥32px，遵守安全间距）+ 「Reven」字标（Inter SemiBold，JetBrains Mono 小字 `1 LINE CODE` 可选）。
   - **决策点（待审）**：产品名保留「Reven」，不替换为「翊行代码」——应用是工具产品，品牌 VI 管视觉不管改名。侧栏底部 "Editorial Publishing Workbench" 改为 `CODE, ONE STROKE AT A TIME.`（英文 tagline，JetBrains Mono 小字）。
4. 侧栏黑边改为 `--line` 细边；导航 active 态沿用反转药丸（ink 底 paper 字），hover 文字变绿。

## 3. 组件与页面映射规则

| 现状 | 改法 |
|---|---|
| `button` default hover `--red` | hover 保持碳黑，focus ring `--blue` → `--signal`；default 按钮可在文字后加 4px 绿方块点睛（主 CTA 唯一绿元素） |
| `button` danger `--red` | 改用 `--danger`（语义例外） |
| `.section-kicker` 蓝色 mono 标签 | 改 `--muted` 色 + 前缀 6×6 绿方块（JetBrains Mono，保持 uppercase tracking） |
| `.integration-card::after` 红色 hover 条 | 改 `--signal` |
| `.candidate-card` 硬偏移投影（5px/8px 红调） | 删除硬投影，改 1px `--line` 边框 + hover 边框变 `--signal`（博客规范卡片规则），去除 translate 位移 |
| `hover:bg-white/50` / `bg-black/5` | 统一 `hover:bg-[var(--faint)]` |
| 正文链接 | `color: var(--signal)` + hover 下划线（VI 铁律：不变色） |
| 引用块 / blockquote | 左侧 4px `--signal` 竖线 + `--faint` 底 |
| 状态徽标（已同步/失败等） | 成功 `--signal`，失败 `--danger`，其余 `--muted` 描边 |
| 彩色 emoji | 页面标题/分区无彩色 emoji，统一 lucide 线性图标 |

单屏自检：装饰性绿色元素 ≤ 3 处（kicker 方块 + hover 态 + CTA 点睛）。链接、粗体、状态徽标属 VI 批准的功能性用法（「正文里绿仅链接 + 极少加粗」），不计入装饰配额。

**链接着色口径**：文字型链接绿 + hover 下划线；按钮化链接（带边框的 action link，如「打开 Notion」「查看原文」）按按钮规则用 `--ink` 着色、`hover:no-underline`。

## 4. 渲染器主题（`renderer/src/render.ts`）

仅改自定义 CSS 块，不碰 vendor 主题表：

- `--md-primary-color: #0F4C81` → `#00E676`（引用块左竖线、粗体、强调自动变绿）。
- 标题全部保持碳黑：h1 下边框改碳黑、h2 移除绿底填充、h3 左边框改碳黑、h4–h6 颜色改碳黑（实现后的最终口径，与 VI「标题无信号色」一致）。
- 链接：`#576b95` → `#00E676` + 字重 600。
- `wechatBaseCSS` 追加：引用块 `border-left: 4px solid #00E676` + 5% 灰底 + 倾斜；代码块底 `#0A0A0A` / 字 `#FAFAFA` / 关键字 `#00E676`，字体栈加 JetBrains Mono；行内 code 改碳黑字 + 6% 碳黑底 + `#E5E5E5` 边；图片加 1px `#E5E5E5` 边。
- 微信端无 JetBrains Mono 时回退系统等宽，可接受（渲染产物规范见博客子页 §2）。

## 5. 兼容与回滚

- 纯样式变更，无 API / 数据契约改动；git 单分支逐 step 提交，任一 step 可独立 revert。
- 测试快照若含 class 断言需同步更新；视觉回归靠构建后人工走查四个页面（稿件 / 稿件详情 / RSS 候选 / 集成）。

## 风险

1. **Noto Sans SC 打包体积**：@fontsource 按 unicode-range 分包，浏览器按需加载，构建产物增大但运行加载可控。
2. **`#00E676` 白底对比度**（约 1.6:1）：正文链接遵循 VI 仍用绿，但通过加粗/下划线保证可辨；小字提示不用绿。
3. **深色模式覆盖不全**：组件若残留硬编码浅色（white/50 等）会在深色下破相——实施时用 grep 清单兜底。
