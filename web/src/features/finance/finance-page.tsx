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
  const entriesQuery = useQuery({ queryKey: ["finance", "entries"], queryFn: () => apiRequest<FinanceEntry[]>("/finance/entries") })
  const summaryQuery = useQuery({ queryKey: ["finance", "summary"], queryFn: () => apiRequest<FinanceSummary>("/finance/summary") })
  const createMutation = useMutation({
    mutationFn: (payload: FinanceEntryPayload) =>
      apiRequest<FinanceEntry>("/finance/entries", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: async () => {
      toast.success("财务记录已添加")
      setForm(emptyForm)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["finance", "entries"] }),
        queryClient.invalidateQueries({ queryKey: ["finance", "summary"] }),
      ])
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录添加失败"),
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
    createMutation.mutate({
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
    })
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">财务收支</h1>
        <p className="text-sm text-[var(--muted)]">一人公司现金流台账：收入、花销、应收、跑道。</p>
      </div>

      <section aria-label="财务汇总" className="grid gap-4 md:grid-cols-5">
        <SummaryCard label="收入" value={summary?.income_cents} />
        <SummaryCard label="花销" value={summary?.expense_cents} />
        <SummaryCard label="净额" value={summary?.net_cents} />
        <SummaryCard label="应收" value={summary?.receivable_cents} />
        <SummaryCard label="应付" value={summary?.payable_cents} />
      </section>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">添加记录</h2>
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
            <div className="flex items-end">
              <Button type="submit" disabled={createMutation.isPending}>添加记录</Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">收支记录</h2>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>分类</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">金额</TableHead>
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
                </TableRow>
              ))}
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-[var(--muted)]">
                    还没有财务记录。
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
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
