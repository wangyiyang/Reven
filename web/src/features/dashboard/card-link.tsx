import type { ReactNode } from "react"
import { Link } from "react-router-dom"

/**
 * 数字卡的整卡跳转容器：main a 全局样式会给链接上 signal 色与 hover 下划线，
 * 整卡链接需显式还原为中性文本样式。
 */
export function CardLink({ to, label, children }: { to: string; label: string; children: ReactNode }) {
  return (
    <Link
      aria-label={label}
      className="block h-full rounded-lg text-[var(--ink)] no-underline transition-shadow hover:shadow-md hover:no-underline"
      to={to}
    >
      {children}
    </Link>
  )
}
