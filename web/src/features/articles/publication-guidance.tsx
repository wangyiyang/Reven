import { ArrowUpRight, Wrench } from "lucide-react"
import { Link } from "react-router-dom"

import { safeNotionUrl } from "@/lib/external-url"
import type { ArticleDetail, JobDetail, ValidationItem } from "./types"

interface GuidanceItem {
  source: string
  error: string
  advice: string
}

export function PublicationGuidance({
  article,
  job,
}: {
  article: ArticleDetail
  job: JobDetail | null
}) {
  const items = guidanceItems(article, job)
  const notionUrl = safeNotionUrl(article.notion_url)
  return (
    <section className="border-y border-[var(--ink)] py-7">
      <p className="section-kicker"><Wrench aria-hidden size={14} />Recovery notes / 错误与建议</p>
      <h2 className="mt-2 text-3xl font-bold">下一步怎么处理</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--muted)]">当前没有需要处理的错误。</p>
      ) : (
        <ul className="mt-5 grid gap-3">
          {items.map((item, index) => (
            <li className="grid gap-2 border-l-2 border-[var(--danger)] bg-[var(--faint)] p-4 sm:grid-cols-[10rem_1fr]" key={`${item.source}-${index}`}>
              <div><p className="text-[10px] tracking-[0.12em] text-[var(--muted)] uppercase">{item.source}</p><p className="mt-1 text-sm text-[var(--danger)]">{item.error}</p></div>
              <div><p className="text-[10px] tracking-[0.12em] text-[var(--muted)] uppercase">建议</p><p className="mt-1 text-sm">{item.advice}</p></div>
            </li>
          ))}
        </ul>
      )}
      {items.length > 0 && <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold">
        {notionUrl && <a className="inline-flex items-center gap-1" href={notionUrl} rel="noopener noreferrer" target="_blank">打开 Notion <ArrowUpRight aria-hidden size={12} /></a>}
        <Link to="/integrations">检查集成配置</Link>
      </div>}
    </section>
  )
}

function guidanceItems(article: ArticleDetail, job: JobDetail | null): GuidanceItem[] {
  const items: GuidanceItem[] = []
  if (article.last_error) items.push(item("稿件", article.last_error, article.validation_errors))
  if (job?.blog.error) items.push(item("个人博客", job.blog.error, []))
  if (job?.wechat.error) items.push(item("微信公众号", job.wechat.error, []))
  return items
}

function item(source: string, rawError: string, validation: ValidationItem[]): GuidanceItem {
  const evidence = `${source} ${rawError} ${validation.map((value) => `${value.code} ${value.field}`).join(" ")}`
  return { source, error: redact(rawError), advice: adviceFor(evidence) }
}

function adviceFor(evidence: string): string {
  if (/封面|cover/i.test(evidence)) return "在 Notion 补充封面图片并重新同步，然后重试失败渠道。"
  if (/微信|wechat|白名单|media/i.test(evidence)) return "检查微信集成和出口 IP 白名单，修复后仅重试微信渠道。"
  if (/博客|github|pull request|jekyll|build/i.test(evidence)) return "检查 GitHub 集成、PR 与构建日志，修复后仅重试博客渠道。"
  if (/notion|字段|schema/i.test(evidence)) return "检查 Notion 集成与数据库字段，修复稿件后重新同步。"
  return "检查集成配置或打开 Notion 修复内容，确认后重试对应失败渠道。"
}

function redact(value: string): string {
  return value
    .replace(/https?:\/\/\S+/gi, "[已脱敏地址]")
    .replace(/(bearer|token|secret|password|appsecret)\s*[:=]?\s*\S+/gi, "$1=***")
    .slice(0, 1000)
}
