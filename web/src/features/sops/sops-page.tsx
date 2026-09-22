import * as Dialog from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { ResponsiveList } from "@/components/responsive-list"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { copyPlainText } from "@/lib/clipboard"
import { useResourceList } from "@/lib/use-resource-list"

type Sop = {
  id: string
  title: string
  kind: "procedure" | "checklist" | "script" | "method"
  status: "草稿" | "试行" | "正式"
  body: string
  tags: string[]
  created_at: string
  updated_at: string
}

type SopForm = {
  title: string
  kind: Sop["kind"]
  status: Sop["status"]
  tags: string
  body: string
}

const initialForm: SopForm = { title: "", kind: "procedure", status: "草稿", tags: "", body: "" }

function parseTags(value: string) {
  return value
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
}

const kindLabels: Record<Sop["kind"], string> = {
  procedure: "程序",
  checklist: "Checklist",
  script: "话术",
  method: "方法论",
}

function toPayload(input: SopForm) {
  return {
    title: input.title,
    kind: input.kind,
    status: input.status,
    body: input.body,
    tags: parseTags(input.tags),
  }
}

function toForm(sop: Sop): SopForm {
  return {
    title: sop.title,
    kind: sop.kind,
    status: sop.status,
    tags: sop.tags.join(", "),
    body: sop.body,
  }
}

