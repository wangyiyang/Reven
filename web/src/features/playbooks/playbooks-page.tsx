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

export function PlaybooksPage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)

  const playbooksQuery = useQuery({ queryKey: ["playbooks"], queryFn: () => apiRequest<Playbook[]>("/playbooks") })

  const createMutation = useMutation({
    mutationFn: (input: PlaybookForm) =>
      apiRequest<Playbook>("/playbooks", {
        method: "POST",
        body: JSON.stringify({
          title: input.title,
          kind: input.kind,
          status: input.status,
          body: input.body,
          tags: parseTags(input.tags),
        }),
      }),
    onSuccess: async () => {
      setForm(initialForm)
      await queryClient.invalidateQueries({ queryKey: ["playbooks"] })
      toast.success("Playbook 已添加")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "保存失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest(`/playbooks/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["playbooks"] })
      toast.success("Playbook 已删除")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "删除失败"),
  })

  function updateField<K extends keyof PlaybookForm>(key: K, value: PlaybookForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
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
          <h2 className="text-lg font-medium text-[var(--ink)]">添加 Playbook</h2>
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
            <div className="flex items-end md:col-span-4">
              <Button disabled={createMutation.isPending} type="submit">添加 Playbook</Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">Playbook 列表</h2>
        </CardHeader>
        <CardContent>
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
                    <Button onClick={() => deleteMutation.mutate(playbook.id)} size="sm" type="button" variant="ghost">删除</Button>
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
