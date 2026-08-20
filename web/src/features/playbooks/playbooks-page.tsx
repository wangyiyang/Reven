import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiRequest } from "@/lib/api"

type Playbook = {
  id: string
  title: string
  kind: "sop" | "checklist" | "script" | "method"
  status: "草稿" | "试行" | "正式"
  body: string
  tags: string[]
  created_at: string
  updated_at: string
}

type PlaybookForm = {
  title: string
  kind: Playbook["kind"]
  status: Playbook["status"]
  tags: string
  body: string
}

const initialForm: PlaybookForm = { title: "", kind: "sop", status: "草稿", tags: "", body: "" }

function parseTags(value: string) {
  return value
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
}

const kindLabels: Record<Playbook["kind"], string> = {
  sop: "SOP",
  checklist: "Checklist",
  script: "话术",
  method: "方法论",
}

function toPayload(input: PlaybookForm) {
  return {
    title: input.title,
    kind: input.kind,
    status: input.status,
    body: input.body,
    tags: parseTags(input.tags),
  }
}

export function PlaybooksPage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [filters, setFilters] = useState({ kind: "", status: "", query: "" })

  const playbooksQuery = useQuery({
    queryKey: ["playbooks", filters],
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters.kind) params.set("kind", filters.kind)
      if (filters.status) params.set("status", filters.status)
      if (filters.query.trim()) params.set("query", filters.query.trim())
      const suffix = params.size ? `?${params.toString()}` : ""
      return apiRequest<Playbook[]>(`/playbooks${suffix}`)
    },
  })

  async function invalidatePlaybooks() {
    await queryClient.invalidateQueries({ queryKey: ["playbooks"] })
  }

  const createMutation = useMutation({
    mutationFn: (input: PlaybookForm) =>
      apiRequest<Playbook>("/playbooks", { method: "POST", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async () => {
      setForm(initialForm)
      await invalidatePlaybooks()
      toast.success("Playbook 已添加")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "保存失败"),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: PlaybookForm }) =>
      apiRequest<Playbook>(`/playbooks/${id}`, { method: "PUT", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async () => {
      setForm(initialForm)
      setEditingId(null)
      await invalidatePlaybooks()
      toast.success("Playbook 已更新")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "更新失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest(`/playbooks/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidatePlaybooks()
      toast.success("Playbook 已删除")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "删除失败"),
  })

  function updateField<K extends keyof PlaybookForm>(key: K, value: PlaybookForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function startEdit(playbook: Playbook) {
    setEditingId(playbook.id)
    setForm({
      title: playbook.title,
      kind: playbook.kind,
      status: playbook.status,
      tags: playbook.tags.join(", "),
      body: playbook.body,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(initialForm)
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form.title.trim() || !form.body.trim()) {
      toast.error("请填写标题和内容")
      return
    }
    if (editingId) {
      updateMutation.mutate({ id: editingId, input: form })
      return
    }
    createMutation.mutate(form)
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">SOP / 话术库</h1>
        <p className="text-sm text-[var(--muted)]">沉淀 SOP、Checklist、话术和方法论，状态按 草稿 → 试行 → 正式 管理。</p>
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">{editingId ? "编辑 Playbook" : "添加 Playbook"}</h2>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-4" onSubmit={onSubmit}>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="playbook-title">标题</Label>
              <Input id="playbook-title" onChange={(event) => updateField("title", event.target.value)} required value={form.title} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="playbook-kind">类型</Label>
              <select
                aria-label="类型"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="playbook-kind"
                onChange={(event) => updateField("kind", event.target.value as Playbook["kind"])}
                value={form.kind}
              >
                <option value="sop">SOP</option>
                <option value="checklist">Checklist</option>
                <option value="script">话术</option>
                <option value="method">方法论</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="playbook-status">状态</Label>
              <select
                aria-label="状态"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="playbook-status"
                onChange={(event) => updateField("status", event.target.value as Playbook["status"])}
                value={form.status}
              >
                <option value="草稿">草稿</option>
                <option value="试行">试行</option>
                <option value="正式">正式</option>
              </select>
            </div>
            <div className="space-y-2 md:col-span-4">
              <Label htmlFor="playbook-tags">标签</Label>
              <Input id="playbook-tags" onChange={(event) => updateField("tags", event.target.value)} placeholder="CRM, 销售" value={form.tags} />
              <p className="text-xs text-[var(--muted)]">多个标签用逗号分隔。</p>
            </div>
            <div className="space-y-2 md:col-span-4">
              <Label htmlFor="playbook-body">内容</Label>
              <textarea
                className="min-h-32 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 py-2 text-sm"
                id="playbook-body"
                onChange={(event) => updateField("body", event.target.value)}
                value={form.body}
              />
            </div>
            <div className="flex items-end gap-2 md:col-span-4">
              <Button disabled={createMutation.isPending || updateMutation.isPending} type="submit">
                {editingId ? "保存修改" : "添加 Playbook"}
              </Button>
              {editingId ? (
                <Button onClick={cancelEdit} type="button" variant="ghost">
                  取消编辑
                </Button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">Playbook 列表</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="playbooks-filter-kind">类型筛选</Label>
              <select
                aria-label="类型筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="playbooks-filter-kind"
                onChange={(event) => setFilters((current) => ({ ...current, kind: event.target.value }))}
                value={filters.kind}
              >
                <option value="">全部</option>
                <option value="sop">SOP</option>
                <option value="checklist">Checklist</option>
                <option value="script">话术</option>
                <option value="method">方法论</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="playbooks-filter-status">状态筛选</Label>
              <select
                aria-label="状态筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="playbooks-filter-status"
                onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
                value={filters.status}
              >
                <option value="">全部</option>
                <option value="草稿">草稿</option>
                <option value="试行">试行</option>
                <option value="正式">正式</option>
              </select>
            </div>
            <div className="min-w-56 flex-1 space-y-2">
              <Label htmlFor="playbooks-filter-query">搜索</Label>
              <Input
                aria-label="搜索 Playbook"
                id="playbooks-filter-query"
                onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="按标题、内容或标签搜索"
                value={filters.query}
              />
            </div>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>标题</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>标签</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {playbooksQuery.data?.length === 0 ? (
                <TableRow>
                  <TableCell className="py-10 text-center text-[var(--muted)]" colSpan={5}>
                    暂无 Playbook，先沉淀一条 SOP。
                  </TableCell>
                </TableRow>
              ) : null}
              {(playbooksQuery.data ?? []).map((playbook) => (
                <TableRow key={playbook.id}>
                  <TableCell>
                    <div className="font-medium text-[var(--ink)]">{playbook.title}</div>
                    <div className="line-clamp-2 whitespace-pre-wrap text-xs text-[var(--muted)]">{playbook.body}</div>
                  </TableCell>
                  <TableCell>{kindLabels[playbook.kind]}</TableCell>
                  <TableCell><Badge>{playbook.status}</Badge></TableCell>
                  <TableCell>{playbook.tags.length ? playbook.tags.join("、") : "—"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button onClick={() => startEdit(playbook)} size="sm" type="button" variant="ghost">
                        编辑
                      </Button>
                      <Button
                        onClick={() => {
                          if (!window.confirm(`确认删除 Playbook「${playbook.title}」？此操作不可恢复。`)) return
                          deleteMutation.mutate(playbook.id)
                        }}
                        size="sm"
                        type="button"
                        variant="ghost"
                      >
                        删除
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </main>
  )
}
