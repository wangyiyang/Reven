import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, CalendarClock } from "lucide-react"
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

import { emptyToNull } from "../crm/crm-api"
import { todayInShanghai } from "../crm/date-utils"

import { createInteraction, deleteInteraction, listInteractions, talentsKeys, updateInteraction } from "./talents-api"
import { INTERACTION_CHANNELS, type InteractionChannel, type TalentInteraction, type TalentInteractionInput } from "./types"

type InteractionFormValues = {
  channel: InteractionChannel
  occurred_on: string
  summary: string
  next_action: string
  next_due_on: string
}

function emptyInteraction(): InteractionFormValues {
  return { channel: "微信", occurred_on: todayInShanghai(), summary: "", next_action: "", next_due_on: "" }
}

export function InteractionsSection({ talentId }: { talentId: string }) {
  const [form, setForm] = useState<InteractionFormValues>(emptyInteraction)
  const [editing, setEditing] = useState<TalentInteraction | null>(null)
  const [deleting, setDeleting] = useState<TalentInteraction | null>(null)
  const interactionsQuery = useQuery({ queryKey: talentsKeys.interactions(talentId), queryFn: () => listInteractions(talentId) })
  const reset = () => { setForm(emptyInteraction()); setEditing(null) }
  const createMutation = useCreateInteraction(talentId, reset)
  const updateMutation = useUpdateInteraction(talentId, reset)
  const deleteMutation = useDeleteInteraction(talentId, () => setDeleting(null))

  function submit() {
    const error = validateInteraction(form)
    if (error) return toast.error(error)
    const input = interactionFormToInput(form)
    if (editing) updateMutation.mutate({ interactionId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(interaction: TalentInteraction) {
    setEditing(interaction)
    setForm(interactionToForm(interaction))
  }

  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">跟进记录</h2></CardHeader>
      <CardContent className="space-y-5">
        <InteractionForm busy={createMutation.isPending || updateMutation.isPending} editing={editing !== null} onCancel={reset} onChange={setForm} onSubmit={submit} values={form} />
        <InteractionList failed={interactionsQuery.isError} interactions={interactionsQuery.data} loading={interactionsQuery.isLoading} onDelete={setDeleting} onEdit={startEdit} onRetry={() => void interactionsQuery.refetch()} />
      </CardContent>
      <InteractionDeleteDialog interaction={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
    </Card>
  )
}

type InteractionFormProps = {
  values: InteractionFormValues
  editing: boolean
  busy: boolean
  onChange: (values: InteractionFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

function InteractionForm(props: InteractionFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); props.onSubmit() }
  const { values, onChange } = props
  return (
    <form className="space-y-4 rounded-lg border border-[var(--line)] p-4" onSubmit={submit}>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="talent-interaction-channel">方式</Label><select className={selectClassName} id="talent-interaction-channel" onChange={(event) => onChange({ ...values, channel: event.target.value as InteractionChannel })} value={values.channel}>{INTERACTION_CHANNELS.map((channel) => <option key={channel}>{channel}</option>)}</select></div>
        <div className="space-y-2"><Label htmlFor="talent-interaction-date">发生日期</Label><Input id="talent-interaction-date" onChange={(event) => onChange({ ...values, occurred_on: event.target.value })} required type="date" value={values.occurred_on} /></div>
      </div>
      <div className="space-y-2"><Label htmlFor="talent-interaction-summary">沟通内容</Label><Textarea id="talent-interaction-summary" onChange={(event) => onChange({ ...values, summary: event.target.value })} required value={values.summary} /></div>
      <div className="grid gap-4 md:grid-cols-[1fr_14rem]">
        <div className="space-y-2"><Label htmlFor="talent-interaction-action">约定的下一步</Label><Input id="talent-interaction-action" onChange={(event) => onChange({ ...values, next_action: event.target.value })} value={values.next_action} /></div>
        <div className="space-y-2"><Label htmlFor="talent-interaction-due">下次跟进日期</Label><Input id="talent-interaction-due" onChange={(event) => onChange({ ...values, next_due_on: event.target.value })} type="date" value={values.next_due_on} /></div>
      </div>
      <div className="flex gap-2"><Button disabled={props.busy} size="sm" type="submit">{props.editing ? "保存跟进" : "记录跟进"}</Button>{props.editing ? <Button onClick={props.onCancel} size="sm" type="button" variant="ghost">取消</Button> : null}</div>
    </form>
  )
}

type InteractionListProps = { interactions: TalentInteraction[] | undefined; loading: boolean; failed: boolean; onRetry: () => void; onEdit: (value: TalentInteraction) => void; onDelete: (value: TalentInteraction) => void }

function InteractionList(props: InteractionListProps) {
  if (props.loading) return <p className="text-sm text-[var(--muted)]">正在加载跟进记录…</p>
  if (props.failed) return <div className="flex items-center gap-2 text-sm text-[var(--muted)]"><span>跟进记录加载失败。</span><Button onClick={props.onRetry} size="sm" type="button" variant="outline">重试</Button></div>
  if (props.interactions?.length === 0) return <p className="text-sm text-[var(--muted)]">暂无跟进记录。</p>
  return <div className="space-y-3">{props.interactions?.map((item) => <InteractionCard interaction={item} key={item.id} onDelete={props.onDelete} onEdit={props.onEdit} />)}</div>
}

function InteractionCard({ interaction, onEdit, onDelete }: { interaction: TalentInteraction; onEdit: (value: TalentInteraction) => void; onDelete: (value: TalentInteraction) => void }) {
  return (
    <article aria-label={`${interaction.occurred_on} ${interaction.channel} 跟进记录`} className="border-l-2 border-[var(--line)] py-2 pl-4">
      <div className="flex flex-wrap items-center gap-2"><Badge>{interaction.channel}</Badge><span className="text-xs text-[var(--muted)]">{interaction.occurred_on}</span><DueState dueOn={interaction.next_due_on} /></div>
      {interaction.summary ? <p className="mt-2 whitespace-pre-wrap text-sm">{interaction.summary}</p> : null}
      {interaction.next_action ? <p className="mt-2 text-xs text-[var(--muted)]">下一步：{interaction.next_action}{interaction.next_due_on ? ` · ${interaction.next_due_on}` : ""}</p> : null}
      <div className="mt-2 flex gap-1"><Button onClick={() => onEdit(interaction)} size="sm" type="button" variant="ghost">编辑</Button><Button onClick={() => onDelete(interaction)} size="sm" type="button" variant="ghost">删除</Button></div>
    </article>
  )
}

function DueState({ dueOn }: { dueOn: string | null }) {
  if (!dueOn) return null
  const today = todayInShanghai()
  if (dueOn < today) return <span className="flex items-center gap-1 text-xs text-[var(--danger)]"><AlertTriangle aria-hidden size={13} />已逾期</span>
  if (dueOn === today) return <span className="flex items-center gap-1 text-xs font-semibold"><CalendarClock aria-hidden size={13} />今天到期</span>
  return null
}

function useCreateInteraction(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: TalentInteractionInput) => createInteraction(talentId, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: talentsKeys.interactions(talentId) }),
        queryClient.invalidateQueries({ queryKey: talentsKeys.talent(talentId) }),
        queryClient.invalidateQueries({ queryKey: talentsKeys.talents }),
      ])
      onSaved()
      toast.success("跟进已记录")
    },
    onError: showError,
  })
}

