import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiRequest } from "@/lib/api"

type FinanceEntry = {
  id: string
  kind: "income" | "expense"
  name: string
  amount_cents: number
  category: string | null
  occurred_on: string
  due_on: string | null
  recurrence: string | null
  source: string | null
  status: string
  notes: string | null
}

type FinanceSummary = {
  income_cents: number
  expense_cents: number
  net_cents: number
  receivable_cents: number
  payable_cents: number
}

type FinanceEntryPayload = {
  kind: "income" | "expense"
  name: string
  amount: number
  category: string | null
  occurred_on: string
  due_on: string | null
  recurrence: string | null
  source: string | null
  status: string
  notes: string | null
}

const emptyForm = {
  kind: "expense" as "income" | "expense",
  name: "",
  amount: "",
  category: "",
  occurred_on: new Date().toISOString().slice(0, 10),
  status: "已记录",
}

export function FinancePage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [filters, setFilters] = useState({ kind: "", query: "" })
  const [deleting, setDeleting] = useState<FinanceEntry | null>(null)

  const entriesQuery = useQuery({
    queryKey: ["finance", "entries", filters],
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters.kind) params.set("kind", filters.kind)
      if (filters.query.trim()) params.set("query", filters.query.trim())
      const suffix = params.size ? `?${params.toString()}` : ""
      return apiRequest<FinanceEntry[]>(`/finance/entries${suffix}`)
    },
  })
  const summaryQuery = useQuery({ queryKey: ["finance", "summary"], queryFn: () => apiRequest<FinanceSummary>("/finance/summary") })

  async function invalidateFinance() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["finance", "entries"] }),
      queryClient.invalidateQueries({ queryKey: ["finance", "summary"] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: (payload: FinanceEntryPayload) =>
      apiRequest<FinanceEntry>("/finance/entries", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: async () => {
      toast.success("财务记录已添加")
      setForm(emptyForm)
      await invalidateFinance()
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录添加失败"),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: FinanceEntryPayload }) =>
      apiRequest<FinanceEntry>(`/finance/entries/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: async () => {
      toast.success("财务记录已更新")
      setForm(emptyForm)
      setEditingId(null)
      await invalidateFinance()
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录更新失败"),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest<null>(`/finance/entries/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await invalidateFinance()
      toast.success("财务记录已删除")
      setDeleting(null)
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录删除失败"),
  })

  const entries = entriesQuery.data ?? []
  const summary = summaryQuery.data

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const amount = Number(form.amount)
    if (!form.name.trim() || !Number.isFinite(amount) || amount <= 0 || !form.occurred_on) {
      toast.error("请填写名称、有效金额和日期")
      return
    }
    const payload: FinanceEntryPayload = {
      kind: form.kind,
      name: form.name.trim(),
      amount,
      category: form.category.trim() || null,
      occurred_on: form.occurred_on,
      due_on: null,
      recurrence: null,
      source: null,
      status: form.status,
      notes: null,
    }
    if (editingId) {
      updateMutation.mutate({ id: editingId, payload })
      return
    }
    createMutation.mutate(payload)
  }

  function startEdit(entry: FinanceEntry) {
    setEditingId(entry.id)
    setForm({
      kind: entry.kind,
      name: entry.name,
      amount: String(entry.amount_cents / 100),
      category: entry.category ?? "",
      occurred_on: entry.occurred_on,
      status: entry.status,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(emptyForm)
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">财务收支</h1>
        <p className="text-sm text-[var(--muted)]">一人公司现金流台账：现金收付与应收应付。</p>
      </div>

      <section aria-label="财务汇总" className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5 md:gap-4">
        <SummaryCard label="已收收入" value={summary?.income_cents} />
        <SummaryCard label="已付花销" value={summary?.expense_cents} />
        <SummaryCard label="现金净额" value={summary?.net_cents} />
        <SummaryCard label="应收" value={summary?.receivable_cents} />
        <SummaryCard label="应付" value={summary?.payable_cents} />
      </section>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">{editingId ? "编辑记录" : "添加记录"}</h2>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-5" onSubmit={submit}>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="finance-name">名称</Label>
              <Input
                id="finance-name"
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="finance-amount">金额</Label>
              <Input
                id="finance-amount"
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => setForm((current) => ({ ...current, amount: event.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="finance-kind">类型</Label>
              <select
                id="finance-kind"
                aria-label="类型"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                value={form.kind}
                onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value as "income" | "expense" }))}
              >
                <option value="expense">支出</option>
                <option value="income">收入</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="finance-date">日期</Label>
              <Input
                id="finance-date"
                type="date"
                value={form.occurred_on}
                onChange={(event) => setForm((current) => ({ ...current, occurred_on: event.target.value }))}
              />
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="finance-category">分类</Label>
              <Input
                id="finance-category"
                value={form.category}
                onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="finance-status">状态</Label>
              <select
                id="finance-status"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                value={form.status}
                onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
              >
                <option value="已记录">已记录</option>
                <option value="应收">应收</option>
                <option value="已收">已收</option>
                <option value="应付">应付</option>
                <option value="已付">已付</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <Button className="w-full sm:w-auto" type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                {editingId ? "保存修改" : "添加记录"}
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
          <h2 className="text-lg font-medium text-[var(--ink)]">收支记录</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="finance-filter-kind">类型筛选</Label>
              <select
                aria-label="类型筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="finance-filter-kind"
                onChange={(event) => setFilters((current) => ({ ...current, kind: event.target.value }))}
                value={filters.kind}
              >
                <option value="">全部</option>
                <option value="income">收入</option>
                <option value="expense">支出</option>
              </select>
            </div>
            <div className="min-w-56 flex-1 space-y-2">
              <Label htmlFor="finance-filter-query">搜索</Label>
              <Input
                aria-label="搜索记录"
                id="finance-filter-query"
                onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="按名称或分类搜索"
                value={filters.query}
              />
            </div>
          </div>
          <div className="grid gap-3 lg:hidden">
            {entries.map((entry) => (
              <article
                aria-label={`${entry.name} 移动摘要`}
                className="rounded-lg border border-[var(--line)] p-4"
                key={entry.id}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-semibold text-[var(--ink)]">{entry.name}</p>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {entry.occurred_on} · {entry.category ?? "未分类"} · {entry.status}
                    </p>
                  </div>
                  <p className="shrink-0 text-base font-semibold text-[var(--ink)]">{formatMoney(entry.amount_cents)}</p>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <Badge className={entry.kind === "income" ? "text-emerald-600" : "text-[var(--muted)]"}>
                    {entry.kind === "income" ? "收入" : "支出"}
                  </Badge>
                  <div className="flex gap-1">
                    <Button aria-label={`编辑 ${entry.name}`} onClick={() => startEdit(entry)} size="sm" type="button" variant="ghost">
                      编辑
                    </Button>
                    <Button aria-label={`删除 ${entry.name}`} onClick={() => setDeleting(entry)} size="sm" type="button" variant="ghost">
                      删除
                    </Button>
                  </div>
                </div>
              </article>
            ))}
            {entries.length === 0 ? (
              <p className="py-6 text-center text-sm text-[var(--muted)]">还没有财务记录。</p>
            ) : null}
          </div>
          <div className="hidden lg:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>分类</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">金额</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell>{entry.occurred_on}</TableCell>
                  <TableCell>{entry.name}</TableCell>
                  <TableCell>
                    <Badge className={entry.kind === "income" ? "text-emerald-600" : "text-[var(--muted)]"}>
                      {entry.kind === "income" ? "收入" : "支出"}
                    </Badge>
                  </TableCell>
                  <TableCell>{entry.category ?? "—"}</TableCell>
                  <TableCell>{entry.status}</TableCell>
                  <TableCell className="text-right">{formatMoney(entry.amount_cents)}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button onClick={() => startEdit(entry)} size="sm" type="button" variant="ghost">
                        编辑
                      </Button>
                      <Button
                        onClick={() => setDeleting(entry)}
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
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-[var(--muted)]">
                    还没有财务记录。
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        busy={deleteMutation.isPending}
        confirmLabel={`确认删除「${deleting?.name ?? ""}」`}
        description="删除后无法恢复，请确认这条财务记录已不再需要。"
        onClose={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return
          deleteMutation.mutate(deleting.id)
        }}
        open={deleting !== null}
        title="删除财务记录"
      />
    </main>
  )
}

function SummaryCard({ label, value }: { label: string; value: number | undefined }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-[var(--muted)]">{label}</p>
        <p className="mt-2 text-lg font-semibold text-[var(--ink)]">{value === undefined ? "—" : formatMoney(value)}</p>
      </CardContent>
    </Card>
  )
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(cents / 100)
}
