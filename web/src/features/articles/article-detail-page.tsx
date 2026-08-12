import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowUpRight, Ban, RefreshCcw, RotateCcw } from "lucide-react"
import { useRef } from "react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiRequest } from "@/lib/api"
import { safeNotionUrl } from "@/lib/external-url"
import { ArticleStatus } from "./article-status"
import { ChannelTimeline } from "./channel-timeline"
import { ContentSyncControl } from "./content-sync-control"
import type { ArticleDetail, ChannelName, JobDetail, JobSummary, ValidationItem } from "./types"
import { WechatPreview } from "./wechat-preview"
import { parseAction, parseArticleDetail, parseJobDetail } from "./response-parsers"
import { PublicationGuidance } from "./publication-guidance"
import { PortableMarkdownCopy } from "./portable-markdown-copy"

export function ArticleDetailPage() {
  const { articleId = "" } = useParams()
  const article = useQuery({
    queryKey: ["article", articleId],
    queryFn: async () => parseArticleDetail(await apiRequest<unknown>(`/articles/${articleId}`)),
    enabled: Boolean(articleId),
  })
  if (article.isLoading) return <DetailLoading />
  if (article.isError) return <DetailError message={article.error.message} retry={() => article.refetch()} />
  if (!article.data) return null
  return <DetailContent article={article.data} />
}

function DetailContent({ article }: { article: ArticleDetail }) {
  const notionUrl = safeNotionUrl(article.notion_url)
  const newest = article.jobs[0]
  const job = useQuery({
    queryKey: ["article-job", article.id, newest?.id],
    queryFn: async () => parseJobDetail(await apiRequest<unknown>(`/articles/${article.id}/jobs/${newest.id}`)),
    enabled: Boolean(newest),
  })
  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-9 sm:px-8 lg:px-12 lg:py-12">
      <Link className="inline-flex min-h-10 items-center gap-2 text-xs font-semibold hover:underline" to="/articles"><ArrowLeft aria-hidden size={14} />返回稿件索引</Link>
      <header className="mt-5 grid gap-7 border-b border-[var(--ink)] pb-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="section-kicker">Article dossier / 交付档案</p>
          <h1 className="mt-3 max-w-4xl text-[clamp(2.5rem,6vw,5.5rem)] leading-[0.95] font-bold tracking-[-0.05em]">{article.title}</h1>
          <div className="mt-5 flex flex-wrap gap-2"><ArticleStatus status={article.notion_status} /><ArticleStatus status={article.automation_status} /></div>
        </div>
        <div className="flex flex-wrap gap-2">
          {notionUrl && <a className="inline-flex min-h-10 items-center gap-2 border border-[var(--line)] px-4 text-sm font-semibold text-[var(--ink)] hover:border-[var(--ink)] hover:no-underline" href={notionUrl} rel="noopener noreferrer" target="_blank">打开 Notion <ArrowUpRight aria-hidden size={14} /></a>}
          <ContentSyncControl article={article} />
          <PortableMarkdownCopy articleId={article.id} enabled={article.content_sync.outputs_enabled} />
          <WechatPreview articleId={article.id} enabled={article.content_sync.outputs_enabled} title={article.title} />
        </div>
      </header>
      <ContentSyncPanel article={article} />
      <section className="grid gap-8 py-8 lg:grid-cols-[0.8fr_1.2fr]">
        <Metadata article={article} />
        <Validation errors={article.validation_errors} warnings={article.validation_warnings} />
      </section>
      <section aria-label="渠道交付时间线">
        <p className="section-kicker mb-2">Delivery timeline / 渠道状态</p>
        {!newest && <>
          <ChannelTimeline channel="个人博客" result={article.blog} />
          <ChannelTimeline channel="微信公众号" result={article.wechat} />
        </>}
        {newest && job.isLoading && <JobLoading />}
        {newest && job.isError && <JobError message={job.error.message} retry={() => job.refetch()} />}
        {job.isSuccess && <>
          <ChannelTimeline channel="个人博客" result={job.data.blog} />
          <ChannelTimeline channel="微信公众号" result={job.data.wechat} />
        </>}
      </section>
      {job.isSuccess && <JobActions articleId={article.id} job={job.data} outputsEnabled={article.content_sync.outputs_enabled} />}
      <PublicationGuidance article={article} job={job.data ?? null} />
      <JobHistory article={article} />
    </main>
  )
}