function useUpdateInteraction(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ interactionId, input }: { interactionId: string; input: TalentInteractionInput }) => updateInteraction(interactionId, input),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.interactions(talentId) }); onSaved(); toast.success("跟进已更新") },
    onError: showError,
  })
}

function useDeleteInteraction(talentId: string, onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (interactionId: string) => deleteInteraction(interactionId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: talentsKeys.interactions(talentId) }),
        queryClient.invalidateQueries({ queryKey: talentsKeys.talents }),
      ])
      onDeleted()
      toast.success("跟进已删除")
    },
    onError: showError,
  })
}

type DeleteMutation = ReturnType<typeof useDeleteInteraction>

function InteractionDeleteDialog({ interaction, mutation, onClose }: { interaction: TalentInteraction | null; mutation: DeleteMutation; onClose: () => void }) {
  return <ConfirmDialog busy={mutation.isPending} confirmLabel="确认删除这条跟进" description="仅删除这条跟进记录，人才档案不受影响。" onClose={onClose} onConfirm={() => { if (interaction) mutation.mutate(interaction.id) }} open={interaction !== null} title="删除跟进" />
}

function interactionToForm(value: TalentInteraction): InteractionFormValues {
  return { channel: value.channel, occurred_on: value.occurred_on, summary: value.summary ?? "", next_action: value.next_action ?? "", next_due_on: value.next_due_on ?? "" }
}

function interactionFormToInput(value: InteractionFormValues): TalentInteractionInput {
  return { channel: value.channel, occurred_on: value.occurred_on, summary: emptyToNull(value.summary), next_action: emptyToNull(value.next_action), next_due_on: emptyToNull(value.next_due_on) }
}

function validateInteraction(value: InteractionFormValues): string | null {
  if (!value.summary.trim()) return "请填写沟通内容"
  if (value.next_due_on && !value.next_action.trim()) return "设置跟进日期时请填写下一步行动"
  return null
}

function showError(error: unknown) { toast.error(error instanceof Error ? error.message : "请求失败") }
