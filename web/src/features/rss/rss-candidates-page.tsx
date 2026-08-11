import { ArrowUpRight, Check, Rss, Sparkles, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { RssCandidate } from "./types"
import { useRssCandidatesController } from "./use-rss-candidates-controller"

export function RssCandidatesPage() {
  const controller = useRssCandidatesController()
  return (
    <main className="page-enter mx-auto w-full max-w-7xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 grid gap-6 border-b border-[var(--ink)] pb-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="section-kicker"><Sparkles aria-hidden size={15} />Discovery desk / Review</p>
          <h1 className="font-display mt-4 text-[clamp(2.7rem,7vw,5.5rem)] leading-[0.92] tracking-[-0.045em]">RSS 候选工作台</h1>
          <p className="mt-5 max-w-2xl text-sm leading-7 text-[var(--muted)]">核对筛选依据，只把值得继续编辑的素材送入 Notion Inbox。</p>
        </div>
        <div className="border-l-4 border-[var(--red)] pl-4">
          <p className="font-display text-4xl">{controller.candidates.data?.length ?? "—"}</p>
          <p className="text-xs tracking-[0.12em] text-[var(--muted)] uppercase">Awaiting review</p>
        </div>
      </header>

      {controller.candidates.isLoading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取候选…</p>}
      {controller.candidates.isError && (
        <div className="border border-[var(--red)] bg-[var(--red-soft)] p-5 text-sm text-[var(--red)]" role="alert">
          <p>RSS 候选读取失败：{controller.candidates.error.message}</p>
          <Button className="mt-4" onClick={() => controller.candidates.refetch()} size="sm" variant="outline">重新读取</Button>
        </div>
      )}
      {controller.candidates.data?.length === 0 && <EmptyQueue />}
      <ol className="grid gap-6">
        {controller.candidates.data?.map((candidate, index) => (
          <CandidateCard
            busy={controller.busyId === candidate.id}
            candidate={candidate}
            index={index + 1}
            key={candidate.id}
            onConfirm={() => controller.confirm(candidate.id)}
            onIgnore={() => controller.ignore(candidate.id)}
          />
        ))}
      </ol>
    </main>
  )
}

function EmptyQueue() {
  return (
    <section className="grid min-h-72 place-items-center border border-dashed border-[var(--line-strong)] bg-white/25 text-center">
      <div><Rss aria-hidden className="mx-auto text-[var(--blue)]" /><h2 className="font-display mt-4 text-3xl">候选队列已清空</h2><p className="mt-2 text-sm text-[var(--muted)]">下一次定时发现完成后，新候选会出现在这里。</p></div>
    </section>
  )
}

function CandidateCard(props: {
  candidate: RssCandidate
  index: number
  busy: boolean
  onConfirm: () => Promise<unknown>
  onIgnore: () => Promise<unknown>
}) {
  const { candidate } = props
  return (
    <li className="candidate-card grid overflow-hidden border border-[var(--ink)] bg-[var(--paper)] lg:grid-cols-[minmax(0,1fr)_20rem]">
      <article className="p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[var(--muted)]">
          <span className="font-mono font-bold text-[var(--red)]">#{String(props.index).padStart(2, "0")}</span>
          <span>{candidate.source_name}</span><span aria-hidden>·</span><time>{formatDate(candidate.published_at)}</time>
        </div>
        <h2 className="font-display mt-4 text-3xl leading-tight sm:text-4xl">{candidate.title_zh}</h2>
        {candidate.title_zh !== candidate.title && <p className="mt-2 text-sm italic text-[var(--muted)]">{candidate.title}</p>}
        <p className="mt-5 max-w-3xl text-sm leading-7">{candidate.summary_zh || candidate.summary || "暂无摘要"}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {candidate.positive_literal_matches.map((term) => <Badge className="text-[var(--blue)]" key={`positive-${term}`}>{term}</Badge>)}
          {candidate.negative_literal_matches.map((term) => <Badge className="text-[var(--red)]" key={`negative-${term}`}>反向 · {term}</Badge>)}
          {candidate.positive_literal_matches.length + candidate.negative_literal_matches.length === 0 && <span className="text-xs text-[var(--muted)]">无字面命中</span>}
        </div>
        <p className="mt-5 border-l-2 border-[var(--blue)] pl-4 text-sm leading-6"><span className="font-semibold">入选依据：</span>{candidate.reason ?? "未提供"}</p>
      </article>
      <aside className="flex flex-col border-t border-[var(--ink)] bg-white/30 p-5 lg:border-t-0 lg:border-l">
        <p className="text-[10px] font-bold tracking-[0.16em] text-[var(--muted)] uppercase">Signal report</p>
        <dl className="mt-4 grid grid-cols-3 gap-2 lg:grid-cols-1">
          <Score label="BM25" value={candidate.bm25_score} />
          <Score label="正向语义" value={candidate.positive_embedding_score} />
          <Score label="反向语义" value={candidate.negative_embedding_score} />
        </dl>
        <div className="mt-5 text-[11px] leading-5 text-[var(--muted)]">
          <p>向量：{candidate.embedding_status} · {candidate.embedding_model ?? "未启用"}</p>
          <p>模型复核：{candidate.model_status}</p>
          <p>规则：{candidate.rules_version ?? "—"}</p>
        </div>
        <div className="mt-auto grid gap-2 pt-6">
          {candidate.url && <a className="inline-flex min-h-10 items-center justify-center gap-2 border border-[var(--line)] px-4 text-sm font-semibold hover:border-[var(--ink)]" href={candidate.url} rel="noopener noreferrer" target="_blank">查看原文 <ArrowUpRight aria-hidden size={15} /></a>}
          <Button aria-label={`推送到 Notion ${candidate.title_zh}`} disabled={props.busy} onClick={() => void props.onConfirm()}><Check aria-hidden size={16} />推送到 Notion</Button>
          <Button aria-label={`忽略 ${candidate.title_zh}`} disabled={props.busy} onClick={() => void props.onIgnore()} variant="ghost"><X aria-hidden size={16} />忽略</Button>
        </div>
      </aside>
    </li>
  )
}

function Score({ label, value }: { label: string; value: number }) {
  return <div className="border-b border-[var(--line)] py-2"><dt className="text-[10px] tracking-[0.08em] text-[var(--muted)] uppercase">{label}</dt><dd className="mt-1 font-mono text-lg font-bold">{value.toFixed(3)}</dd></div>
}

function formatDate(value: string | null): string {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(date)
}
