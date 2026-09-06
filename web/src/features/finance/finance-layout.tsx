import { useState } from "react"
import { NavLink, Outlet } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { EntryFormDrawer } from "./entry-form-drawer"
import type { EntryFormVariant } from "./finance-utils"

const ACTIONS: { variant: EntryFormVariant; label: string; primary?: boolean }[] = [
  { variant: "income-settled", label: "记收入", primary: true },
  { variant: "expense-settled", label: "记支出" },
  { variant: "receivable", label: "新增待收" },
  { variant: "payable", label: "新增待付" },
]

const TABS = [
  { to: "/finance/overview", label: "概览" },
  { to: "/finance/ledger", label: "收支流水" },
  { to: "/finance/pending", label: "待收待付" },
]

export function FinanceLayout() {
  const [drawerVariant, setDrawerVariant] = useState<EntryFormVariant | null>(null)

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">财务</h1>
        <p className="text-sm text-[var(--muted)]">看本月经营、查收支流水、跟进待收待付。</p>
      </div>
      <div aria-label="财务操作" className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        {ACTIONS.map((action) => (
          <Button
            key={action.variant}
            onClick={() => setDrawerVariant(action.variant)}
            type="button"
            variant={action.primary ? "default" : "outline"}
          >
            {action.label}
          </Button>
        ))}
      </div>
      <nav aria-label="财务子页面" className="flex gap-1 border-b border-[var(--line)]">
        {TABS.map((tab) => (
          <NavLink
            className={({ isActive }) => cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-semibold transition-colors",
              isActive
                ? "border-[var(--signal)] text-[var(--ink)]"
                : "border-transparent text-[var(--muted)] hover:text-[var(--ink)]",
            )}
            key={tab.to}
            to={tab.to}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
      <EntryFormDrawer
        onClose={() => setDrawerVariant(null)}
        open={drawerVariant !== null}
        variant={drawerVariant ?? "income-settled"}
      />
    </main>
  )
}
