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
import { Textarea } from "@/components/ui/textarea"

import { createFollowUp, crmKeys, deleteFollowUp, emptyToNull, listContacts, listFollowUps, updateFollowUp } from "./crm-api"
import { todayInShanghai } from "./date-utils"
import { FOLLOW_UP_KINDS, type Contact, type FollowUp, type FollowUpInput, type FollowUpKind } from "./types"

type FollowUpFormValues = {
  contact_id: string
  kind: FollowUpKind
  occurred_on: string
  summary: string
  next_action: string
  next_follow_up_on: string
  set_as_current: boolean
}

function emptyFollowUp(): FollowUpFormValues {
  return { contact_id: "", kind: "会议", occurred_on: todayInShanghai(), summary: "", next_action: "", next_follow_up_on: "", set_as_current: true }
}

export function FollowUpsSection({ customerId }: { customerId: string }) {
  const [form, setForm] = useState<FollowUpFormValues>(emptyFollowUp)
  const [editing, setEditing] = useState<FollowUp | null>(null)
  const [deleting, setDeleting] = useState<FollowUp | null>(null)
  const contactsQuery = useQuery({ queryKey: crmKeys.contacts(customerId), queryFn: () => listContacts(customerId) })
  const followUpsQuery = useQuery({ queryKey: crmKeys.followUps(customerId), queryFn: () => listFollowUps(customerId) })
  const reset = () => { setForm(emptyFollowUp()); setEditing(null) }
  const createMutation = useCreateFollowUp(customerId, reset)
  const updateMutation = useUpdateFollowUp(customerId, reset)
  const deleteMutation = useDeleteFollowUp(customerId, () => setDeleting(null))

  function submit() {
    const error = validateFollowUp(form)
    if (error) return toast.error(error)
    const input = followUpFormToInput(form)
    if (editing) updateMutation.mutate({ followUpId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(followUp: FollowUp) {
    setEditing(followUp)
    setForm(followUpToForm(followUp))
  }

  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">跟进记录</h2></CardHeader>
      <CardContent className="space-y-5">
        <FollowUpForm busy={createMutation.isPending || updateMutation.isPending} contacts={contactsQuery.data ?? []} editing={editing !== null} onCancel={reset} onChange={setForm} onSubmit={submit} values={form} />
        <FollowUpList failed={followUpsQuery.isError} followUps={followUpsQuery.data} loading={followUpsQuery.isLoading} onDelete={setDeleting} onEdit={startEdit} onRetry={() => void followUpsQuery.refetch()} />
      </CardContent>
      <FollowUpDeleteDialog followUp={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
    </Card>
  )
}

type FollowUpFormProps = {
  values: FollowUpFormValues
  contacts: Contact[]
  editing: boolean
  busy: boolean
  onChange: (values: FollowUpFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

function FollowUpForm(props: FollowUpFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); props.onSubmit() }
  return (
    <form className="space-y-4 rounded-lg border border-[var(--line)] p-4" onSubmit={submit}>
      <FollowUpMetaFields {...props} />
      <div className="space-y-2"><Label htmlFor="crm-follow-up-summary">沟通内容</Label><Textarea id="crm-follow-up-summary" onChange={(event) => props.onChange({ ...props.values, summary: event.target.value })} required value={props.values.summary} /></div>
      <FollowUpActionFields {...props} />
      {props.editing ? <p className="text-xs text-[var(--muted)]">修正历史记录不会改写客户当前下一步行动。</p> : <SyncCurrentField {...props} />}
      <div className="flex gap-2"><Button disabled={props.busy} size="sm" type="submit">{props.editing ? "保存跟进" : "记录跟进"}</Button>{props.editing ? <Button onClick={props.onCancel} size="sm" type="button" variant="ghost">取消</Button> : null}</div>
    </form>
  )
}

function FollowUpMetaFields({ values, contacts, onChange }: FollowUpFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-2"><Label htmlFor="crm-follow-up-kind">方式</Label><select className={selectClassName} id="crm-follow-up-kind" onChange={(event) => onChange({ ...values, kind: event.target.value as FollowUpKind })} value={values.kind}>{FOLLOW_UP_KINDS.map((kind) => <option key={kind}>{kind}</option>)}</select></div>
      <div className="space-y-2"><Label htmlFor="crm-follow-up-date">发生日期</Label><Input id="crm-follow-up-date" onChange={(event) => onChange({ ...values, occurred_on: event.target.value })} required type="date" value={values.occurred_on} /></div>
      <div className="space-y-2"><Label htmlFor="crm-follow-up-contact">关联联系人</Label><select className={selectClassName} id="crm-follow-up-contact" onChange={(event) => onChange({ ...values, contact_id: event.target.value })} value={values.contact_id}><option value="">不关联</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.name}</option>)}</select></div>
    </div>
  )
}

function FollowUpActionFields({ values, onChange }: FollowUpFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-[1fr_14rem]">
      <div className="space-y-2"><Label htmlFor="crm-follow-up-action">约定的下一步</Label><Input id="crm-follow-up-action" onChange={(event) => onChange({ ...values, next_action: event.target.value })} value={values.next_action} /></div>
      <div className="space-y-2"><Label htmlFor="crm-follow-up-next-date">下次跟进日期</Label><Input id="crm-follow-up-next-date" onChange={(event) => onChange({ ...values, next_follow_up_on: event.target.value })} type="date" value={values.next_follow_up_on} /></div>
    </div>
  )
}

