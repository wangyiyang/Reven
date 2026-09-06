import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

import { deleteEntry, listEntries, type FinanceEntry, type FinanceEntryKind } from "./finance-api"
import { EntryFormDrawer } from "./entry-form-drawer"
import { currentMonthShanghai, formatMoney, variantForEntry } from "./finance-utils"

type LedgerFilters = {
  month: string
  kind: "" | FinanceEntryKind
  category: string
  query: string
}

const SELECT_CLASS = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm text-[var(--ink)]"

export function FinanceLedgerPage() {
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState<LedgerFilters>({ month: currentMonthShanghai(), kind: "", category: "", query: "" })
  const [editing, setEditing] = useState<FinanceEntry | null>(null)
  const [deleting, setDeleting] = useState<FinanceEntry | null>(null)

  const entriesQuery = useQuery({
    queryKey: ["finance", "entries", "ledger", filters],
    queryFn: () => listEntries({
      statuses: ["已收", "已付"],
      month: filters.month || undefined,
      kind: filters.kind || undefined,
      category: filters.category,
      query: filters.query,
    }),
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

  const entries = entriesQuery.data ?? []

  return (
    <div className="space-y-4">
      <LedgerFilterBar filters={filters} onChange={setFilters} />
      <LedgerList entries={entries} onDelete={setDeleting} onEdit={setEditing} />
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

function LedgerFilterBar({ filters, onChange }: { filters: LedgerFilters; onChange: (filters: LedgerFilters) => void }) {
  const set = (patch: Partial<LedgerFilters>) => onChange({ ...filters, ...patch })
  return (
    <div aria-label="流水筛选" className="flex flex-wrap items-end gap-3">
      <div className="space-y-2">
        <Label htmlFor="ledger-filter-month">月份</Label>
        <Input id="ledger-filter-month" onChange={(event) => set({ month: event.target.value })} type="month" value={filters.month} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="ledger-filter-kind">类型</Label>
        <select
          aria-label="类型筛选"
          className={SELECT_CLASS}
          id="ledger-filter-kind"
          onChange={(event) => set({ kind: event.target.value as LedgerFilters["kind"] })}
          value={filters.kind}
        >
          <option value="">全部</option>
          <option value="income">收入</option>
          <option value="expense">支出</option>
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="ledger-filter-category">分类</Label>
        <Input id="ledger-filter-category" onChange={(event) => set({ category: event.target.value })} placeholder="按分类筛选" value={filters.category} />
      </div>
      <div className="min-w-56 flex-1 space-y-2">
        <Label htmlFor="ledger-filter-query">搜索</Label>
        <Input id="ledger-filter-query" onChange={(event) => set({ query: event.target.value })} placeholder="按名称搜索" value={filters.query} />
      </div>
    </div>
  )
}

type LedgerListProps = {
  entries: FinanceEntry[]
  onEdit: (entry: FinanceEntry) => void
  onDelete: (entry: FinanceEntry) => void
}

function LedgerList({ entries, onEdit, onDelete }: LedgerListProps) {
  if (entries.length === 0) {
    return <p className="py-6 text-center text-sm text-[var(--muted)]">该月份暂无收支流水。</p>
  }
  return (
    <>
      <div className="grid gap-3 lg:hidden">
        {entries.map((entry) => (
          <article aria-label={`${entry.name} 移动摘要`} className="rounded-lg border border-[var(--line)] p-4" key={entry.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-[var(--ink)]">{entry.name}</p>
                <p className="mt-1 text-xs text-[var(--muted)]">{entry.occurred_on} · {entry.category ?? "未分类"}</p>
              </div>
              <p className="shrink-0 text-base font-semibold text-[var(--ink)]">{formatMoney(entry.amount_cents)}</p>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <KindBadge kind={entry.kind} />
              <RowActions entry={entry} onDelete={onDelete} onEdit={onEdit} labeled />
            </div>
          </article>
        ))}
      </div>
      <div className="hidden lg:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>名称</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>分类</TableHead>
              <TableHead className="text-right">金额</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>{entry.occurred_on}</TableCell>
                <TableCell>{entry.name}</TableCell>
                <TableCell><KindBadge kind={entry.kind} /></TableCell>
                <TableCell>{entry.category ?? "—"}</TableCell>
                <TableCell className="text-right">{formatMoney(entry.amount_cents)}</TableCell>
                <TableCell><RowActions entry={entry} onDelete={onDelete} onEdit={onEdit} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  )
}

function KindBadge({ kind }: { kind: FinanceEntryKind }) {
  return (
    <Badge className={kind === "income" ? "text-[var(--signal)]" : "text-[var(--muted)]"}>
      {kind === "income" ? "收入" : "支出"}
    </Badge>
  )
}

function RowActions({ entry, onEdit, onDelete, labeled }: {
  entry: FinanceEntry
  onEdit: (entry: FinanceEntry) => void
  onDelete: (entry: FinanceEntry) => void
  labeled?: boolean
}) {
  return (
    <div className="flex gap-1">
      <Button aria-label={labeled ? `编辑 ${entry.name}` : undefined} onClick={() => onEdit(entry)} size="sm" type="button" variant="ghost">
        编辑
      </Button>
      <Button aria-label={labeled ? `删除 ${entry.name}` : undefined} onClick={() => onDelete(entry)} size="sm" type="button" variant="ghost">
        删除
      </Button>
    </div>
  )
}
