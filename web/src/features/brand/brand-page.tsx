import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCcw, UploadCloud } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { AssetsSection } from "./assets-section"
import { fetchImportRuns, runNotionImport } from "./brand-api"
import { ProfileSection } from "./profile-section"
import { TemplatesSection } from "./templates-section"

export function BrandPage() {
  const client = useQueryClient()
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["brand-profile"] }),
      client.invalidateQueries({ queryKey: ["brand-assets"] }),
      client.invalidateQueries({ queryKey: ["brand-template"] }),
      client.invalidateQueries({ queryKey: ["brand-import-runs"] }),
    ])
  }
  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4 border-b border-[var(--line)] pb-6">
        <div>
          <h1 className="text-2xl font-semibold">品牌与发布</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">品牌档案、素材与渠道模板版本化管理；发布只影响之后创建的发布任务。</p>
        </div>
        <Button onClick={refresh} size="sm" variant="ghost"><RefreshCcw aria-hidden size={14} />刷新</Button>
      </header>
      <div className="grid gap-6">
        <ProfileSection />
        <AssetsSection />
        <TemplatesSection />
        <ImportSection />
      </div>
    </main>
  )
}

function ImportSection() {
  const client = useQueryClient()
  const runs = useQuery({ queryKey: ["brand-import-runs"], queryFn: fetchImportRuns })
  const run = useMutation({
    mutationFn: (dryRun: boolean) => runNotionImport(dryRun),
    onSuccess: async (result) => {
      const report = result.report
      toast.success(
        result.dry_run
          ? `预演完成：可导入素材 ${report.assets_imported ?? 0} 项，跳过 ${report.skipped?.length ?? 0} 项`
          : "迁移完成，已生成草稿（不会自动发布）",
      )
      await client.invalidateQueries({ queryKey: ["brand-import-runs"] })
      await client.invalidateQueries({ queryKey: ["brand-profile"] })
      await client.invalidateQueries({ queryKey: ["brand-assets"] })
      await client.invalidateQueries({ queryKey: ["brand-template"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const latest = runs.data?.[0] ?? null
  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold">从 Notion VI Hub 迁移</h2>
        <p className="mt-1 text-xs text-[var(--muted)]">一次性把 VI Hub 页面中的品牌信息与图片素材迁入，结果生成草稿，需人工检查后发布。</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          <Button disabled={run.isPending} onClick={() => run.mutate(true)} size="sm" variant="outline">预演（不写库）</Button>
          <Button disabled={run.isPending || (latest !== null && !latest.dry_run && latest.status === "成功")} onClick={() => run.mutate(false)} size="sm" title={latest && !latest.dry_run && latest.status === "成功" ? "已成功迁移过，不重复执行" : "执行迁移"}>
            <UploadCloud aria-hidden size={13} />执行迁移
          </Button>
        </div>
        {latest && (
          <div className="mt-4 border border-[var(--line)] p-4 text-xs">
            <p className="font-semibold">最近一次{latest.dry_run ? "预演" : "迁移"}：{latest.status}{latest.finished_at ? ` · ${new Date(latest.finished_at).toLocaleString("zh-CN")}` : ""}</p>
            {latest.error && <p className="mt-1 text-[var(--danger)]">{latest.error}</p>}
            {latest.report.assets_imported !== undefined && (
              <p className="mt-1 text-[var(--muted)]">
                素材导入 {latest.report.assets_imported} 项、复用 {latest.report.assets_reused ?? 0} 项、跳过 {latest.report.skipped?.length ?? 0} 项
              </p>
            )}
            {latest.report.skipped && latest.report.skipped.length > 0 && (
              <ul className="mt-2 grid gap-1">
                {latest.report.skipped.map((item, index) => (
                  <li className="text-[var(--muted)]" key={index}>跳过：{item.item} — {item.reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
