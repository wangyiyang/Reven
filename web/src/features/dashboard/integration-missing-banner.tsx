import { X } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router-dom"

import {
  loadDismissedMissingKeys,
  missingIntegrationKeys,
  missingIntegrationLabel,
  saveDismissedMissingKeys,
  type DashboardIntegrationSummary,
} from "./dashboard-api"

/**
 * 集成配置缺失横幅：列出全部当前缺失项（含 COS）；可关闭。
 * 关闭集合持久化在 localStorage；当前缺失集合 ⊄ 已关闭集合时重新弹出。
 */
export function IntegrationMissingBanner({ summary }: { summary: DashboardIntegrationSummary }) {
  const missingKeys = missingIntegrationKeys(summary)
  const [dismissed, setDismissed] = useState<string[]>(loadDismissedMissingKeys)
  const visible = missingKeys.some((key) => !dismissed.includes(key))
  if (missingKeys.length === 0 || !visible) return null

  function dismiss() {
    saveDismissedMissingKeys(missingKeys)
    setDismissed(missingKeys)
  }

  return (
    <section aria-label="集成配置缺失提醒" className="mb-6 rounded-lg border border-[var(--danger)] bg-[var(--faint)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--ink)]">
            {missingKeys.length} 项集成未配置，相关能力不可用
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm text-[var(--muted)]">
            {missingKeys.map((key) => (
              <li key={key}>{missingIntegrationLabel(key)}</li>
            ))}
          </ul>
          <Link className="mt-3 inline-block text-sm" to="/integrations">
            前往集成设置
          </Link>
        </div>
        <button
          aria-label="关闭集成缺失提醒"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--muted)] transition-colors hover:bg-[var(--line)] hover:text-[var(--ink)]"
          onClick={dismiss}
          type="button"
        >
          <X aria-hidden size={16} />
        </button>
      </div>
    </section>
  )
}
