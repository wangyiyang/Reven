import { useEffect, useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ErrorPanel } from "@/components/ui/error-panel"
import type { RssKeywordInput } from "./rss-api"
import { StatusBadge } from "./rss-shared"
import type { RssKeyword, RssKeywordKind } from "./types"
import { useRssSettingsController } from "./use-rss-settings-controller"

export function RssKeywordsPage() {
  const controller = useRssSettingsController()
  const loading = controller.keywords.isLoading
  const error = controller.keywords.error

  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold">RSS 关键词</h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          维护正向与反向关键词，用于每日抓取内容的自动筛选。
        </p>
      </header>
      {loading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取 RSS 关键词…</p>}
      {error && <ErrorPanel message={error.message} retry={() => void controller.keywords.refetch()} title="RSS 配置读取失败" />}
      {controller.keywords.isSuccess && (
        <KeywordSettings
          busy={controller.isActionLocked}
          keywords={controller.keywords.data}
          onCreate={(input) => controller.execute({ action: "create-keyword", input })}
          onDelete={(keyword) => controller.execute({ action: "delete-keyword", id: keyword.id })}
          onUpdate={(keyword, input) => controller.execute({ action: "update-keyword", id: keyword.id, input })}
        />
      )}
    </main>
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
    <div className="grid gap-8">
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
    </div>
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

const COLLAPSE_LIMIT = 30

function KeywordPanel(props: {
  busy: boolean
  kind: RssKeywordKind
  keywords: RssKeyword[]
  onDelete: (keyword: RssKeyword) => void
  onEdit: (keyword: RssKeyword) => void
  onUpdate: (keyword: RssKeyword, input: RssKeywordInput) => Promise<boolean>
}) {
  const [query, setQuery] = useState("")
  const [expanded, setExpanded] = useState(false)
  const filtered = props.keywords.filter((keyword) => keyword.kind === props.kind)
  const title = props.kind === "positive" ? "正向关键词" : "反向关键词"
  const term = query.trim().toLowerCase()
  const matched = term ? filtered.filter((keyword) => keyword.term.toLowerCase().includes(term)) : filtered
  const visible = term || expanded ? matched : matched.slice(0, COLLAPSE_LIMIT)
  const collapsible = !term && matched.length > COLLAPSE_LIMIT
  return (
    <Card aria-label={title} role="region">
      <CardHeader>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-[var(--muted)]">
          {term ? `${matched.length} / ${filtered.length} 个关键词` : `${filtered.length} 个关键词`}
        </p>
      </CardHeader>
      <CardContent>
        <Input
          aria-label={`搜索${title}`}
          className="mb-4"
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`搜索${title}…`}
          value={query}
        />
        {matched.length === 0 && (
          <p className="text-sm text-[var(--muted)]">
            {term ? `没有匹配「${query.trim()}」的${title}。` : `尚未配置${title}。`}
          </p>
        )}
        <ul className="flex flex-wrap gap-2">
          {visible.map((keyword) => (
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
        {collapsible && (
          <Button className="mt-3" onClick={() => setExpanded((value) => !value)} size="sm" variant="ghost">
            {expanded ? "收起" : `展开全部 ${matched.length} 条`}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
