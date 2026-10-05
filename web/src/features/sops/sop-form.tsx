import type { FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import type { SopFormValues, SopKind, SopStatus } from "./sop-form-model"
import { kindLabels, SOP_KINDS, SOP_STATUSES } from "./sop-form-model"

type SopFormProps = {
  values: SopFormValues
  editing: boolean
  busy: boolean
  onChange: (values: SopFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

export function SopForm(props: SopFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    props.onSubmit()
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="sop-title">标题</Label>
        <Input
          id="sop-title"
          onChange={(event) => props.onChange({ ...props.values, title: event.target.value })}
          required
          value={props.values.title}
        />
      </div>
      <div className="grid gap-4">
        <div className="space-y-2">
          <Label htmlFor="sop-kind">类型</Label>
          <select
            aria-label="类型"
            className={selectClassName}
            id="sop-kind"
            onChange={(event) => props.onChange({ ...props.values, kind: event.target.value as SopKind })}
            value={props.values.kind}
          >
            {SOP_KINDS.map((kind) => (
              <option key={kind} value={kind}>{kindLabels[kind]}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="sop-status">状态</Label>
          <select
            aria-label="状态"
            className={selectClassName}
            id="sop-status"
            onChange={(event) => props.onChange({ ...props.values, status: event.target.value as SopStatus })}
            value={props.values.status}
          >
            {SOP_STATUSES.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="sop-tags">标签</Label>
        <Input
          id="sop-tags"
          onChange={(event) => props.onChange({ ...props.values, tags: event.target.value })}
          placeholder="CRM, 销售"
          value={props.values.tags}
        />
        <p className="text-xs text-[var(--muted)]">多个标签用逗号分隔。</p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="sop-body">内容</Label>
        <textarea
          className="min-h-32 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 py-2 text-sm"
          id="sop-body"
          onChange={(event) => props.onChange({ ...props.values, body: event.target.value })}
          value={props.values.body}
        />
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button onClick={props.onCancel} type="button" variant="outline">{props.editing ? "取消编辑" : "取消"}</Button>
        <Button disabled={props.busy} type="submit">{props.editing ? "保存修改" : "添加 SOP"}</Button>
      </div>
    </form>
  )
}