function ContentSyncPanel({ article }: { article: ArticleDetail }) {
  const snapshot = article.content_sync.current_snapshot
  return (
    <section className="mt-8 border border-[var(--line)] bg-[var(--faint)] p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-3xl font-bold">内容快照</h2>
        <ArticleStatus status={article.content_sync.status} />
      </div>
      <dl className="mt-5 grid gap-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Meta label="最近成功同步" value={formatDate(snapshot?.synced_at ?? null)} />
        <Meta label="对应 Notion 编辑" value={formatDate(snapshot?.source_last_edited_at ?? null)} />
        <Meta label="正文字符" value={snapshot ? String(snapshot.character_count) : "—"} />
        <Meta label="归档媒体" value={snapshot ? String(snapshot.media_count) : "—"} />
      </dl>
      {article.content_sync.error && <p className="mt-4 text-sm text-[var(--danger)]">{article.content_sync.error}</p>}
      {!article.content_sync.outputs_enabled && <p className="mt-2 text-xs text-[var(--muted)]">同步成功且版本校验通过后，复制与发布操作才会解锁。</p>}
    </section>
  )
}

function Metadata({ article }: { article: ArticleDetail }) {
  return (
    <section>
      <h2 className="text-3xl font-bold">Notion 元数据</h2>
      <dl className="mt-5 grid grid-cols-2 gap-5 text-sm">
        <Meta label="封面校验" value={article.cover_valid ? "通过" : "未通过：发布将被阻止"} danger={!article.cover_valid} />
        <Meta label="计划时间" value={formatDate(article.planned_at)} />
        <Meta label="目标渠道" value={(article.target_channels.length ? article.target_channels : ["个人博客", "微信公众号"]).join("、")} />
        <Meta label="Notion 索引刷新" value={formatDate(article.last_synced_at)} />
        <Meta label="内容 Hash" value={article.content_sync.current_snapshot?.content_hash ?? "尚未同步"} mono />
      </dl>
    </section>
  )
}

function Validation({ errors, warnings }: { errors: ValidationItem[]; warnings: ValidationItem[] }) {
  return (
    <section>
      <h2 className="text-3xl font-bold">发布前校验</h2>
      <div className="mt-5 grid gap-3">
        {errors.length === 0 && warnings.length === 0 && <p className="border-l-2 border-[var(--signal)] bg-[var(--faint)] p-4 text-sm">当前没有校验问题。</p>}
        {errors.map((item, index) => <Issue item={item} key={`error-${index}`} tone="error" />)}
        {warnings.map((item, index) => <Issue item={item} key={`warning-${index}`} tone="warning" />)}
      </div>
    </section>
  )
}

function Issue({ item, tone }: { item: ValidationItem; tone: "error" | "warning" }) {
  return <div className={tone === "error" ? "border-l-2 border-[var(--danger)] bg-[var(--faint)] p-4" : "border-l-2 border-[var(--muted)] bg-[var(--faint)] p-4"}><p className="text-sm font-semibold">{item.message ?? item.code ?? "未知校验问题"}</p>{item.field && <p className="mt-1 text-xs opacity-70">字段：{item.field}</p>}</div>
}

