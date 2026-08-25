import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { LoginPage } from "@/features/auth/login-page"
import { CrmPage } from "@/features/crm/crm-page"
import { CustomerDetailPage } from "@/features/crm/customer-detail-page"
import { IntegrationsPage } from "@/features/integrations/integrations-page"
import { ArticleDetailPage } from "@/features/articles/article-detail-page"
import { ArticlesPage } from "@/features/articles/articles-page"
import { FinancePage } from "@/features/finance/finance-page"
import { PlaybooksPage } from "@/features/playbooks/playbooks-page"
import { ProjectsPage } from "@/features/projects/projects-page"
import { RssSettingsPage } from "@/features/rss/rss-settings-page"
import { RssCandidatesPage } from "@/features/rss/rss-candidates-page"
import { SystemPage } from "@/features/system/system-page"

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
        <Route element={<IntegrationsPage />} path="/integrations" />
        <Route element={<CrmPage />} path="/crm" />
        <Route element={<CustomerDetailPage />} path="/crm/customers/:customerId" />
        <Route element={<FinancePage />} path="/finance" />
        <Route element={<ProjectsPage />} path="/projects" />
        <Route element={<PlaybooksPage />} path="/playbooks" />
        <Route element={<RssSettingsPage />} path="/rss" />
        <Route element={<RssCandidatesPage />} path="/rss/candidates" />
        <Route element={<SystemPage />} path="/system" />
        <Route element={<Navigate replace to="/articles" />} path="*" />
      </Routes>
    </AppShell>
  )
}
