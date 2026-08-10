import { useQuery } from "@tanstack/react-query"
import { ArrowUpRight, BookOpenText, ChevronLeft, ChevronRight } from "lucide-react"
import { Link, useSearchParams } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiRequest } from "@/lib/api"
import { safeNotionUrl } from "@/lib/external-url"
import { ArticleFilters, type ArticleFilterValues } from "./article-filters"
import { ArticleStatus } from "./article-status"
import { ContentSyncControl } from "./content-sync-control"
import { parseArticleList } from "./response-parsers"
import type { ArticleSummary } from "./types"

const PAGE_SIZE = 20

export function ArticlesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = readFilters(searchParams)
  const queryString = buildQuery(filters)
  const articles = useQuery({
    queryKey: ["articles", queryString],
    queryFn: async () => parseArticleList(await apiRequest<unknown>(`/articles?${queryString}`)),
  })
  const updateFilters = (next: ArticleFilterValues) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(next)) if (value) params.set(key, value)
    params.set("page", "1")
    setSearchParams(params)
  }
  return (
    <main className="page-enter mx-auto w-full max-w-[94rem] px-4 py-9 sm:px-7 lg:px-10 lg:py-12">
      <Header total={articles.data?.total} />
      <ArticleFilters onChange={updateFilters} values={filters} />
      {articles.isLoading && <LoadingRows />}
      {articles.isError && <ErrorPanel message={articles.error.message} retry={() => articles.refetch()} />}
      {articles.isSuccess && articles.data.items.length === 0 && <EmptyState />}
      {articles.isSuccess && articles.data.items.length > 0 && (
        <>
          <DesktopTable items={articles.data.items} />
          <MobileList items={articles.data.items} />
          <Pagination
            page={articles.data.page}
            pageSize={articles.data.page_size}
            total={articles.data.total}
            setPage={(page) => {
              const params = new URLSearchParams(searchParams)
              params.set("page", String(page))
              setSearchParams(params)
            }}
          />
        </>
      )}
    </main>
  )
}

function Header({ total }: { total?: number }) {
  return (
    <header className="mb-8 flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
      <div>
        <p className="section-kicker"><BookOpenText aria-hidden size={15} />Editorial queue / 稿件索引</p>
        <h1 className="font-display mt-3 text-[clamp(2.8rem,7vw,6.4rem)] leading-[0.9] tracking-[-0.055em]">交付，<i className="text-[var(--red)]">逐篇校准</i></h1>
      </div>
      <p className="max-w-sm border-l border-[var(--ink)] pl-5 text-sm leading-7 text-[var(--muted)]">
        当前索引 <strong className="font-display text-3xl text-[var(--ink)]">{total ?? "—"}</strong> 篇。稿件仍在 Notion 写作，Reven 只负责同步、校验与交付。
      </p>
    </header>
  )
}

function DesktopTable({ items }: { items: ArticleSummary[] }) {
  return (
    <div className="mt-6 hidden overflow-x-auto xl:block">
      <table className="w-full min-w-[1180px] border-collapse text-left text-xs">
        <thead><tr className="border-b border-[var(--ink)] text-[10px] tracking-[0.1em] text-[var(--muted)] uppercase">
          {["标题", "Notion 状态", "自动化状态", "内容同步", "封面", "目标渠道", "计划时间", "博客", "微信", "成功同步"].map((title) => <th className="px-2 py-3 font-semibold" key={title}>{title}</th>)}
        </tr></thead>
        <tbody>{items.map((article) => <ArticleRow article={article} key={article.id} />)}</tbody>
      </table>
    </div>
  )
}

function ArticleRow({ article }: { article: ArticleSummary }) {
  return (
    <tr className="group border-b border-[var(--line)] align-top hover:bg-white/30">
      <td className="w-[21%] px-2 py-5">
        <Link className="font-display text-lg leading-tight underline decoration-[var(--line)] underline-offset-4 group-hover:decoration-[var(--red)]" to={`/articles/${article.id}`}>{article.title}</Link>
        <RowActions article={article} />
      </td>
      <td className="px-2 py-5"><ArticleStatus compact status={article.notion_status} /></td>
      <td className="px-2 py-5"><ArticleStatus compact status={article.automation_status} /></td>
      <td className="px-2 py-5"><ArticleStatus compact status={article.content_sync.status} /></td>
      <td className="px-2 py-5">{article.cover_valid ? "✓ 已校验" : <span className="text-[var(--red)]">! 缺失</span>}</td>
      <td className="px-2 py-5">{channelLabel(article.target_channels, " · ")}</td>
      <td className="px-2 py-5">{formatDate(article.planned_at)}</td>
      <td className="px-2 py-5"><ArticleStatus compact status={article.blog_status} /></td>
      <td className="px-2 py-5"><ArticleStatus compact status={article.wechat_status} /></td>
      <td className="px-2 py-5">{formatDate(article.content_sync.current_snapshot?.synced_at ?? null)}</td>
    </tr>
  )
}

