import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import { emptyToNull } from "../crm/crm-api"

import {
  createExperience,
  deleteExperience,
  formatMonth,
  listExperiences,
  talentsKeys,
  updateExperience,
} from "./talents-api"
import type { TalentExperience, TalentExperienceInput } from "./types"

type ExperienceFormValues = {
  company: string
  title: string
  description: string
  start_on: string
  end_on: string
}

const EMPTY_EXPERIENCE: ExperienceFormValues = { company: "", title: "", description: "", start_on: "", end_on: "" }

export function ExperiencesSection({ talentId }: { talentId: string }) {
  const [form, setForm] = useState<ExperienceFormValues>(EMPTY_EXPERIENCE)
  const [editing, setEditing] = useState<TalentExperience | null>(null)
  const [deleting, setDeleting] = useState<TalentExperience | null>(null)
  const experiencesQuery = useQuery({ queryKey: talentsKeys.experiences(talentId), queryFn: () => listExperiences(talentId) })
  const reset = () => { setForm(EMPTY_EXPERIENCE); setEditing(null) }
  const createMutation = useCreateExperience(talentId, reset)
  const updateMutation = useUpdateExperience(talentId, reset)
  const deleteMutation = useDeleteExperience(talentId, () => setDeleting(null))

  function submit() {
    const error = validateExperience(form)
    if (error) return toast.error(error)
    const input = experienceFormToInput(form)
    if (editing) updateMutation.mutate({ experienceId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(experience: TalentExperience) {
    setEditing(experience)
    setForm(experienceToForm(experience))
  }

  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">工作履历</h2></CardHeader>
      <CardContent className="space-y-5">
        <ExperienceForm busy={createMutation.isPending || updateMutation.isPending} editing={editing !== null} onCancel={reset} onChange={setForm} onSubmit={submit} values={form} />
        <ExperienceList experiences={experiencesQuery.data} failed={experiencesQuery.isError} loading={experiencesQuery.isLoading} onDelete={setDeleting} onEdit={startEdit} onRetry={() => void experiencesQuery.refetch()} />
      </CardContent>
      <ExperienceDeleteDialog experience={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
    </Card>
  )
}

type ExperienceFormProps = {
  values: ExperienceFormValues
  editing: boolean
  busy: boolean
  onChange: (values: ExperienceFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

function ExperienceForm(props: ExperienceFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); props.onSubmit() }
  const { values, onChange } = props
  return (
    <form className="space-y-4 rounded-lg border border-[var(--line)] p-4" onSubmit={submit}>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="talent-experience-company">公司</Label><Input id="talent-experience-company" onChange={(event) => onChange({ ...values, company: event.target.value })} required value={values.company} /></div>
        <div className="space-y-2"><Label htmlFor="talent-experience-title">职务</Label><Input id="talent-experience-title" onChange={(event) => onChange({ ...values, title: event.target.value })} required value={values.title} /></div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="talent-experience-start">开始月份</Label><Input id="talent-experience-start" onChange={(event) => onChange({ ...values, start_on: event.target.value })} required type="date" value={values.start_on} /></div>
        <div className="space-y-2"><Label htmlFor="talent-experience-end">结束月份</Label><Input id="talent-experience-end" onChange={(event) => onChange({ ...values, end_on: event.target.value })} placeholder="留空表示至今" type="date" value={values.end_on} /></div>
      </div>
      <div className="space-y-2"><Label htmlFor="talent-experience-description">经历描述</Label><Textarea id="talent-experience-description" onChange={(event) => onChange({ ...values, description: event.target.value })} placeholder="职责、代表项目（可留空）" value={values.description} /></div>
      <div className="flex gap-2"><Button disabled={props.busy} size="sm" type="submit">{props.editing ? "保存履历" : "添加履历"}</Button>{props.editing ? <Button onClick={props.onCancel} size="sm" type="button" variant="ghost">取消</Button> : null}</div>
    </form>
  )
}

type ExperienceListProps = {
  experiences: TalentExperience[] | undefined
  loading: boolean
  failed: boolean
  onRetry: () => void
  onEdit: (value: TalentExperience) => void
  onDelete: (value: TalentExperience) => void
}

function ExperienceList(props: ExperienceListProps) {
  if (props.loading) return <p className="text-sm text-[var(--muted)]">正在加载工作履历…</p>
  if (props.failed) return <div className="flex items-center gap-2 text-sm text-[var(--muted)]"><span>工作履历加载失败。</span><Button onClick={props.onRetry} size="sm" type="button" variant="outline">重试</Button></div>
  if (props.experiences?.length === 0) return <p className="text-sm text-[var(--muted)]">暂无履历，在上方录入一段工作经历完善画像。</p>
  return <div className="space-y-3">{props.experiences?.map((item) => <ExperienceCard experience={item} key={item.id} onDelete={props.onDelete} onEdit={props.onEdit} />)}</div>
}

function ExperienceCard({ experience, onEdit, onDelete }: { experience: TalentExperience; onEdit: (value: TalentExperience) => void; onDelete: (value: TalentExperience) => void }) {
  return (
    <article aria-label={`${experience.company} ${experience.title} 履历`} className="border-l-2 border-[var(--line)] py-2 pl-4">
      <div className="flex flex-wrap items-baseline gap-2"><span className="font-semibold">{experience.company}</span><span className="text-sm">{experience.title}</span><span className="text-xs text-[var(--muted)]">{formatMonth(experience.start_on)} — {formatMonth(experience.end_on)}</span></div>
      {experience.description ? <p className="mt-2 whitespace-pre-wrap text-sm">{experience.description}</p> : null}
      <div className="mt-2 flex gap-1"><Button onClick={() => onEdit(experience)} size="sm" type="button" variant="ghost">编辑</Button><Button onClick={() => onDelete(experience)} size="sm" type="button" variant="ghost">删除</Button></div>
    </article>
  )
}

function useCreateExperience(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: TalentExperienceInput) => createExperience(talentId, input),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.experiences(talentId) }); onSaved(); toast.success("履历已添加") },
    onError: showError,
  })
}

