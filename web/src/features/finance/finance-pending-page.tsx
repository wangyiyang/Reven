import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

import { ConfirmSettleDialog } from "./confirm-settle-dialog"
import { EntryFormDrawer } from "./entry-form-drawer"
import { deleteEntry, listEntries, type FinanceEntry } from "./finance-api"
import {
  PENDING_GROUP_LABELS,
  formatMoney,
  groupPendingEntries,
  todayShanghai,
  variantForEntry,
  type PendingGroup,
} from "./finance-utils"

const GROUP_ORDER: PendingGroup[] = ["overdue", "upcoming", "later", "unscheduled"]

type PendingTab = "receivable" | "payable"

export function FinancePendingPage() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab: PendingTab = searchParams.get("tab") === "payable" ? "payable" : "receivable"
  const groupParam = searchParams.get("group")
  const groupFilter = GROUP_ORDER.includes(groupParam as PendingGroup) ? (groupParam as PendingGroup) : null
  const [confirming, setConfirming] = useState<FinanceEntry | null>(null)
  const [editing, setEditing] = useState<FinanceEntry | null>(null)
  const [deleting, setDeleting] = useState<FinanceEntry | null>(null)

  const entriesQuery = useQuery({
    queryKey: ["finance", "entries", "pending", tab],
    queryFn: () => listEntries({ statuses: [tab === "receivable" ? "应收" : "应付"] }),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteEntry(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["finance"] })
      toast.success("财务记录已删除")
      setDeleting(null)
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录删除失败"),
  })

  const today = todayShanghai()
  const groups = groupPendingEntries(entriesQuery.data ?? [], today)
  const visibleGroups = GROUP_ORDER.filter((group) => !groupFilter || group === groupFilter)
  const confirmLabel = tab === "receivable" ? "确认收款" : "确认付款"

  function updateParams(patch: { tab?: PendingTab; group?: PendingGroup | null }) {
    const next = new URLSearchParams(searchParams)
    if (patch.tab) next.set("tab", patch.tab)
    if (patch.group) next.set("group", patch.group)
    if (patch.group === null) next.delete("group")
    setSearchParams(next)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div aria-label="待收待付方向" className="flex gap-1">
          {(["receivable", "payable"] as const).map((value) => (
            <button
              aria-pressed={tab === value}
              className={cn(
                "rounded-md border px-3 py-2 text-sm font-semibold transition-colors",
                tab === value
                  ? "border-[var(--signal)] text-[var(--signal)]"
                  : "border-[var(--line)] text-[var(--muted)] hover:text-[var(--ink)]",
              )}
              key={value}
              onClick={() => updateParams({ tab: value })}
              type="button"
            >
              {value === "receivable" ? "待收" : "待付"}
            </button>
          ))}
        </div>
        {groupFilter ? (
          <div className="flex items-center gap-2">
            <Badge className="text-[var(--signal)]">仅看：{PENDING_GROUP_LABELS[groupFilter]}</Badge>
            <Button onClick={() => updateParams({ group: null })} size="sm" type="button" variant="ghost">
              清除筛选
            </Button>
          </div>
        ) : null}
      </div>
      {visibleGroups.map((group) => (
        <PendingGroupSection
          confirmLabel={confirmLabel}
          entries={groups[group]}
          group={group}
          key={group}
          onConfirm={setConfirming}
          onDelete={setDeleting}
          onEdit={setEditing}
          today={today}
        />
      ))}
      {visibleGroups.every((group) => groups[group].length === 0) ? (
        <p className="py-6 text-center text-sm text-[var(--muted)]">
          {groupFilter ? "该分组暂无款项。" : tab === "receivable" ? "暂无待收款项。" : "暂无待付款项。"}
        </p>
      ) : null}
      <ConfirmSettleDialog entry={confirming} onClose={() => setConfirming(null)} />
      {editing ? (
        <EntryFormDrawer entry={editing} onClose={() => setEditing(null)} open variant={variantForEntry(editing)} />
      ) : null}
      <ConfirmDialog
        busy={deleteMutation.isPending}
        confirmLabel={`确认删除「${deleting?.name ?? ""}」`}
        description="删除后无法恢复，请确认这条财务记录已不再需要。"
        onClose={() => setDeleting(null)}
        onConfirm={() => { if (deleting) deleteMutation.mutate(deleting.id) }}
        open={deleting !== null}
        title="删除财务记录"
      />
    </div>
  )
}

