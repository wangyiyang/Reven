# Web Brand and Accessible Color Contract

## 1. Scope / Trigger

Use this contract whenever changing colors, theme tokens, shared controls,
status badges, navigation, or light/dark behavior in `@reven/web`.

The current product direction is the compact Notion-style blue/gray workbench
introduced by PR #40 (`9c9b0f8`) and confirmed for Issue #105. Do not restore
the earlier terminal-green poster UI. The WeChat renderer has an independent
green output theme in `renderer/src/render.ts`; it does not define web app
tokens and is outside this contract.

## 2. Signatures

`web/src/index.css` owns these CSS custom properties:

| Token | Light (`:root`) | Dark (`html[data-theme="dark"]`) | Purpose |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `#191919` | Page and input background |
| `--panel` | `#F7F7F5` | `#202020` | Sidebar and panel background |
| `--ink` | `#37352F` | `#D4D4D2` | Primary text |
| `--signal` | `#0B65A3` | `#6EB6E8` | Links, focus, active status, primary backgrounds |
| `--on-signal` | `#FFFFFF` | `#191919` | Text on a `--signal` background |
| `--muted` | `#6B6A67` | `#A7A7A4` | Secondary text on both page and panel |
| `--faint` | `rgb(55 53 47 / 0.06)` | `rgb(255 255 255 / 0.06)` | Subtle hover/background tint |
| `--line` | `#E9E9E7` | `#2F2F2F` | Hairline borders |
| `--danger` | `#B42318` | `#FF7B72` | Error/destructive text and background |
| `--on-danger` | `#FFFFFF` | `#191919` | Text on a `--danger` background |

Dark mode is driven only by `html[data-theme="dark"]`. `web/src/lib/theme.ts`
owns initialization and toggling, and `main.tsx` initializes the theme before
rendering. Storage access must remain guarded because browser storage can
throw.

## 3. Contracts

Normal text below the WCAG large-text threshold must have at least 4.5:1
contrast in its rendered state. Non-text UI and large text must meet their
applicable WCAG AA thresholds. Approved token pairs intentionally retain
margin above 4.5:1:

| Pair | Light | Dark |
|---|---:|---:|
| `--signal` on `--bg` | 6.17:1 | 7.97:1 |
| `--signal` on `--panel` | 5.75:1 | 7.39:1 |
| `--muted` on `--bg` | 5.41:1 | 7.29:1 |
| `--muted` on `--panel` | 5.04:1 | 6.76:1 |
| `--on-signal` on `--signal` | 6.17:1 | 7.97:1 |
| `--on-danger` on `--danger` | 6.57:1 | at least 6.41:1 |

Use `--on-signal` for text on primary filled controls and `--on-danger` for
text on destructive filled/hover controls. A single foreground such as white
cannot satisfy both the dark and light signal backgrounds.

Do not lower the opacity of an entire filled control on hover. Element opacity
blends both its text and background with the surface; the nominal token ratio
therefore does not describe the rendered result. Primary controls use a small
vertical translation for hover feedback while preserving their color pair.
Disabled controls may use reduced opacity because inactive controls are exempt
from the normal text contrast criterion, but they must remain identifiable.

Use semantic tokens instead of fixed palette utilities such as
`text-emerald-*` for product statuses. Links, published/success badges, filter
buttons, sidebar labels, and focus indicators must all remain legible in both
themes. Keep the Notion-style neutral surfaces, compact density, one-pixel
borders, and blue signal direction; this accessibility contract is not
permission for an unrelated rebrand.

Fonts remain locally bundled through `@fontsource`: Inter and Noto Sans SC for
the UI, JetBrains Mono for code/data where already used. Do not add CDN font
links.

## 4. Validation & Error Matrix

| Condition | Expected behavior |
|---|---|
| Text uses `--muted` on page or panel | Contrast is at least 4.5:1 in light and dark themes |
| Text is placed on `--signal` | Use `--on-signal`, never a fixed light/dark foreground |
| Text is placed on `--danger` | Use `--on-danger` |
| Primary control is hovered | Feedback remains visible without changing the foreground/background contrast pair |
| Destructive outline control is hovered | Background becomes `--danger` and text becomes `--on-danger` |
| A status needs success/published emphasis | Use `--signal`; do not introduce a fixed green utility |
| A new color pair falls below 4.5:1 for normal text | Reject it or assign separate foreground/background tokens |
| Theme storage is unavailable | Keep the current session theme; never crash initialization or toggling |

## 5. Good / Base / Bad Cases

- Good: a light primary button uses `#0B65A3` with white text; the dark version
  uses `#6EB6E8` with `#191919` text.
- Good: sidebar secondary text uses `--muted`, reaching at least 5.04:1 on the
  panel in both themes.
- Base: primary body text uses `--ink` and neutral surfaces keep the current
  Notion-style hierarchy.
- Bad: `bg-[var(--signal)] text-white`; it passes in light mode but fails on the
  light-blue dark-mode signal.
- Bad: `hover:opacity-*` on a filled button; rendered blending can reduce a
  nominally safe pair below 4.5:1.
- Bad: restoring `#00E676` as web signal; it is both the retired visual
  direction and insufficient for normal text on the light surface.

## 6. Tests Required

- Token tests must assert the exact light/dark values for `--signal`,
  `--on-signal`, `--muted`, `--danger`, and `--on-danger`.
- Shared Button and login tests must assert semantic foreground tokens and
  reject whole-control opacity hover on signal-filled controls.
- Feature tests must prevent fixed palette regressions for semantic badges.
- Run the web unit suite, ESLint, TypeScript build, and `git diff --check`.
- In a real browser, audit `/articles`, `/crm`, and the shared sidebar in both
  themes with axe-core's `color-contrast` rule. There must be no serious or
  critical violations.
- Browser checks must include primary hover, destructive hover, and keyboard
  focus; inspect screenshots to confirm the Notion blue/gray direction remains
  intact.

## 7. Wrong vs Correct

### Wrong

```tsx
<button className="bg-[var(--signal)] text-white hover:opacity-90">
  保存
</button>
```

The fixed white foreground fails on the dark theme, and whole-control opacity
changes the effective contrast of both colors.

### Correct

```tsx
<button className="bg-[var(--signal)] text-[var(--on-signal)] hover:-translate-y-px">
  保存
</button>
```

The theme selects a matched foreground/background pair, while hover feedback
does not reduce text contrast.
