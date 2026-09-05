import type { FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import type { CustomerFormValues } from "./customer-form-model"
import { CUSTOMER_STATUSES, type CustomerStatus } from "./types"

type CustomerFormProps = {
  values: CustomerFormValues
  editing: boolean
  busy: boolean
  onChange: (values: CustomerFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

export function CustomerForm(props: CustomerFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    props.onSubmit()
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      <CustomerIdentityFields {...props} />
      <CustomerActionFields {...props} />
      <CustomerNotesField {...props} />
      <CustomerFormActions {...props} />
    </form>
  )
}

function CustomerIdentityFields({ values, onChange }: CustomerFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-2">
        <Label htmlFor="crm-customer-name">客户名称</Label>
        <Input
          id="crm-customer-name"
          onChange={(event) => onChange({ ...values, name: event.target.value })}
          required
          value={values.name}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="crm-customer-status">关系状态</Label>
        <select
          className={selectClassName}
          id="crm-customer-status"
          onChange={(event) => onChange({ ...values, status: event.target.value as CustomerStatus })}
          value={values.status}
        >
          {CUSTOMER_STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="crm-customer-source">客户来源</Label>
        <Input
          id="crm-customer-source"
          onChange={(event) => onChange({ ...values, source: event.target.value })}
          placeholder="朋友介绍、官网、活动…"
          value={values.source}
        />
      </div>
    </div>
  )
}

function CustomerActionFields({ values, onChange }: CustomerFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-[1fr_14rem]">
      <div className="space-y-2">
        <Label htmlFor="crm-customer-next-action">下一步行动</Label>
        <Input
          id="crm-customer-next-action"
          onChange={(event) => onChange({ ...values, next_action: event.target.value })}
          placeholder="例如：发送报价方案"
          value={values.next_action}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="crm-customer-next-date">下次跟进日期</Label>
        <Input
          id="crm-customer-next-date"
          onChange={(event) => onChange({ ...values, next_follow_up_on: event.target.value })}
          type="date"
          value={values.next_follow_up_on}
        />
      </div>
    </div>
  )
}

function CustomerNotesField({ values, onChange }: CustomerFormProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor="crm-customer-notes">备注</Label>
      <Textarea
        className="text-[var(--ink)] placeholder:text-[var(--muted)]"
        id="crm-customer-notes"
        onChange={(event) => onChange({ ...values, notes: event.target.value })}
        placeholder="背景、需求、限制条件…"
        value={values.notes}
      />
    </div>
  )
}

function CustomerFormActions({ editing, busy, onCancel }: CustomerFormProps) {
  return (
    <div className="flex gap-2">
      <Button disabled={busy} type="submit">{editing ? "保存修改" : "添加客户"}</Button>
      {editing ? <Button onClick={onCancel} type="button" variant="ghost">取消编辑</Button> : null}
    </div>
  )
}