export function SopsPage() {
  const list = useResourceList<Sop, SopForm>({
    key: "sops",
    path: "/sops",
    initialForm,
    initialFilters: { kind: "", status: "", query: "" },
    toPayload,
    toForm,
    validate: (form) => (form.title.trim() && form.body.trim() ? null : "请填写标题和内容"),
    messages: {
      created: "SOP 已添加",
      updated: "SOP 已更新",
      deleted: "SOP 已删除",
      saveFailed: "保存失败",
      updateFailed: "更新失败",
      deleteFailed: "删除失败",
    },
  })
  const { form, filters } = list
  const [viewing, setViewing] = useState<Sop | null>(null)

  async function copyViewingBody() {
    if (!viewing) return
    try {
      await copyPlainText(viewing.body)
      toast.success("内容已复制")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制失败")
    }
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">SOP（标准作业流程）</h1>
        <p className="text-sm text-[var(--muted)]">沉淀程序、Checklist、话术和方法论，状态按 草稿 → 试行 → 正式 管理。</p>
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">{list.editingId ? "编辑 SOP" : "添加 SOP"}</h2>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-4" onSubmit={list.submit}>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="sop-title">标题</Label>
              <Input id="sop-title" onChange={(event) => list.setField("title", event.target.value)} required value={form.title} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sop-kind">类型</Label>
              <select
                aria-label="类型"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="sop-kind"
                onChange={(event) => list.setField("kind", event.target.value as Sop["kind"])}
                value={form.kind}
              >
                <option value="procedure">程序</option>
                <option value="checklist">Checklist</option>
                <option value="script">话术</option>
                <option value="method">方法论</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="sop-status">状态</Label>
              <select
                aria-label="状态"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="sop-status"
                onChange={(event) => list.setField("status", event.target.value as Sop["status"])}
                value={form.status}
              >
                <option value="草稿">草稿</option>
                <option value="试行">试行</option>
                <option value="正式">正式</option>
              </select>
            </div>
            <div className="space-y-2 md:col-span-4">
              <Label htmlFor="sop-tags">标签</Label>
              <Input id="sop-tags" onChange={(event) => list.setField("tags", event.target.value)} placeholder="CRM, 销售" value={form.tags} />
              <p className="text-xs text-[var(--muted)]">多个标签用逗号分隔。</p>
            </div>
            <div className="space-y-2 md:col-span-4">
              <Label htmlFor="sop-body">内容</Label>
              <textarea
                className="min-h-32 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 py-2 text-sm"
                id="sop-body"
                onChange={(event) => list.setField("body", event.target.value)}
                value={form.body}
              />
            </div>
            <div className="flex items-end gap-2 md:col-span-4">
              <Button disabled={list.isSaving} type="submit">
                {list.editingId ? "保存修改" : "添加 SOP"}
              </Button>
              {list.editingId ? (
                <Button onClick={list.cancelEdit} type="button" variant="ghost">
                  取消编辑
                </Button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">SOP 列表</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="sops-filter-kind">类型筛选</Label>
              <select
                aria-label="类型筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="sops-filter-kind"
                onChange={(event) => list.setFilters((current) => ({ ...current, kind: event.target.value }))}
                value={filters.kind}
              >
                <option value="">全部</option>
                <option value="procedure">程序</option>
                <option value="checklist">Checklist</option>
                <option value="script">话术</option>
                <option value="method">方法论</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="sops-filter-status">状态筛选</Label>
              <select
                aria-label="状态筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="sops-filter-status"
                onChange={(event) => list.setFilters((current) => ({ ...current, status: event.target.value }))}
                value={filters.status}
              >
                <option value="">全部</option>
                <option value="草稿">草稿</option>
                <option value="试行">试行</option>
                <option value="正式">正式</option>
              </select>
            </div>
            <div className="min-w-56 flex-1 space-y-2">
              <Label htmlFor="sops-filter-query">搜索</Label>
              <Input
                aria-label="搜索 SOP"
                id="sops-filter-query"
                onChange={(event) => list.setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="按标题、内容或标签搜索"
                value={filters.query}
              />
            </div>
          </div>
          <ResponsiveList
            actions={[
              { label: "查看", ariaLabel: (sop) => `查看 ${sop.title}`, onClick: setViewing },
              { label: "编辑", ariaLabel: (sop) => `编辑 ${sop.title}`, onClick: list.startEdit },
              { label: "删除", ariaLabel: (sop) => `删除 ${sop.title}`, onClick: list.requestRemove },
            ]}
            card={(sop) => ({
              title: sop.title,
              status: <Badge>{sop.status}</Badge>,
              body: <p className="mt-2 line-clamp-2 whitespace-pre-wrap text-xs text-[var(--muted)]">{sop.body}</p>,
              meta: (
                <div className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>{kindLabels[sop.kind]}</span>
                  {sop.tags.length ? <span>{sop.tags.join("、")}</span> : null}
                </div>
              ),
            })}
            cardLabel={(sop) => `${sop.title} 移动摘要`}
            columns={[
              {
                header: "标题",
                cell: (sop) => (
                  <>
                    <div className="font-medium text-[var(--ink)]">{sop.title}</div>
                    <div className="line-clamp-2 whitespace-pre-wrap text-xs text-[var(--muted)]">{sop.body}</div>
                  </>
                ),
              },
              { header: "类型", cell: (sop) => kindLabels[sop.kind] },
              { header: "状态", cell: (sop) => <Badge>{sop.status}</Badge> },
              { header: "标签", cell: (sop) => (sop.tags.length ? sop.tags.join("、") : "—") },
            ]}
            emptyText="暂无 SOP，先沉淀一条。"
            items={list.itemsQuery.data}
            keyOf={(sop) => sop.id}
          />
        </CardContent>
      </Card>

      <Dialog.Root onOpenChange={(open) => !open && setViewing(null)} open={viewing !== null}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
          <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[80vh] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg">
            {viewing ? (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-2">
                    <Dialog.Title className="text-lg font-semibold text-[var(--ink)]">{viewing.title}</Dialog.Title>
                    <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                      <span>{kindLabels[viewing.kind]}</span>
                      <Badge>{viewing.status}</Badge>
                      {viewing.tags.length ? <span>{viewing.tags.join("、")}</span> : null}
                    </div>
                  </div>
                  <Dialog.Close asChild>
                    <Button aria-label="关闭" size="sm" type="button" variant="ghost"><X size={16} /></Button>
                  </Dialog.Close>
                </div>
                <Dialog.Description className="sr-only">查看 SOP 完整内容</Dialog.Description>
                <div className="whitespace-pre-wrap rounded-md border border-[var(--line)] bg-[var(--faint)] p-4 text-sm leading-6 text-[var(--ink)]">
                  {viewing.body}
                </div>
                <div className="flex justify-end">
                  <Button onClick={copyViewingBody} size="sm" type="button" variant="outline">复制内容</Button>
                </div>
              </div>
            ) : null}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmDialog
        busy={list.isRemoving}
        confirmLabel={`确认删除「${list.deleting?.title ?? ""}」`}
        description="删除后无法恢复，请确认这条 SOP 已不再需要。"
        onClose={list.cancelRemove}
        onConfirm={list.confirmRemove}
        open={list.deleting !== null}
        title="删除 SOP"
      />
    </main>
  )
}
