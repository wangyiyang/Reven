import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { FormEvent, ReactNode } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Drawer } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import { createEntry, updateEntry, type FinanceEntry, type FinanceEntryPayload } from "./finance-api"
import { ENTRY_VARIANT_CONFIG, todayShanghai, type EntryFormVariant, type EntryVariantConfig } from "./finance-utils"

type VariantConfig = EntryVariantConfig

type FormState = {
  name: string
  amount: string
  occurred_on: string
  category: string
  source: string
  due_on: string
  notes: string
}

type EntryFormDrawerProps = {
  open: boolean
  variant: EntryFormVariant
  entry?: FinanceEntry | null
  onClose: () => void
}

export function EntryFormDrawer(props: EntryFormDrawerProps) {
  if (!props.open) return null
  return <EntryFormDrawerInner {...props} />
}

function EntryFormDrawerInner({ variant, entry = null, onClose }: EntryFormDrawerProps) {
  const config = ENTRY_VARIANT_CONFIG[variant]
  const queryClient = useQueryClient()
  const [form, setForm] = useState<FormState>(() => ({
    name: entry?.name ?? "",
    amount: entry ? String(entry.amount_cents / 100) : "",
    occurred_on: entry?.occurred_on ?? todayShanghai(),
    category: entry?.category ?? "",
    source: entry?.source ?? "",
    due_on: entry?.due_on ?? "",
    notes: entry?.notes ?? "",
  }))
  const set = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }))

  const mutation = useMutation({
    mutationFn: (payload: FinanceEntryPayload) =>
      entry ? updateEntry(entry.id, payload) : createEntry(payload),
    onSuccess: async () => {
      toast.success(entry ? "财务记录已更新" : "财务记录已添加")
      await queryClient.invalidateQueries({ queryKey: ["finance"] })
      onClose()
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "财务记录保存失败"),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const error = validateForm(form, config)
    if (error) {
      toast.error(error)
      return
    }
    mutation.mutate(buildPayload(config, form, entry))
  }

  return (
    <Drawer onClose={onClose} open title={entry ? "编辑财务记录" : config.title}>
      <form className="space-y-4" onSubmit={submit}>
        <Field htmlFor="entry-form-name" label="名称">
          <Input id="entry-form-name" onChange={(event) => set({ name: event.target.value })} value={form.name} />
        </Field>
        <Field htmlFor="entry-form-amount" label="金额">
          <Input id="entry-form-amount" inputMode="decimal" onChange={(event) => set({ amount: event.target.value })} value={form.amount} />
        </Field>
        {config.settled ? (
          <>
            <Field htmlFor="entry-form-occurred-on" label="实际收付日期">
              <Input id="entry-form-occurred-on" onChange={(event) => set({ occurred_on: event.target.value })} type="date" value={form.occurred_on} />
            </Field>
            <Field htmlFor="entry-form-category" label="分类（可选）">
              <Input id="entry-form-category" onChange={(event) => set({ category: event.target.value })} value={form.category} />
            </Field>
          </>
        ) : (
          <>
            <Field htmlFor="entry-form-source" label="收付款对象">
              <Input id="entry-form-source" onChange={(event) => set({ source: event.target.value })} value={form.source} />
            </Field>
            <Field htmlFor="entry-form-due-on" label="预计收付日期">
              <Input id="entry-form-due-on" onChange={(event) => set({ due_on: event.target.value })} type="date" value={form.due_on} />
            </Field>
            <Field htmlFor="entry-form-notes" label="备注（可选）">
              <Textarea id="entry-form-notes" onChange={(event) => set({ notes: event.target.value })} value={form.notes} />
            </Field>
          </>
        )}
        <div className="flex justify-end gap-3 pt-2">
          <Button onClick={onClose} type="button" variant="outline">取消</Button>
          <Button disabled={mutation.isPending} type="submit">{entry ? "保存修改" : config.title}</Button>
        </div>
      </form>
    </Drawer>
  )
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}

function validateForm(form: FormState, config: VariantConfig): string | null {
  const amount = Number(form.amount)
  if (!form.name.trim()) return "请填写名称"
  if (!Number.isFinite(amount) || amount <= 0) return "请填写有效金额"
  if (config.settled && !form.occurred_on) return "请选择实际收付日期"
  if (!config.settled && !form.source.trim()) return "请填写收付款对象"
  if (!config.settled && !form.due_on) return "请选择预计收付日期"
  return null
}

function buildPayload(config: VariantConfig, form: FormState, entry: FinanceEntry | null): FinanceEntryPayload {
  return {
    kind: config.kind,
    status: config.status,
    name: form.name.trim(),
    amount: Number(form.amount),
    occurred_on: config.settled ? form.occurred_on : entry?.occurred_on ?? todayShanghai(),
    due_on: config.settled ? entry?.due_on ?? null : form.due_on,
    category: config.settled ? form.category.trim() || null : entry?.category ?? null,
    source: config.settled ? entry?.source ?? null : form.source.trim(),
    notes: config.settled ? entry?.notes ?? null : form.notes.trim() || null,
    recurrence: entry?.recurrence ?? null,
  }
}