function JobActions({ articleId, job, outputsEnabled }: { articleId: string; job: JobSummary | JobDetail; outputsEnabled: boolean }) {
  const lock = useRef(false)
  const client = useQueryClient()
  const action = useMutation({
    mutationFn: async ({ kind, channels }: { kind: "retry" | "cancel"; channels?: ChannelName[] }) =>
      parseAction(
        await apiRequest<unknown>(`/articles/${articleId}/jobs/${job.id}/${kind}`, {
          method: "POST",
          body: channels ? JSON.stringify({ channels }) : undefined,
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["article", articleId] })
      await client.invalidateQueries({ queryKey: ["article-job", articleId, job.id] })
      toast.success("任务状态已更新")
    },
    onError: (error: Error) => toast.error(error.message),
    onSettled: () => { lock.current = false },
  })
  const runAction = (input: { kind: "retry" | "cancel"; channels?: ChannelName[] }) => {
    if (lock.current) return
    lock.current = true
    action.mutate(input)
  }
  const failed = [
    ...(isFailed(job.blog_status) ? ["个人博客" as const] : []),
    ...(isFailed(job.wechat_status) ? ["微信公众号" as const] : []),
  ]
  const resumable = job.overall_status === "阻塞"
    ? job.target_channels.filter((channel) => !isDelivered(job, channel))
    : []
  return (
    <section className="my-8 flex flex-wrap items-center justify-between gap-4 border-y border-[var(--ink)] py-5">
      <div><p className="text-xs text-[var(--muted)]">最近任务</p><p className="mt-1 font-mono text-xs">{job.id}</p></div>
      <div className="flex flex-wrap gap-2">
        {resumable.length > 0
          ? <Button disabled={action.isPending || !outputsEnabled} onClick={() => runAction({ kind: "retry", channels: resumable })} size="sm" variant="danger"><RotateCcw aria-hidden size={13} />恢复发布</Button>
          : failed.map((channel) => <Button disabled={action.isPending || !outputsEnabled} key={channel} onClick={() => runAction({ kind: "retry", channels: [channel] })} size="sm" variant="danger"><RotateCcw aria-hidden size={13} />重试{channel}</Button>)}
        {job.overall_status === "等待中" && <Button disabled={action.isPending} onClick={() => runAction({ kind: "cancel" })} size="sm" variant="outline"><Ban aria-hidden size={13} />取消等待任务</Button>}
      </div>
    </section>
  )
}

function JobHistory({ article }: { article: ArticleDetail }) {
  return (
    <section className="py-5">
      <h2 className="text-3xl font-bold">任务历史</h2>
      <p className="mt-2 text-xs text-[var(--muted)]">显示最近 {article.jobs.length} 条，共 {article.jobs_total} 条。{article.jobs_has_more && "更早记录未在本页加载。"}</p>
      <ol className="mt-5 grid gap-2">
        {article.jobs.map((job) => <li className="grid gap-2 border-b border-[var(--line)] py-3 text-xs sm:grid-cols-[1fr_auto_auto]" key={job.id}><span className="truncate font-mono">{job.id}</span><ArticleStatus compact status={job.overall_status} /><time>{formatDate(job.scheduled_at)}</time></li>)}
      </ol>
    </section>
  )
}

function Meta({ label, value, danger = false, mono = false }: { label: string; value: string; danger?: boolean; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-[10px] tracking-[0.12em] text-[var(--muted)] uppercase">{label}</dt><dd className={`mt-1 break-words ${danger ? "text-[var(--danger)]" : ""} ${mono ? "font-mono text-xs" : ""}`}>{value}</dd></div>
}

function isFailed(status: string) {
  return /失败|阻塞/.test(status)
}

function isDelivered(job: JobSummary | JobDetail, channel: ChannelName) {
  return channel === "个人博客" ? job.blog_status === "已上线" : job.wechat_status === "草稿已生成"
}

function formatDate(value: string | null) {
  if (!value) return "未安排"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value))
}

function DetailLoading() {
  return <main aria-busy="true" aria-label="正在读取稿件详情" className="mx-auto max-w-6xl px-5 py-12"><Skeleton className="h-16 rounded-none" /><Skeleton className="mt-8 h-72 rounded-none" /></main>
}

function DetailError({ message, retry }: { message: string; retry: () => void }) {
  return <main className="mx-auto max-w-6xl px-5 py-12"><div className="border border-[var(--danger)] bg-[var(--faint)] p-6" role="alert"><p>稿件详情读取失败：{message}</p><Button className="mt-4" onClick={retry} variant="outline"><RefreshCcw aria-hidden size={14} />重新读取</Button></div></main>
}

function JobLoading() {
  return <div aria-busy="true" aria-label="正在读取最近任务" className="grid gap-3 py-6"><Skeleton className="h-20 rounded-none" /><Skeleton className="h-20 rounded-none" /></div>
}

function JobError({ message, retry }: { message: string; retry: () => void }) {
  return <div className="my-5 border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert"><p>最近任务读取失败：{message}</p><Button className="mt-3" onClick={retry} size="sm" variant="outline">重试任务详情</Button></div>
}
