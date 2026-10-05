import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { ResponsiveList } from "@/components/responsive-list"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Drawer } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { copyPlainText } from "@/lib/clipboard"
import { useResourceList } from "@/lib/use-resource-list"

import { SopFormDrawer } from "./sop-form-drawer"
import type { Sop, SopFormValues } from "./sop-form-model"
import { EMPTY_SOP_FORM, kindLabels, sopFormToPayload, sopToForm, validateSopForm } from "./sop-form-model"

export function SopsPage() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const list = useResourceList<Sop, SopFormValues>({
    key: "sops",
    path: "/sops",
    initialForm: EMPTY_SOP_FORM,
    initialFilters: { kind: "", status: "", query: "" },
    toPayload: sopFormToPayload,
    toForm: sopToForm,
    validate: validateSopForm,
    messages: {
      created: "SOP 已添加",
      updated: "SOP 已更新",
      deleted: "SOP 已删除",
      saveFailed: "保存失败",
      updateFailed: "更新失败",
      deleteFailed: "删除失败",
    },
    onSaved: () => setDrawerOpen(false),
  })
  const { form, filters } = list
  const [viewing, setViewing] = useState<Sop | null>(null)
  // 抽屉退出动画期间 viewing 已置空，用 ref 留住最后查看的 SOP，避免面板滑出时内容消失
  const lastViewingRef = useRef<Sop | null>(null)
  useEffect(() => {
    if (viewing) lastViewingRef.current = viewing
  }, [viewing])
  const shownSop = viewing ?? lastViewingRef.current

  function closeDrawer() {
    if (list.editingId) list.cancelEdit()
    else setDrawerOpen(false)
  }

  async function copyViewingBody() {
    if (!shownSop) return
    try {
      await copyPlainText(shownSop.body)
      toast.success("内容已复制")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "复制失败")
    }
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-[var(--ink)]">SOP（标准作业流程）</h1>
          <p className="text-sm text-[var(--muted)]">沉淀程序、Checklist、话术和方法论，状态按 草稿 → 试行 → 正式 管理。</p>
        </div>
        <Button onClick={() => setDrawerOpen(true)} type="button">新建 SOP</Button>
      </div>

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

      <SopFormDrawer
        busy={list.isSaving}
        editing={list.editingId !== null}
        onChange={list.setForm}
        onClose={closeDrawer}
        onSubmit={list.submit}
        open={drawerOpen || list.editingId !== null}
        values={form}
      />

      <Drawer
        description={shownSop ? `查看 SOP「${shownSop.title}」完整内容` : undefined}
        footer={(
          <div className="flex justify-end">
            <Button onClick={copyViewingBody} size="sm" type="button" variant="outline">复制内容</Button>
          </div>
        )}
        onClose={() => setViewing(null)}
        open={viewing !== null}
        title={shownSop?.title ?? ""}
      >
        {shownSop ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
              <span>{kindLabels[shownSop.kind]}</span>
              <Badge>{shownSop.status}</Badge>
              {shownSop.tags.length ? <span>{shownSop.tags.join("、")}</span> : null}
            </div>
            <div className="whitespace-pre-wrap rounded-md border border-[var(--line)] bg-[var(--faint)] p-4 text-sm leading-6 text-[var(--ink)]">
              {shownSop.body}
            </div>
          </div>
        ) : null}
      </Drawer>

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
