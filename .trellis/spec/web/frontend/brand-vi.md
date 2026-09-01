# Brand VI Design Tokens (web)

> Executable contract for the 翊行代码 VI v2.1 visual system in `@reven/web`.
> Source of truth: Notion「YY · Personal Brand Prompt Kit」VI 核心规范. Implemented in `web/src/index.css` (2026-08, task `08-12-brand-vi-refactor`).

## Token Contract

| Token | Light | Dark (`html[data-theme="dark"]`) | Usage |
|---|---|---|---|
| `--bg` | `#FAFAFA` | `#0A0A0A` | Page background |
| `--ink` | `#0A0A0A` | `#FAFAFA` | Primary text, primary buttons, borders-strong |
| `--signal` | `#00E676` | `#00E676` (same) | Terminal green accents ONLY: links, hover, focus ring, small status squares, kicker prefix |
| `--muted` | `rgb(10 10 10 / 0.5)` | `rgb(250 250 250 / 0.5)` | Secondary text |
| `--faint` | `rgb(10 10 10 / 0.1)` | `rgb(250 250 250 / 0.1)` | Hover/divider backgrounds |
| `--line` | `#E5E5E5` | `rgb(250 250 250 / 0.14)` | 1px hairline borders |
| `--danger` | `#D92D20` | same | Errors/destructive actions ONLY (user-approved semantic exception) |
| `--font-sans` | `"Inter", "Noto Sans SC", "Source Han Sans SC", system-ui, sans-serif` | — | All body/headings (hierarchy via weight 400/600/700) |
| `--font-mono` | `"JetBrains Mono", ui-monospace, monospace` | — | Kickers, data, status, tagline |

Fonts are bundled via `@fontsource/{inter,jetbrains-mono,noto-sans-sc}` imports at the top of `index.css`. Never use a CDN link.

## Theming Mechanics

- Dark mode is driven **only** by `html[data-theme="dark"]`; `@custom-variant dark` in `index.css` wires Tailwind `dark:` utilities to it.
- `web/src/lib/theme.ts` owns init/toggle; `main.tsx` calls `initTheme()` before render; `localStorage` access MUST stay try/catch-guarded (Safari private mode throws).
- Sonner `<Toaster theme={theme}>` must follow app theme (it lives in `AppShell`, not `main.tsx`).

## Forbidden Patterns (VI 铁律)

- ❌ New brand colors (4th color incl. gray) — mid-tones = carbon/off-white alpha only.
- ❌ `--signal` on large fills, glow, neon, gradients, text > 3 lines. Decorative green ≤ 3 elements/screen; links/bold/status badges are functional green and don't count.
- ❌ Serif/kaiti/calligraphy fonts (Noto Serif SC, KaiTi, STKaiti, Songti), paper-texture backgrounds, colorful emoji in page chrome (use lucide).
- ❌ Headings in `--signal` or with green fills.

## Conventions

- Text links: `color: var(--signal)` + `underline` on hover (global rule in `index.css` covers `main a`).
- Button-styled links (bordered action links like「打开 Notion」/「查看原文」): `--ink` color + `hover:no-underline`.
- Cards: 1px `var(--line)` border, hover border → `var(--signal)`. No hard offset shadows (neubrutalism is off-brand).
- Status badges: success `--signal`, failure `--danger`, pending/working `--muted` outline.
- Logo: `/brand/yixing-logo-v2-{master,mono-white}.svg` pair switched via `dark:hidden` / `hidden dark:block`; never restyle/recolor the SVG; min 32px.

## Renderer (WeChat output) Contract

See `renderer/src/render.ts`: `--md-primary-color: #00E676`; headings always carbon (h1/h3 carbon borders, h2 no fill); quote = 4px green left bar + 5% gray bg + italic; code block = `#0A0A0A` bg + `#FAFAFA` text + green `hljs-keyword`. Regression guard: `renderer/tests/render-brand.test.ts`.
