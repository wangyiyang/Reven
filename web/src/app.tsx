import { Navigate, Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { LoginPage } from "@/features/auth/login-page"
import { IntegrationsPage } from "@/features/integrations/integrations-page"
import { ArticleDetailPage } from "@/features/articles/article-detail-page"
import { ArticlesPage } from "@/features/articles/articles-page"
import { RssSettingsPage } from "@/features/rss/rss-settings-page"
import { RssCandidatesPage } from "@/features/rss/rss-candidates-page"

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
        <Route element={<RssSettingsPage />} path="/rss" />
        <Route element={<RssCandidatesPage />} path="/rss/candidates" />
        <Route element={<Placeholder eyebrow="Operations" title="系统状态" />} path="/system" />
        <Route element={<Navigate replace to="/articles" />} path="*" />
      </Routes>
    </AppShell>
  )
}

function Placeholder({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <main className="page-enter grid min-h-[75vh] place-items-center px-6">
      <div className="text-center">
        <p className="section-kicker justify-center">{eyebrow}</p>
        <h1 className="mt-4 text-6xl font-bold">{title}</h1>
        <p className="mt-5 text-sm text-[var(--muted)]">此页面将在下一阶段接入。</p>
      </div>
    </main>
  )
}
