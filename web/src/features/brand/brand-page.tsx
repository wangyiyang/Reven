import { useQueryClient } from "@tanstack/react-query"
import { RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { AssetsSection } from "./assets-section"
import { ProfileSection } from "./profile-section"
import { TemplatesSection } from "./templates-section"

export function BrandPage() {
  const client = useQueryClient()
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["brand-profile"] }),
      client.invalidateQueries({ queryKey: ["brand-assets"] }),
      client.invalidateQueries({ queryKey: ["brand-template"] }),
    ])
  }
  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4 border-b border-[var(--line)] pb-6">
        <div>
          <h1 className="text-2xl font-semibold">品牌管理</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">集中管理品牌档案、图片素材与渠道模板版本。</p>
        </div>
        <Button onClick={refresh} size="sm" variant="ghost"><RefreshCcw aria-hidden size={14} />刷新</Button>
      </header>
      <div className="grid gap-6">
        <ProfileSection />
        <AssetsSection />
        <TemplatesSection />
      </div>
    </main>
  )
}
