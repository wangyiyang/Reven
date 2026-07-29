import { Activity, FileText, PlugZap } from "lucide-react"
import type { ReactNode } from "react"
import { NavLink } from "react-router-dom"

import { cn } from "@/lib/utils"

const navigation = [
  { to: "/articles", label: "稿件", icon: FileText },
  { to: "/integrations", label: "集成设置", icon: PlugZap },
  { to: "/system", label: "系统状态", icon: Activity },
]

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="z-20 border-b border-[var(--ink)] bg-[var(--paper)] lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex h-full items-center justify-between px-5 py-4 lg:flex-col lg:items-stretch lg:px-6 lg:py-8">
          <NavLink className="group flex items-baseline gap-2" to="/articles">
            <span className="font-display text-3xl tracking-[-0.05em]">REVEN</span>
            <span className="h-2 w-2 bg-[var(--red)] transition-transform group-hover:rotate-45" aria-hidden />
          </NavLink>
          <nav aria-label="主导航" className="lg:my-auto">
            <ul className="flex gap-1 lg:flex-col lg:gap-2">
              {navigation.map(({ to, label, icon: Icon }) => (
                <li key={to}>
                  <NavLink
                    className={({ isActive }) => cn(
                      "nav-link flex min-h-11 items-center gap-3 px-3 text-sm font-semibold",
                      isActive && "active",
                    )}
                    to={to}
                  >
                    <Icon aria-hidden size={17} />
                    <span className="hidden sm:inline">{label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <p className="hidden text-[10px] leading-5 tracking-[0.13em] text-[var(--muted)] uppercase lg:block">
            Editorial<br />Publishing<br />Workbench
          </p>
        </div>
      </aside>
      <div className="min-w-0">{children}</div>
    </div>
  )
}