function MobileList({ items }: { items: ArticleSummary[] }) {
  return (
    <div className="mt-6 grid gap-4 xl:hidden">
      {items.map((article) => (
        <article aria-label={`${article.title}移动摘要`} className="border border-[var(--line-strong)] bg-white/25 p-5" key={article.id}>
          <Link className="font-display text-2xl leading-tight" to={`/articles/${article.id}`}>{article.title}</Link>
          <div className="mt-4 flex flex-wrap gap-2"><ArticleStatus status={article.content_sync.status} /><ArticleStatus status={article.automation_status} /><ArticleStatus status={article.notion_status} /></div>
          <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
            <Meta label="渠道" value={channelLabel(article.target_channels, "、")} />
            <Meta label="封面" value={article.cover_valid ? "已校验" : "缺失"} />
            <Meta label="计划" value={formatDate(article.planned_at)} />
            <Meta label="成功同步" value={formatDate(article.content_sync.current_snapshot?.synced_at ?? null)} />
          </dl>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <ChannelSummary label="博客" status={article.blog_status} />
            <ChannelSummary label="微信" status={article.wechat_status} />
          </div>
          <RowActions article={article} />
        </article>
      ))}
    </div>
  )
}

function RowActions({ article }: { article: ArticleSummary }) {
  const notionUrl = safeNotionUrl(article.notion_url)
  return (
    <div className="mt-3 flex flex-wrap gap-1">
      {notionUrl && <a className="inline-flex min-h-9 items-center gap-1 px-2 text-xs hover:bg-black/5" href={notionUrl} rel="noopener noreferrer" target="_blank">Notion <ArrowUpRight aria-hidden size={12} /></a>}
      <ContentSyncControl article={article} compact />
      <Link className="inline-flex min-h-9 items-center px-2 text-xs hover:bg-black/5" to={`/articles/${article.id}`}>任务详情</Link>
    </div>
  )
}

function Pagination({ page, pageSize, total, setPage }: { page: number; pageSize: number; total: number; setPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <nav aria-label="稿件分页" className="mt-8 flex items-center justify-between border-t border-[var(--ink)] pt-5">
      <span className="text-xs text-[var(--muted)]">第 {page} / {pages} 页</span>
      <div className="flex gap-2">
        <Button aria-label="上一页" disabled={page <= 1} onClick={() => setPage(page - 1)} size="sm" variant="outline"><ChevronLeft aria-hidden size={14} /></Button>
        <Button aria-label="下一页" disabled={page >= pages} onClick={() => setPage(page + 1)} size="sm" variant="outline"><ChevronRight aria-hidden size={14} /></Button>
      </div>
    </nav>
  )
}

function readFilters(params: URLSearchParams): ArticleFilterValues & { page: string } {
  const rawPage = Number(params.get("page") ?? "1")
  return {
    status: params.get("status") ?? "",
    channel: params.get("channel") ?? "",
    query: params.get("query") ?? "",
    page: Number.isInteger(rawPage) && rawPage > 0 ? String(rawPage) : "1",
  }
}

function buildQuery(filters: ReturnType<typeof readFilters>) {
  const params = new URLSearchParams({ page: filters.page, page_size: String(PAGE_SIZE) })
  for (const key of ["status", "channel", "query"] as const) if (filters[key]) params.set(key, filters[key])
  return params.toString()
}

function formatDate(value: string | null) {
  if (!value) return "未安排"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value))
}

function channelLabel(channels: ArticleSummary["target_channels"], separator: string) {
  return (channels.length > 0 ? channels : ["个人博客", "微信公众号"]).join(separator)
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-[10px] tracking-[0.1em] text-[var(--muted)] uppercase">{label}</dt><dd className="mt-1">{value}</dd></div>
}

function ChannelSummary({ label, status }: { label: string; status: string | null }) {
  return <div><p className="mb-1 text-[10px] tracking-[0.1em] text-[var(--muted)] uppercase">{label}</p><ArticleStatus compact status={status} /></div>
}

function LoadingRows() {
  return <section aria-busy="true" aria-label="正在读取稿件" className="mt-6 grid gap-3">{Array.from({ length: 5 }, (_, index) => <Skeleton className="h-20 rounded-none bg-black/8" key={index} />)}</section>
}

function ErrorPanel({ message, retry }: { message: string; retry: () => void }) {
  return <div className="mt-6 border border-[var(--red)] bg-[var(--red-soft)] p-5 text-sm text-[var(--red)]" role="alert"><p>稿件读取失败：{message}</p><Button className="mt-4" onClick={retry} size="sm" variant="outline">重新读取</Button></div>
}

function EmptyState() {
  return <div className="mt-8 border border-dashed border-[var(--line-strong)] px-6 py-16 text-center"><p className="font-display text-3xl">没有匹配稿件</p><p className="mt-2 text-sm text-[var(--muted)]">调整筛选条件，或先从 Notion 同步稿件。</p></div>
}