type GroupSectionProps = {
  group: PendingGroup
  entries: FinanceEntry[]
  today: string
  confirmLabel: string
  onConfirm: (entry: FinanceEntry) => void
  onEdit: (entry: FinanceEntry) => void
  onDelete: (entry: FinanceEntry) => void
}

function PendingGroupSection(props: GroupSectionProps) {
  const { group, entries } = props
  if (entries.length === 0) return null
  return (
    <section aria-label={PENDING_GROUP_LABELS[group]} className="space-y-3">
      <h2 className="text-sm font-semibold text-[var(--ink)]">
        {PENDING_GROUP_LABELS[group]}（{entries.length}）
      </h2>
      <div className="grid gap-3 lg:hidden">
        {entries.map((entry) => (
          <article aria-label={`${entry.name} 移动摘要`} className="rounded-lg border border-[var(--line)] p-4" key={entry.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-[var(--ink)]">{entry.name}</p>
                <p className="mt-1 text-xs text-[var(--muted)]">{entry.source ?? "未填写收付款对象"}</p>
                <DueMeta entry={entry} group={group} today={props.today} />
              </div>
              <p className="shrink-0 text-base font-semibold text-[var(--ink)]">{formatMoney(entry.amount_cents)}</p>
            </div>
            <div className="mt-3">
              <PendingActions {...props} entry={entry} labeled />
            </div>
          </article>
        ))}
      </div>
      <div className="hidden lg:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>名称</TableHead>
              <TableHead>收付款对象</TableHead>
              <TableHead>预计收付日期</TableHead>
              <TableHead className="text-right">金额</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>{entry.name}</TableCell>
                <TableCell>{entry.source ?? "—"}</TableCell>
                <TableCell><DueMeta entry={entry} group={group} today={props.today} /></TableCell>
                <TableCell className="text-right">{formatMoney(entry.amount_cents)}</TableCell>
                <TableCell><PendingActions {...props} entry={entry} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}

function DueMeta({ entry, group, today }: { entry: FinanceEntry; group: PendingGroup; today: string }) {
  if (group === "unscheduled") {
    return <p className="mt-1 text-xs text-[var(--muted)]">日期未定，可编辑补录</p>
  }
  if (group === "overdue" && entry.due_on) {
    return (
      <p className="mt-1 text-xs text-[var(--danger)]">
        {entry.due_on} · 逾期 {overdueDays(entry.due_on, today)} 天
      </p>
    )
  }
  return <p className="mt-1 text-xs text-[var(--muted)]">{entry.due_on}</p>
}

function PendingActions({ entry, confirmLabel, onConfirm, onEdit, onDelete, labeled }: GroupSectionProps & {
  entry: FinanceEntry
  labeled?: boolean
}) {
  const label = (action: string) => (labeled ? `${action} ${entry.name}` : undefined)
  return (
    <div className="flex flex-wrap gap-1">
      <Button aria-label={label(confirmLabel)} onClick={() => onConfirm(entry)} size="sm" type="button" variant="outline">
        {confirmLabel}
      </Button>
      <Button aria-label={label("编辑")} onClick={() => onEdit(entry)} size="sm" type="button" variant="ghost">
        编辑
      </Button>
      <Button aria-label={label("删除")} onClick={() => onDelete(entry)} size="sm" type="button" variant="ghost">
        删除
      </Button>
    </div>
  )
}

function overdueDays(dueOn: string, today: string): number {
  return Math.max(0, Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${dueOn}T00:00:00Z`)) / 86_400_000))
}