function useUpdateExperience(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ experienceId, input }: { experienceId: string; input: TalentExperienceInput }) => updateExperience(talentId, experienceId, input),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.experiences(talentId) }); onSaved(); toast.success("履历已更新") },
    onError: showError,
  })
}

function useDeleteExperience(talentId: string, onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (experienceId: string) => deleteExperience(talentId, experienceId),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.experiences(talentId) }); onDeleted(); toast.success("履历已删除") },
    onError: showError,
  })
}

type DeleteMutation = ReturnType<typeof useDeleteExperience>

function ExperienceDeleteDialog({ experience, mutation, onClose }: { experience: TalentExperience | null; mutation: DeleteMutation; onClose: () => void }) {
  return <ConfirmDialog busy={mutation.isPending} confirmLabel="确认删除这条履历" description="仅删除这条履历记录，人才档案不受影响。" onClose={onClose} onConfirm={() => { if (experience) mutation.mutate(experience.id) }} open={experience !== null} title="删除履历" />
}

function experienceToForm(value: TalentExperience): ExperienceFormValues {
  return { company: value.company, title: value.title, description: value.description ?? "", start_on: value.start_on, end_on: value.end_on ?? "" }
}

function experienceFormToInput(value: ExperienceFormValues): TalentExperienceInput {
  return { company: value.company.trim(), title: value.title.trim(), description: emptyToNull(value.description), start_on: value.start_on, end_on: emptyToNull(value.end_on) }
}

function validateExperience(value: ExperienceFormValues): string | null {
  if (!value.company.trim()) return "请填写公司"
  if (!value.title.trim()) return "请填写职务"
  if (!value.start_on) return "请选择开始月份"
  if (value.end_on && value.end_on < value.start_on) return "结束月份不能早于开始月份"
  return null
}

function showError(error: unknown) { toast.error(error instanceof Error ? error.message : "请求失败") }
