import { Activity, BookOpenCheck, ContactRound, FolderKanban, Palette, PlugZap, Rss, Sparkles, Tags, Users, Wallet, type LucideIcon } from "lucide-react"
import type { ReactElement } from "react"
import { Navigate } from "react-router-dom"

import { LoginPage } from "@/features/auth/login-page"
import { BrandPage } from "@/features/brand/brand-page"
import { CrmPage } from "@/features/crm/crm-page"
import { CustomerDetailPage } from "@/features/crm/customer-detail-page"
import { FinanceLayout } from "@/features/finance/finance-layout"
import { FinanceLedgerPage } from "@/features/finance/finance-ledger-page"
import { FinanceOverviewPage } from "@/features/finance/finance-overview-page"
import { FinancePendingPage } from "@/features/finance/finance-pending-page"
import { IntegrationsPage } from "@/features/integrations/integrations-page"
import { ProjectsPage } from "@/features/projects/projects-page"
import { RssCandidatesPage } from "@/features/rss/rss-candidates-page"
import { RssKeywordsPage } from "@/features/rss/rss-keywords-page"
import { RssSourcesPage } from "@/features/rss/rss-sources-page"
import { SopsPage } from "@/features/sops/sops-page"
import { SystemPage } from "@/features/system/system-page"
import { TalentDetailPage } from "@/features/talents/talent-detail-page"
import { TalentsPage } from "@/features/talents/talents-page"

/**
 * 路由注册表：App 的路由表与 AppShell 的主导航共同消费这一个数组。
 * 加一个页面 = 在这里加一处数组项。
 *
 * - path 与 index 二选一：index 表示父级的默认子路由
 * - 带 label + icon 的条目出现在主导航；其余（详情页、重定向、通配符）只注册路由
 * - children 绝对 path → 平铺注册为兄弟路由，并构成主导航分组（如 RSS）；
 *   children 相对 path / index → 嵌套在父 element 的 <Outlet/>（如财务）
 * - bare 条目不包 AppShell（登录页）
 */
export interface RouteDef {
  path?: string
  index?: boolean
  label?: string
  icon?: LucideIcon
  element?: ReactElement
  children?: RouteDef[]
  bare?: boolean
}

export const routes: RouteDef[] = [
  { path: "/login", element: <LoginPage />, bare: true },
  { path: "/crm", label: "CRM", icon: ContactRound, element: <CrmPage /> },
  { path: "/crm/customers/:customerId", element: <CustomerDetailPage /> },
  { path: "/talents", label: "人才库", icon: Users, element: <TalentsPage /> },
  { path: "/talents/:talentId", element: <TalentDetailPage /> },
  {
    path: "/finance",
    label: "财务",
    icon: Wallet,
    element: <FinanceLayout />,
    children: [
      { index: true, element: <Navigate replace to="/finance/overview" /> },
      { path: "overview", element: <FinanceOverviewPage /> },
      { path: "ledger", element: <FinanceLedgerPage /> },
      { path: "pending", element: <FinancePendingPage /> },
    ],
  },
  { path: "/projects", label: "项目", icon: FolderKanban, element: <ProjectsPage /> },
  { path: "/sops", label: "SOP（标准作业流程）", icon: BookOpenCheck, element: <SopsPage /> },
  {
    path: "/rss",
    label: "RSS",
    icon: Rss,
    element: <Navigate replace to="/rss/sources" />,
    children: [
      { path: "/rss/candidates", label: "内容发现", icon: Sparkles, element: <RssCandidatesPage /> },
      { path: "/rss/sources", label: "RSS 源", icon: Rss, element: <RssSourcesPage /> },
      { path: "/rss/keywords", label: "RSS 关键词", icon: Tags, element: <RssKeywordsPage /> },
    ],
  },
  { path: "/brand", label: "品牌管理", icon: Palette, element: <BrandPage /> },
  { path: "/integrations", label: "集成设置", icon: PlugZap, element: <IntegrationsPage /> },
  { path: "/system", label: "系统状态", icon: Activity, element: <SystemPage /> },
  { path: "*", element: <Navigate replace to="/rss/candidates" /> },
]
