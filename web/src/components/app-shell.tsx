import { Activity, FileText, Moon, PlugZap, Rss, Sparkles, Sun } from "lucide-react"
import { useState, type ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { Toaster } from "sonner"

import { getTheme, toggleTheme, type Theme } from "@/lib/theme"
import { cn } from "@/lib/utils"

const navigation = [
  { to: "/articles", label: "稿件", icon: FileText },
  { to: "/rss/candidates", label: "RSS 候选", icon: Sparkles },
  { to: "/rss", label: "RSS 配置", icon: Rss, end: true },
  { to: "/integrations", label: "集成设置", icon: PlugZap },
  { to: "/system", label: "系统状态", icon: Activity },
]

export function AppShell({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getTheme)
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="z-20 border-b border-[var(--line)] bg-[var(--bg)] lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex h-full items-center justify-between px-5 py-4 lg:flex-col lg:items-stretch lg:px-6 lg:py-8">
          <NavLink aria-label="Reven 首页" className="group flex items-center gap-2.5" to="/articles">
            <img alt="" className="h-8 w-8 dark:hidden" src="/brand/yixing-logo-v2-master.svg" />
            <img alt="" className="hidden h-8 w-8 dark:block" src="/brand/yixing-logo-v2-mono-white.svg" />
            <span className="text-xl font-semibold tracking-[-0.02em]">Reven</span>
          </NavLink>
          <nav aria-label="内容工作台主导航" className="lg:my-auto">
            <ul className="flex gap-1 lg:flex-col lg:gap-2">
              {navigation.map(({ to, label, icon: Icon, end }) => (
                <li key={to}>
                  <NavLink
                    aria-label={label}
                    className={({ isActive }) => cn(
                      "nav-link flex min-h-11 items-center gap-3 px-3 text-sm font-semibold",
                      isActive && "active",
                    )}
                    end={end}
                    to={to}
                  >
                    <Icon aria-hidden size={17} />
                    <span className="hidden sm:inline">{label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="hidden lg:flex lg:flex-col lg:gap-5">
            <button
              aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
              className="flex min-h-9 w-fit items-center gap-2 border border-[var(--line)] px-3 font-mono text-[11px] tracking-[0.08em] text-[var(--muted)] uppercase transition-colors hover:border-[var(--signal)] hover:text-[var(--signal)]"
              onClick={() => setTheme(toggleTheme())}
              type="button"
            >
              {theme === "dark" ? <Sun aria-hidden size={14} /> : <Moon aria-hidden size={14} />}
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <p className="font-mono text-[10px] leading-5 tracking-[0.13em] text-[var(--muted)] uppercase">
              CODE, ONE STROKE<br />AT A TIME.
            </p>
          </div>
        </div>
      </aside>
      <div className="min-w-0">{children}</div>
      <Toaster position="bottom-right" theme={theme} />
    </div>
  )
}
