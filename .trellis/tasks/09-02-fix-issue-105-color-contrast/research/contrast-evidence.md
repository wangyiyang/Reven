# #105 Contrast Evidence

## Authoritative baseline

- PR #40 (`9c9b0f8`, merged 2026-08-19) intentionally replaced the earlier terminal-green poster UI with the current Notion-style blue/gray workbench.
- The user confirmed on 2026-09-02 that #105 must retain the current Notion blue/gray visual direction.
- `.trellis/spec/web/frontend/brand-vi.md` predates PR #40 and is stale where it mandates terminal green; it must not override the newer merged product decision.

## Contrast calculations

Calculated with WCAG relative luminance:

| Pair | Ratio |
|---|---:|
| `#0B65A3` on `#FFFFFF` | 6.17:1 |
| `#0B65A3` on `#F7F7F5` | 5.75:1 |
| `#6EB6E8` on `#191919` | 7.97:1 |
| `#6EB6E8` on `#202020` | 7.39:1 |
| `#6B6A67` on `#FFFFFF` | 5.41:1 |
| `#6B6A67` on `#F7F7F5` | 5.04:1 |
| `#A7A7A4` on `#191919` | 7.29:1 |
| `#A7A7A4` on `#202020` | 6.76:1 |
| `#FFFFFF` on `#0B65A3` | 6.17:1 |
| `#191919` on `#6EB6E8` | 7.97:1 |

Current failing pairs include `#2383E2` on white (3.88:1), `#9B9A97` on white (2.81:1), and white on `#529CCA` (3.01:1).
