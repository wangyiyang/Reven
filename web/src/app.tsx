import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { LoginPage } from "@/features/auth/login-page"
import { CrmPage } from "@/features/crm/crm-page"
import { CustomerDetailPage } from "@/features/crm/customer-detail-page"
import { BrandPage } from "@/features/brand/brand-page"
import { IntegrationsPage } from "@/features/integrations/integrations-page"
import { ArticleDetailPage } from "@/features/articles/article-detail-page"
import { ArticlesPage } from "@/features/articles/articles-page"
import { FinanceLayout } from "@/features/finance/finance-layout"
import { FinanceLedgerPage } from "@/features/finance/finance-ledger-page"
import { FinanceOverviewPage } from "@/features/finance/finance-overview-page"
import { FinancePendingPage } from "@/features/finance/finance-pending-page"
import { SopsPage } from "@/features/sops/sops-page"
import { ProjectsPage } from "@/features/projects/projects-page"
import { RssKeywordsPage } from "@/features/rss/rss-keywords-page"
import { RssSourcesPage } from "@/features/rss/rss-sources-page"
import { RssCandidatesPage } from "@/features/rss/rss-candidates-page"
import { SystemPage } from "@/features/system/system-page"
import { TalentDetailPage } from "@/features/talents/talent-detail-page"
import { TalentsPage } from "@/features/talents/talents-page"

export function App() {
  return (
    <Routes>
      <Route element={<LoginPage />} path="/login" />
      <Route element={<ShellRoutes />} path="*" />
    </Routes>
  )
}

function ShellRoutes() {
  return (
    <AppShell>
      <Routes>
        <Route element={<ArticlesPage />} path="/articles" />
        <Route element={<ArticleDetailPage />} path="/articles/:articleId" />
        <Route element={<BrandPage />} path="/brand" />
        <Route element={<IntegrationsPage />} path="/integrations" />
        <Route element={<CrmPage />} path="/crm" />
        <Route element={<CustomerDetailPage />} path="/crm/customers/:customerId" />
        <Route element={<FinanceLayout />} path="/finance">
          <Route element={<Navigate replace to="/finance/overview" />} index />
          <Route element={<FinanceOverviewPage />} path="overview" />
          <Route element={<FinanceLedgerPage />} path="ledger" />
          <Route element={<FinancePendingPage />} path="pending" />
        </Route>
        <Route element={<ProjectsPage />} path="/projects" />
        <Route element={<SopsPage />} path="/sops" />
        <Route element={<Navigate replace to="/rss/sources" />} path="/rss" />
        <Route element={<RssSourcesPage />} path="/rss/sources" />
        <Route element={<RssKeywordsPage />} path="/rss/keywords" />
        <Route element={<RssCandidatesPage />} path="/rss/candidates" />
        <Route element={<SystemPage />} path="/system" />
        <Route element={<TalentsPage />} path="/talents" />
        <Route element={<TalentDetailPage />} path="/talents/:talentId" />
        <Route element={<Navigate replace to="/articles" />} path="*" />
      </Routes>
    </AppShell>
  )
}
