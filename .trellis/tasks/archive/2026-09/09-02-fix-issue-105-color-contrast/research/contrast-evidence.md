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

## Browser audit after implementation

Audit environment: local Vite app at 1440×1000, isolated browser session,
axe-core 4.10.3 `color-contrast` rule, deterministic local API fixtures.

| Route / state | Light | Dark |
|---|---|---|
| `/articles` including published badges, filters, and shared sidebar | 0 violations | 0 violations |
| Primary filter hover after transition | 0 violations | 0 violations |
| `/crm` including shared sidebar and muted content | 0 violations | 0 violations |
| Destructive confirmation hover | 0 violations | 0 violations |
| `/login` enabled primary-button hover | 0 violations | 0 violations |

The first light primary-hover attempt exposed a serious 4.49:1 violation:
whole-control `opacity: 0.9` produced effective colors `#EBF3F8` on
`#2374AC`. The fix replaces opacity hover with a `-1px` translation, preserving
the approved token pair at opacity 1. Browser verification observed
`translate: 0px -1px` in both themes.

Keyboard focus on the article filter is `:focus-visible` in both themes. The
computed ring uses a 2px page-background offset plus a 2px `--signal` ring.

Reviewer follow-up found that Tailwind's generated hover rule initially won
over the shared button's active translation. The active utility now has
explicit priority on shared and login primary buttons. Browser verification
confirms both controls translate to `0px 1px` while pressed, retain opacity 1
and the approved foreground/background pair; disabled shared controls remain
identifiable at opacity 0.45.

Chrome/axe reports the resizable CRM notes textarea as one `incomplete`
(`elmPartiallyObscured`) because its native resize affordance overlaps the
element. It is not a violation. Manual computed-style verification confirms
the placeholder is now opaque `#6B6A67` in light mode and `#A7A7A4` in dark
mode, matching the 5.41:1 and 7.29:1 page-background ratios above.

Screenshots:

- `/tmp/reven-105-articles-light.png`
- `/tmp/reven-105-articles-dark.png`
- `/tmp/reven-105-crm-light.png`
- `/tmp/reven-105-crm-dark.png`
