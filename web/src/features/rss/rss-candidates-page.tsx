import { ArrowUpRight, Check, Rss, X } from "lucide-react"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { ErrorPanel } from "@/components/ui/error-panel"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import type { RssCandidate } from "./types"
import { useRssCandidatesController } from "./use-rss-candidates-controller"

export function RssCandidatesPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get("status") === "saved" ? "saved" : "candidate"
  const controller = useRssCandidatesController(view)
  const visible = controller.items
  const remaining = (controller.total ?? 0) - visible.length
  return (
    <main className="page-enter mx-auto w-full max-w-7xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold">RSS 内容发现</h1>
        <p className="text-sm text-[var(--muted)]">{view === "saved" ? "已保存" : "待审"} <span className="font-semibold text-[var(--ink)]">{controller.total ?? "—"}</span></p>
      </header>

      <Tabs className="mb-6" onValueChange={(status) => setParams({ status })} value={view}>
        <TabsList aria-label="内容状态">
          <TabsTrigger value="candidate">待审核</TabsTrigger>
          <TabsTrigger value="saved">已保存素材</TabsTrigger>
        </TabsList>
        <TabsContent value={view}>
          {controller.candidates.isLoading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取内容…</p>}
          {controller.candidates.isError && (
            <ErrorPanel
              message={controller.candidates.error.message}
              retry={() => void controller.candidates.refetch()}
              title="RSS 内容读取失败"
            />
          )}
          {controller.total === 0 && <EmptyQueue saved={view === "saved"} />}
          <ol className="grid gap-6">
            {visible.map((candidate, index) => (
              <CandidateCard
                busy={controller.busyId != null}
                candidate={candidate}
                index={index + 1}
                key={candidate.record_id}
                onConfirm={() => controller.confirm(candidate.record_id)}
                onIgnore={() => controller.ignore(candidate.record_id)}
              />
            ))}
          </ol>
          {controller.hasNextPage && (
            <div className="mt-6 flex justify-center">
              <Button
                disabled={controller.isFetchingNextPage}
                onClick={() => controller.fetchNextPage()}
                type="button"
                variant="outline"
              >
                {controller.isFetchingNextPage ? "正在加载…" : `加载更多（还剩 ${remaining} 条）`}
              </Button>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </main>
  )
}

function EmptyQueue({ saved }: { saved: boolean }) {
  return (
    <section className="grid min-h-72 place-items-center rounded-lg border border-dashed border-[var(--line)] bg-[var(--faint)] text-center">
      <div><Rss aria-hidden className="mx-auto text-[var(--muted)]" /><h2 className="mt-4 text-base font-semibold">{saved ? "暂无已保存素材" : "候选队列已清空"}</h2><p className="mt-2 text-sm text-[var(--muted)]">{saved ? "在待审核列表采纳内容后，可在这里查阅。" : "下一次定时发现完成后，新候选会出现在这里。"}</p></div>
    </section>
  )
}

function CandidateCard(props: {
  candidate: RssCandidate
  index: number
  busy: boolean
  onConfirm: () => void
  onIgnore: () => void
}) {
  const { candidate } = props
  const [expanded, setExpanded] = useState(false)
  const summaryText = candidate.summary || "暂无摘要"
  const isLongSummary = summaryText.length > 240
  return (
    <li className="candidate-card grid overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--bg)] lg:grid-cols-[minmax(0,1fr)_20rem]">
      <article className="p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[var(--muted)]">
          <span>#{String(props.index).padStart(2, "0")}</span>
          <span>{candidate.source_name}</span><span aria-hidden>·</span><time>{formatDate(candidate.published_at)}</time>
        </div>
        <h2 className="mt-4 text-lg font-semibold leading-tight">{candidate.title}</h2>
        <p className={`mt-5 max-w-3xl text-sm leading-7${isLongSummary && !expanded ? " line-clamp-4" : ""}`}>{summaryText}</p>
        {isLongSummary && (
          <button
            className="mt-2 text-xs font-semibold text-[var(--signal)] hover:underline"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >{expanded ? "收起" : "展开全文"}</button>
        )}
        <div className="mt-6 flex flex-wrap gap-2">
          {candidate.matched_keywords.map((term) => <Badge className="text-[var(--signal)]" key={term}>{term}</Badge>)}
          {candidate.matched_keywords.length === 0 && <span className="text-xs text-[var(--muted)]">无命中关键词</span>}
        </div>
      </article>
      <aside className="flex flex-col border-t border-[var(--line)] bg-[var(--faint)] p-5 lg:border-t-0 lg:border-l">
        <p className="text-xs text-[var(--muted)]">入库时间</p>
        <p className="mt-1 text-sm">{formatDate(candidate.archived_at)}</p>
        <div className="mt-auto grid gap-2 pt-6">
          {candidate.url && <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-[var(--line)] px-4 text-sm font-semibold text-[var(--ink)] hover:border-[var(--ink)] hover:no-underline" href={candidate.url} rel="noopener noreferrer" target="_blank">查看原文 <ArrowUpRight aria-hidden size={15} /></a>}
          {candidate.status === "candidate" && <>
            <Button aria-label={`采纳并保存 ${candidate.title}`} disabled={props.busy} onClick={props.onConfirm}><Check aria-hidden size={16} />采纳并保存</Button>
            <Button aria-label={`忽略 ${candidate.title}`} disabled={props.busy} onClick={props.onIgnore} variant="ghost"><X aria-hidden size={16} />忽略</Button>
          </>}
          {candidate.status === "saved" && <p className="text-center text-xs text-[var(--signal)]">已保存素材</p>}
        </div>
      </aside>
    </li>
  )
}

function formatDate(value: string | null): string {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(date)
}
