# Design · #105 Notion 蓝灰主题 WCAG AA

## Token Contract

| Token | Light | Dark | 最低实测对比度 |
|---|---|---|---|
| `--signal` | `#0B65A3` | `#6EB6E8` | 5.75:1 / 7.39:1（panel） |
| `--muted` | `#6B6A67` | `#A7A7A4` | 5.04:1 / 6.76:1（panel） |
| `--danger` | `#B42318` | `#FF7B72` | 6.57:1 / 6.41:1+ |
| `--on-signal` | `#FFFFFF` | `#191919` | 6.17:1 / 7.97:1 |
| `--on-danger` | `#FFFFFF` | `#191919` | 6.57:1 / 6.97:1 |

保留 PR #40 的 Notion 蓝灰方向。`--signal` 继续承担链接、状态、focus 和按钮背景；按钮文字改用主题相关的 `--on-signal`，解决“浅色背景需深蓝、深色背景需浅蓝”与固定白字冲突。danger 同理。

## Scope

- 更新 `index.css` token。
- 更新共享 Button、登录按钮和 danger hover 前景。
- 清理 finance 固定 `text-emerald-600`，使用可访问语义色。
- 以 axe-core 在两种主题审计 `/articles`、`/crm` 及共用侧栏。
- 更新过期 Brand VI spec，记录 Notion 主题是当前契约。

## Rollback

仅涉及 CSS token、类名与规范，无数据或 API 影响，可整 commit 回退。
