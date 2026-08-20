import { Activity, FileText, FolderKanban, LogOut, Moon, PlugZap, Rss, Sparkles, Sun, Wallet } from "lucide-react"
import { useState, type ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { Toaster } from "sonner"

import { apiRequest } from "@/lib/api"
import { getTheme, toggleTheme, type Theme } from "@/lib/theme"
import { cn } from "@/lib/utils"

async function logout() {
  try {
    await apiRequest("/auth/logout", { method: "POST" })
  } catch {
    // 会话可能已失效，照常回到登录页
  }
  window.location.assign("/login")
}

const navigation = [
  { to: "/articles", label: "稿件", icon: FileText },
  { to: "/finance", label: "财务", icon: Wallet },
  { to: "/projects", label: "项目", icon: FolderKanban },
  { to: "/rss/candidates", label: "RSS 候选", icon: Sparkles },
  { to: "/rss", label: "RSS 配置", icon: Rss, end: true },
  { to: "/integrations", label: "集成设置", icon: PlugZap },
  { to: "/system", label: "系统状态", icon: Activity },
]

export function AppShell({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getTheme)
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="z-20 border-b border-[var(--line)] bg-[var(--panel)] lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
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
          <div className="flex lg:flex-col lg:gap-3">
            <button
              aria-label="退出登录"
              className="flex min-h-9 w-fit items-center gap-2 rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm text-[var(--muted)] transition-colors hover:text-[var(--ink)]"
              onClick={() => void logout()}
              type="button"
            >
              <LogOut aria-hidden size={14} />
              退出
            </button>
            <button
              aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
              className="flex min-h-9 w-fit items-center gap-2 rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm text-[var(--muted)] transition-colors hover:text-[var(--ink)]"
              onClick={() => setTheme(toggleTheme())}
              type="button"
            >
              {theme === "dark" ? <Sun aria-hidden size={14} /> : <Moon aria-hidden size={14} />}
              {theme === "dark" ? "浅色" : "深色"}
            </button>
          </div>
        </div>
      </aside>
      <div className="min-w-0">{children}</div>
      <Toaster position="bottom-right" theme={theme} />
    </div>
  )
}
