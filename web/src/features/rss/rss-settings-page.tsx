import { useEffect, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RssKeywordInput, RssSourceInput } from "./rss-api"
import type { RssKeyword, RssKeywordKind, RssSource } from "./types"
import { useRssSettingsController } from "./use-rss-settings-controller"

type SourcesPanelProps = {
  sources: RssSource[]
  busy: boolean
  onCreate: (input: RssSourceInput) => Promise<boolean>
  onDelete: (source: RssSource) => Promise<boolean>
  onUpdate: (source: RssSource, input: RssSourceInput) => Promise<boolean>
}

export function RssSettingsPage() {
  const controller = useRssSettingsController()
  const loading = controller.sources.isLoading || controller.keywords.isLoading
  const error = controller.sources.error ?? controller.keywords.error

  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeader />
      {loading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取 RSS 配置…</p>}
      {error && <ErrorPanel message={error.message} retry={() => void Promise.all([controller.sources.refetch(), controller.keywords.refetch()])} />}
      {controller.sources.isSuccess && controller.keywords.isSuccess && (
        <div className="grid gap-8">
          <SourcesPanel
            busy={controller.isActionLocked}
            onCreate={(input) => controller.execute({ action: "create-source", input })}
            onDelete={(source) => controller.execute({ action: "delete-source", id: source.id })}
            onUpdate={(source, input) => controller.execute({ action: "update-source", id: source.id, input })}
            sources={controller.sources.data}
          />
          <KeywordSettings
            busy={controller.isActionLocked}
            keywords={controller.keywords.data}
            onCreate={(input) => controller.execute({ action: "create-keyword", input })}
            onDelete={(keyword) => controller.execute({ action: "delete-keyword", id: keyword.id })}
            onUpdate={(keyword, input) => controller.execute({ action: "update-keyword", id: keyword.id, input })}
          />
        </div>
      )}
    </main>
  )
}

function PageHeader() {
  return (
    <header className="mb-10">
      <h1 className="text-2xl font-semibold">RSS 内容发现配置</h1>
      <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
        维护抓取源与正反向关键词。系统每天上海时间 06:00 自动抓取、筛选并发送一条汇总。
      </p>
    </header>
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

function KeywordSettings(props: {
  busy: boolean
  keywords: RssKeyword[]
  onCreate: (input: RssKeywordInput) => Promise<boolean>
  onDelete: (keyword: RssKeyword) => Promise<boolean>
  onUpdate: (keyword: RssKeyword, input: RssKeywordInput) => Promise<boolean>
}) {
  const [editing, setEditing] = useState<RssKeyword | null>(null)
  const [deleting, setDeleting] = useState<RssKeyword | null>(null)
  const save = async (input: RssKeywordInput) => {
    const saved = editing ? await props.onUpdate(editing, input) : await props.onCreate(input)
    if (saved) setEditing(null)
    return saved
  }
  return (
    <>
      <KeywordForm busy={props.busy} editing={editing} onCancel={() => setEditing(null)} onSubmit={save} />
      <div className="grid gap-6 lg:grid-cols-2">
        <KeywordPanel busy={props.busy} kind="positive" keywords={props.keywords} onDelete={setDeleting} onEdit={setEditing} onUpdate={props.onUpdate} />
        <KeywordPanel busy={props.busy} kind="negative" keywords={props.keywords} onDelete={setDeleting} onEdit={setEditing} onUpdate={props.onUpdate} />
      </div>
      <ConfirmDialog
        busy={props.busy}
        confirmLabel={`确认删除 ${deleting?.term ?? "关键词"}`}
        description="删除后无法恢复，请确认该关键词已不再需要。"
        onClose={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return
          void props.onDelete(deleting).then((deleted) => deleted && setDeleting(null))
        }}
        open={deleting !== null}
        title="删除关键词"
      />
    </>
  )
}

function KeywordForm(props: {
  busy: boolean
  editing: RssKeyword | null
  onCancel: () => void
  onSubmit: (input: RssKeywordInput) => Promise<boolean>
}) {
  const [term, setTerm] = useState("")
  const [kind, setKind] = useState<RssKeywordKind>("positive")
  useEffect(() => {
    setTerm(props.editing?.term ?? "")
    setKind(props.editing?.kind ?? "positive")
  }, [props.editing])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const saved = await props.onSubmit({ term: term.trim(), kind, enabled: props.editing?.enabled ?? true })
    if (saved) setTerm("")
  }
  return (
    <Card>
      <CardContent className="pt-6">
        <form className="grid gap-4 md:grid-cols-[2fr_1fr_auto] md:items-end" onSubmit={submit}>
          <div><Label htmlFor="rss-keyword-term">关键词</Label><Input id="rss-keyword-term" maxLength={200} onChange={(event) => setTerm(event.target.value)} required value={term} /></div>
          <div>
            <Label htmlFor="rss-keyword-kind">关键词类型</Label>
            <select
              className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm outline-none focus:border-[var(--signal)]"
              id="rss-keyword-kind"
              onChange={(event) => setKind(event.target.value === "negative" ? "negative" : "positive")}
              value={kind}
            >
              <option value="positive">正向关键词</option>
              <option value="negative">反向关键词</option>
            </select>
          </div>
          <div className="flex gap-2">
            {props.editing && <Button disabled={props.busy} onClick={props.onCancel} type="button" variant="ghost">取消编辑</Button>}
            <Button disabled={props.busy} type="submit">{props.editing ? "保存关键词" : "添加关键词"}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function KeywordPanel(props: {
  busy: boolean
  kind: RssKeywordKind
  keywords: RssKeyword[]
  onDelete: (keyword: RssKeyword) => void
  onEdit: (keyword: RssKeyword) => void
  onUpdate: (keyword: RssKeyword, input: RssKeywordInput) => Promise<boolean>
}) {
  const filtered = props.keywords.filter((keyword) => keyword.kind === props.kind)
  const title = props.kind === "positive" ? "正向关键词" : "反向关键词"
  return (
    <Card aria-label={title} role="region">
      <CardHeader>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-[var(--muted)]">{filtered.length} 个关键词</p>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 && <p className="text-sm text-[var(--muted)]">尚未配置{title}。</p>}
        <ul className="flex flex-wrap gap-2">
          {filtered.map((keyword) => (
            <li className="flex items-center gap-2 rounded-md border border-[var(--line)] px-3 py-2 text-sm" key={keyword.id}>
              <span>{keyword.term}</span><StatusBadge enabled={keyword.enabled} />
              <Button
                aria-label={`${keyword.enabled ? "停用" : "启用"} ${keyword.term}`}
                disabled={props.busy}
                onClick={() => void props.onUpdate(keyword, {
                  term: keyword.term,
                  kind: keyword.kind,
                  enabled: !keyword.enabled,
                })}
                size="sm"
                variant="ghost"
              >{keyword.enabled ? "停用" : "启用"}</Button>
              <Button aria-label={`编辑 ${keyword.term}`} disabled={props.busy} onClick={() => props.onEdit(keyword)} size="sm" variant="ghost">编辑</Button>
              <Button aria-label={`删除 ${keyword.term}`} disabled={props.busy} onClick={() => props.onDelete(keyword)} size="sm" variant="danger">删除</Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ enabled }: { enabled: boolean }) {
  return <Badge className={enabled ? "text-[var(--signal)]" : "text-[var(--muted)]"}>{enabled ? "已启用" : "已停用"}</Badge>
}

function ErrorPanel({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert">
      <p>RSS 配置读取失败：{message}</p>
      <Button className="mt-4" onClick={retry} size="sm" variant="outline">重新读取</Button>
    </div>
  )
}
