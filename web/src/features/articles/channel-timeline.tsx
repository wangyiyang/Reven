import { ArrowUpRight } from "lucide-react"

import { ArticleStatus } from "./article-status"
import type { ChannelName, ChannelResult } from "./types"

const safeLinks = new Set(["article_url", "pull_request_url"])
const labels: Record<string, string> = {
  article_url: "线上文章",
  pull_request_url: "Pull Request",
  pull_request_number: "PR 编号",
  commit_sha: "Commit",
  merge_sha: "Merge commit",
  media_id: "微信草稿 media_id",
}

export function ChannelTimeline({ channel, result }: { channel: ChannelName; result: ChannelResult | null }) {
  const entries = Object.entries(result?.result ?? {})
  return (
    <section className="border-t border-[var(--ink)] py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xl font-bold">{channel}</h3>
        <ArticleStatus status={result?.status ?? null} />
      </div>
      <div className="mt-5 border-l border-[var(--line)] pl-5">
        <p className="text-[10px] tracking-[0.13em] text-[var(--muted)] uppercase">当前阶段</p>
        <p className="mt-1 text-sm">{result?.status ?? "尚未创建渠道任务"}</p>
        {entries.length > 0 && (
          <dl className="mt-5 grid gap-3 sm:grid-cols-2">
            {entries.map(([key, value]) => <ResultItem key={key} name={key} value={String(value)} />)}
          </dl>
        )}
        {result?.error && <p className="mt-5 border-l-2 border-[var(--danger)] bg-[var(--faint)] p-3 text-sm text-[var(--danger)]">{result.error}</p>}
      </div>
    </section>
  )
}

function ResultItem({ name, value }: { name: string; value: string }) {
  const isLink = safeLinks.has(name) && /^https:\/\//.test(value)
  return (
    <div className="min-w-0">
      <dt className="text-[10px] tracking-[0.1em] text-[var(--muted)] uppercase">{labels[name] ?? name}</dt>
      <dd className="mt-1 truncate font-mono text-xs">
        {isLink ? <a className="inline-flex items-center gap-1" href={value} rel="noopener noreferrer" target="_blank">打开 <ArrowUpRight aria-hidden size={12} /></a> : value}
      </dd>
    </div>
  )
}
