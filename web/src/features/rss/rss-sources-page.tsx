import { useEffect, useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RssSourceInput } from "./rss-api"
import { ErrorPanel, StatusBadge } from "./rss-shared"
import type { RssSource } from "./types"
import { useRssSettingsController } from "./use-rss-settings-controller"

type SourcesPanelProps = {
  sources: RssSource[]
  busy: boolean
  onCreate: (input: RssSourceInput) => Promise<boolean>
  onDelete: (source: RssSource) => Promise<boolean>
  onUpdate: (source: RssSource, input: RssSourceInput) => Promise<boolean>
}

export function RssSourcesPage() {
  const controller = useRssSettingsController()
  const loading = controller.sources.isLoading
  const error = controller.sources.error

  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold">RSS 源</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          维护抓取源。系统每天上海时间 06:00 自动抓取、筛选并发送一条汇总。
        </p>
      </header>
      {loading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取 RSS 源…</p>}
      {error && <ErrorPanel message={error.message} retry={() => void controller.sources.refetch()} />}
      {controller.sources.isSuccess && (
        <SourcesPanel
          busy={controller.isActionLocked}
          onCreate={(input) => controller.execute({ action: "create-source", input })}
          onDelete={(source) => controller.execute({ action: "delete-source", id: source.id })}
          onUpdate={(source, input) => controller.execute({ action: "update-source", id: source.id, input })}
          sources={controller.sources.data}
        />
      )}
    </main>
  )
}

function SourcesPanel(props: SourcesPanelProps) {
  const [editing, setEditing] = useState<RssSource | null>(null)
  const [deleting, setDeleting] = useState<RssSource | null>(null)
  const [query, setQuery] = useState("")
  const keyword = query.trim().toLowerCase()
  const filteredSources = keyword
    ? props.sources.filter((source) =>
        source.name.toLowerCase().includes(keyword) || source.feed_url.toLowerCase().includes(keyword),
      )
    : props.sources
  const save = async (input: RssSourceInput) => {
    const saved = editing ? await props.onUpdate(editing, input) : await props.onCreate(input)
    if (saved) setEditing(null)
    return saved
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold">RSS 源</h2>
        <p className="text-sm text-[var(--muted)]">{props.sources.length} 个已配置源</p>
      </CardHeader>
      <CardContent>
        <SourceForm busy={props.busy} editing={editing} onCancel={() => setEditing(null)} onSubmit={save} />
        {props.sources.length === 0 && <p className="mt-6 text-sm text-[var(--muted)]">尚未配置 RSS 源。</p>}
        {props.sources.length > 0 && (
          <div className="mt-5 max-w-xs space-y-2">
            <Label htmlFor="rss-source-search">搜索</Label>
            <Input
              aria-label="搜索 RSS 源"
              id="rss-source-search"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按名称或 Feed URL 过滤"
              value={query}
            />
          </div>
        )}
        <ul className="divide-y divide-[var(--line)]">
          {filteredSources.map((source) => (
            <SourceRow
              busy={props.busy}
              key={source.id}
              onDelete={() => setDeleting(source)}
              onEdit={() => setEditing(source)}
              onUpdate={(input) => props.onUpdate(source, input)}
              source={source}
            />
          ))}
        </ul>
        {props.sources.length > 0 && filteredSources.length === 0 && (
          <p className="py-4 text-sm text-[var(--muted)]">没有匹配的 RSS 源</p>
        )}
        <ConfirmDialog
          busy={props.busy}
          confirmLabel={`确认删除 ${deleting?.name ?? "RSS 源"}`}
          description="删除后无法恢复，请确认该 RSS 源已不再需要。"
          onClose={() => setDeleting(null)}
          onConfirm={() => {
            if (!deleting) return
            void props.onDelete(deleting).then((deleted) => deleted && setDeleting(null))
          }}
          open={deleting !== null}
          title="删除 RSS 源"
        />
      </CardContent>
    </Card>
  )
}

function SourceRow(props: {
  busy: boolean
  source: RssSource
  onDelete: () => void
  onEdit: () => void
  onUpdate: (input: RssSourceInput) => Promise<boolean>
}) {
  const { source } = props
  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="font-semibold">{source.name}</p>
        <a className="block truncate text-xs" href={source.feed_url} rel="noopener noreferrer" target="_blank">
          {source.feed_url}
        </a>
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge enabled={source.enabled} />
        <Button
          aria-label={`${source.enabled ? "停用" : "启用"} ${source.name}`}
          disabled={props.busy}
          onClick={() => void props.onUpdate({
            name: source.name,
            feed_url: source.feed_url,
            enabled: !source.enabled,
          })}
          size="sm"
          variant="ghost"
        >{source.enabled ? "停用" : "启用"}</Button>
        <Button aria-label={`编辑 ${source.name}`} disabled={props.busy} onClick={props.onEdit} size="sm" variant="ghost">编辑</Button>
        <Button aria-label={`删除 ${source.name}`} disabled={props.busy} onClick={props.onDelete} size="sm" variant="danger">删除</Button>
      </div>
    </li>
  )
}

function SourceForm(props: {
  busy: boolean
  editing: RssSource | null
  onCancel: () => void
  onSubmit: (input: RssSourceInput) => Promise<boolean>
}) {
  const [name, setName] = useState("")
  const [feedUrl, setFeedUrl] = useState("")
  useEffect(() => {
    setName(props.editing?.name ?? "")
    setFeedUrl(props.editing?.feed_url ?? "")
  }, [props.editing])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const saved = await props.onSubmit({
      name: name.trim(),
      feed_url: feedUrl.trim(),
      enabled: props.editing?.enabled ?? true,
    })
    if (saved) {
      setName("")
      setFeedUrl("")
    }
  }
  return (
    <form className="grid gap-4 border-b border-[var(--line)] pb-6 md:grid-cols-[1fr_2fr_auto] md:items-end" onSubmit={submit}>
      <div><Label htmlFor="rss-source-name">RSS 源名称</Label><Input id="rss-source-name" maxLength={200} onChange={(event) => setName(event.target.value)} required value={name} /></div>
      <div><Label htmlFor="rss-feed-url">Feed URL</Label><Input id="rss-feed-url" onChange={(event) => setFeedUrl(event.target.value)} required type="url" value={feedUrl} /></div>
      <div className="flex gap-2">
        {props.editing && <Button disabled={props.busy} onClick={props.onCancel} type="button" variant="ghost">取消编辑</Button>}
        <Button disabled={props.busy} type="submit">{props.editing ? "保存 RSS 源" : "添加 RSS 源"}</Button>
      </div>
    </form>
  )
}
