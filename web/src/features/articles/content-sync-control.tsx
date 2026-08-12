import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { LoaderCircle, RefreshCcw } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiRequest } from "@/lib/api"
import { parseSyncRun } from "./response-parsers"
import type { ArticleSummary, ContentSyncRun } from "./types"

export function ContentSyncControl({ article, compact = false }: { article: ArticleSummary; compact?: boolean }) {
  const client = useQueryClient()
  const latest = article.content_sync.latest_run
  const [runId, setRunId] = useState(isActive(latest) ? latest?.id ?? null : null)
  const completedToast = useRef<string | null>(null)
  const run = useQuery({
    queryKey: ["content-sync-run", article.id, runId],
    queryFn: async () => parseSyncRun(await apiRequest<unknown>(`/articles/${article.id}/sync-runs/${runId}`)),
    enabled: Boolean(runId),
    refetchInterval: (query) => isActive(query.state.data) ? 1000 : false,
  })
  useEffect(() => {
    if (isActive(latest)) setRunId(latest?.id ?? null)
  }, [latest])
  const sync = useMutation({
    mutationFn: async () => parseSyncRun(await apiRequest<unknown>(`/articles/${article.id}/sync`, { method: "POST" })),
    onSuccess: (accepted) => {
      client.setQueryData(["content-sync-run", article.id, accepted.id], accepted)
      if (isActive(accepted)) {
        setRunId(accepted.id)
        toast.success(accepted.created ? "同步任务已创建" : "同步任务正在处理中")
      } else {
        toast.success("当前内容快照已是最新")
      }
      void invalidateArticle(client, article.id)
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const observed = run.data ?? (runId === latest?.id ? latest : null)
  useEffect(() => {
    if (!observed || isActive(observed) || completedToast.current === observed.id) return
    completedToast.current = observed.id
    void invalidateArticle(client, article.id)
    if (observed.status === "已同步") toast.success("内容同步完成")
    else toast.error(syncFailure(observed))
  }, [article.id, client, observed])
  const working = sync.isPending || isActive(observed) || article.content_sync.status === "同步中"
  return (
    <div className={compact ? "inline-flex flex-col items-start gap-1" : "flex flex-col items-start gap-2"}>
      <Button
        disabled={working}
        onClick={() => sync.mutate()}
        size={compact ? "sm" : "default"}
        type="button"
        variant="outline"
      >
        {working ? <LoaderCircle aria-hidden className="animate-spin" size={14} /> : <RefreshCcw aria-hidden size={14} />}
        {article.content_sync.status === "已同步" ? "重新同步" : "同步内容"}
      </Button>
      <SyncProgress run={observed} fallback={article.content_sync.error} />
    </div>
  )
}

function SyncProgress({ run, fallback }: { run: ContentSyncRun | null; fallback: string | null }) {
  if (!run) return fallback ? <p className="max-w-64 text-[11px] text-[var(--danger)]">{fallback}</p> : null
  const progress = run.progress_total > 0 ? ` ${run.progress_current}/${run.progress_total}` : ""
  const media = run.current_media ? ` · ${run.current_media}` : ""
  const error = run.error_message ? `：${run.error_message}${run.error_media ? `（${run.error_media}）` : ""}` : ""
  return <p className="max-w-72 text-[11px] text-[var(--muted)]">{run.error_stage ?? run.stage}{progress}{media}{error}</p>
}

function isActive(run: ContentSyncRun | null | undefined) {
  return run?.status === "等待中" || run?.status === "同步中"
}

function syncFailure(run: ContentSyncRun) {
  return run.error_message ? `内容同步失败：${run.error_message}` : "内容同步失败"
}

async function invalidateArticle(client: QueryClient, articleId: string) {
  await Promise.all([
    client.invalidateQueries({ queryKey: ["articles"] }),
    client.invalidateQueries({ queryKey: ["article", articleId] }),
  ])
}