function SyncCurrentField({ values, onChange }: FollowUpFormProps) {
  return <label className="flex items-center gap-2 text-sm"><input checked={values.set_as_current} onChange={(event) => onChange({ ...values, set_as_current: event.target.checked })} type="checkbox" />同步为客户当前下一步行动</label>
}

type FollowUpListProps = { followUps: FollowUp[] | undefined; loading: boolean; failed: boolean; onRetry: () => void; onEdit: (value: FollowUp) => void; onDelete: (value: FollowUp) => void }

function FollowUpList(props: FollowUpListProps) {
  if (props.loading) return <p className="text-sm text-[var(--muted)]">正在加载跟进记录…</p>
  if (props.failed) return <div className="flex items-center gap-2 text-sm text-[var(--muted)]"><span>跟进记录加载失败。</span><Button onClick={props.onRetry} size="sm" type="button" variant="outline">重试</Button></div>
  if (props.followUps?.length === 0) return <p className="text-sm text-[var(--muted)]">暂无跟进记录。</p>
  return <div className="space-y-3">{props.followUps?.map((item) => <FollowUpCard followUp={item} key={item.id} onDelete={props.onDelete} onEdit={props.onEdit} />)}</div>
}

function FollowUpCard({ followUp, onEdit, onDelete }: { followUp: FollowUp; onEdit: (value: FollowUp) => void; onDelete: (value: FollowUp) => void }) {
  return (
    <article aria-label={`${followUp.occurred_on} ${followUp.kind} 跟进记录`} className="border-l-2 border-[var(--line)] py-2 pl-4">
      <div className="flex flex-wrap items-center gap-2"><Badge>{followUp.kind}</Badge><span className="text-xs text-[var(--muted)]">{followUp.occurred_on}</span>{followUp.contact_name_snapshot ? <span className="text-xs text-[var(--muted)]">· {followUp.contact_name_snapshot}</span> : null}</div>
      <p className="mt-2 whitespace-pre-wrap text-sm">{followUp.summary}</p>
      {followUp.next_action ? <p className="mt-2 text-xs text-[var(--muted)]">下一步：{followUp.next_action}{followUp.next_follow_up_on ? ` · ${followUp.next_follow_up_on}` : ""}</p> : null}
      <div className="mt-2 flex gap-1"><Button onClick={() => onEdit(followUp)} size="sm" type="button" variant="ghost">编辑</Button><Button onClick={() => onDelete(followUp)} size="sm" type="button" variant="ghost">删除</Button></div>
    </article>
  )
}

function useCreateFollowUp(customerId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: FollowUpInput) => createFollowUp(customerId, input), onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: crmKeys.followUps(customerId) }), queryClient.invalidateQueries({ queryKey: crmKeys.customer(customerId) }), queryClient.invalidateQueries({ queryKey: crmKeys.customers })]); onSaved(); toast.success("跟进已记录") }, onError: showError })
}

function useUpdateFollowUp(customerId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: ({ followUpId, input }: { followUpId: string; input: FollowUpInput }) => updateFollowUp(customerId, followUpId, input), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: crmKeys.followUps(customerId) }); onSaved(); toast.success("跟进已更新") }, onError: showError })
}

function useDeleteFollowUp(customerId: string, onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (followUpId: string) => deleteFollowUp(customerId, followUpId), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: crmKeys.followUps(customerId) }); onDeleted(); toast.success("跟进已删除") }, onError: showError })
}

type DeleteMutation = ReturnType<typeof useDeleteFollowUp>

function FollowUpDeleteDialog({ followUp, mutation, onClose }: { followUp: FollowUp | null; mutation: DeleteMutation; onClose: () => void }) {
  return <ConfirmDialog busy={mutation.isPending} confirmLabel="确认删除这条跟进" description="仅删除历史记录，不会改写客户当前下一步行动。" onClose={onClose} onConfirm={() => { if (followUp) mutation.mutate(followUp.id) }} open={followUp !== null} title="删除跟进" />
}

function followUpToForm(value: FollowUp): FollowUpFormValues {
  return { contact_id: value.contact_id ?? "", kind: value.kind, occurred_on: value.occurred_on, summary: value.summary, next_action: value.next_action ?? "", next_follow_up_on: value.next_follow_up_on ?? "", set_as_current: false }
}

function followUpFormToInput(value: FollowUpFormValues): FollowUpInput {
  return { contact_id: emptyToNull(value.contact_id), kind: value.kind, occurred_on: value.occurred_on, summary: value.summary.trim(), next_action: emptyToNull(value.next_action), next_follow_up_on: emptyToNull(value.next_follow_up_on), set_as_current: value.set_as_current }
}

function validateFollowUp(value: FollowUpFormValues): string | null {
  if (!value.summary.trim()) return "请填写沟通内容"
  if (value.next_follow_up_on && !value.next_action.trim()) return "设置跟进日期时请填写下一步行动"
  if (value.set_as_current && !value.next_action.trim()) return "同步当前行动时请填写下一步行动"
  return null
}

function showError(error: unknown) { toast.error(error instanceof Error ? error.message : "请求失败") }
