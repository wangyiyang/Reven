import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import { emptyToNull } from "../crm/crm-api"

import {
  createEducation,
  deleteEducation,
  formatMonth,
  listEducations,
  talentsKeys,
  updateEducation,
} from "./talents-api"
import type { TalentEducation, TalentEducationInput } from "./types"

type EducationFormValues = {
  school: string
  degree: string
  major: string
  start_on: string
  end_on: string
}

const EMPTY_EDUCATION: EducationFormValues = { school: "", degree: "", major: "", start_on: "", end_on: "" }

export function EducationsSection({ talentId }: { talentId: string }) {
  const [form, setForm] = useState<EducationFormValues>(EMPTY_EDUCATION)
  const [editing, setEditing] = useState<TalentEducation | null>(null)
  const [deleting, setDeleting] = useState<TalentEducation | null>(null)
  const educationsQuery = useQuery({ queryKey: talentsKeys.educations(talentId), queryFn: () => listEducations(talentId) })
  const reset = () => { setForm(EMPTY_EDUCATION); setEditing(null) }
  const createMutation = useCreateEducation(talentId, reset)
  const updateMutation = useUpdateEducation(talentId, reset)
  const deleteMutation = useDeleteEducation(talentId, () => setDeleting(null))

  function submit() {
    const error = validateEducation(form)
    if (error) return toast.error(error)
    const input = educationFormToInput(form)
    if (editing) updateMutation.mutate({ educationId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(education: TalentEducation) {
    setEditing(education)
    setForm(educationToForm(education))
  }

  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">毕业院校</h2></CardHeader>
      <CardContent className="space-y-5">
        <EducationForm busy={createMutation.isPending || updateMutation.isPending} editing={editing !== null} onCancel={reset} onChange={setForm} onSubmit={submit} values={form} />
        <EducationList educations={educationsQuery.data} failed={educationsQuery.isError} loading={educationsQuery.isLoading} onDelete={setDeleting} onEdit={startEdit} onRetry={() => void educationsQuery.refetch()} />
      </CardContent>
      <EducationDeleteDialog education={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
    </Card>
  )
}

type EducationFormProps = {
  values: EducationFormValues
  editing: boolean
  busy: boolean
  onChange: (values: EducationFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

function EducationForm(props: EducationFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); props.onSubmit() }
  const { values, onChange } = props
  return (
    <form className="space-y-4 rounded-lg border border-[var(--line)] p-4" onSubmit={submit}>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2"><Label htmlFor="talent-education-school">学校</Label><Input id="talent-education-school" onChange={(event) => onChange({ ...values, school: event.target.value })} required value={values.school} /></div>
        <div className="space-y-2"><Label htmlFor="talent-education-degree">学位</Label><Input id="talent-education-degree" onChange={(event) => onChange({ ...values, degree: event.target.value })} placeholder="本科、硕士…（可留空）" value={values.degree} /></div>
        <div className="space-y-2"><Label htmlFor="talent-education-major">专业</Label><Input id="talent-education-major" onChange={(event) => onChange({ ...values, major: event.target.value })} value={values.major} /></div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="talent-education-start">入学月份</Label><Input id="talent-education-start" onChange={(event) => onChange({ ...values, start_on: event.target.value })} required type="date" value={values.start_on} /></div>
        <div className="space-y-2"><Label htmlFor="talent-education-end">毕业月份</Label><Input id="talent-education-end" onChange={(event) => onChange({ ...values, end_on: event.target.value })} placeholder="留空表示至今" type="date" value={values.end_on} /></div>
      </div>
      <div className="flex gap-2"><Button disabled={props.busy} size="sm" type="submit">{props.editing ? "保存院校经历" : "添加院校经历"}</Button>{props.editing ? <Button onClick={props.onCancel} size="sm" type="button" variant="ghost">取消</Button> : null}</div>
    </form>
  )
}

type EducationListProps = {
  educations: TalentEducation[] | undefined
  loading: boolean
  failed: boolean
  onRetry: () => void
  onEdit: (value: TalentEducation) => void
  onDelete: (value: TalentEducation) => void
}

function EducationList(props: EducationListProps) {
  if (props.loading) return <p className="text-sm text-[var(--muted)]">正在加载毕业院校…</p>
  if (props.failed) return <div className="flex items-center gap-2 text-sm text-[var(--muted)]"><span>毕业院校加载失败。</span><Button onClick={props.onRetry} size="sm" type="button" variant="outline">重试</Button></div>
  if (props.educations?.length === 0) return <p className="text-sm text-[var(--muted)]">暂无院校经历，在上方录入一段教育经历完善画像。</p>
  return <div className="space-y-3">{props.educations?.map((item) => <EducationCard education={item} key={item.id} onDelete={props.onDelete} onEdit={props.onEdit} />)}</div>
}

function EducationCard({ education, onEdit, onDelete }: { education: TalentEducation; onEdit: (value: TalentEducation) => void; onDelete: (value: TalentEducation) => void }) {
  const detail = [education.degree, education.major].filter(Boolean).join(" · ")
  return (
    <article aria-label={`${education.school} 院校经历`} className="border-l-2 border-[var(--line)] py-2 pl-4">
      <div className="flex flex-wrap items-baseline gap-2"><span className="font-semibold">{education.school}</span>{detail ? <span className="text-sm">{detail}</span> : null}<span className="text-xs text-[var(--muted)]">{formatMonth(education.start_on)} — {formatMonth(education.end_on)}</span></div>
      <div className="mt-2 flex gap-1"><Button onClick={() => onEdit(education)} size="sm" type="button" variant="ghost">编辑</Button><Button onClick={() => onDelete(education)} size="sm" type="button" variant="ghost">删除</Button></div>
    </article>
  )
}

function useCreateEducation(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: TalentEducationInput) => createEducation(talentId, input),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.educations(talentId) }); onSaved(); toast.success("院校经历已添加") },
    onError: showError,
  })
}

function useUpdateEducation(talentId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ educationId, input }: { educationId: string; input: TalentEducationInput }) => updateEducation(talentId, educationId, input),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.educations(talentId) }); onSaved(); toast.success("院校经历已更新") },
    onError: showError,
  })
}

function useDeleteEducation(talentId: string, onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (educationId: string) => deleteEducation(talentId, educationId),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: talentsKeys.educations(talentId) }); onDeleted(); toast.success("院校经历已删除") },
    onError: showError,
  })
}

type DeleteMutation = ReturnType<typeof useDeleteEducation>

function EducationDeleteDialog({ education, mutation, onClose }: { education: TalentEducation | null; mutation: DeleteMutation; onClose: () => void }) {
  return <ConfirmDialog busy={mutation.isPending} confirmLabel="确认删除这条院校经历" description="仅删除这条院校经历，人才档案不受影响。" onClose={onClose} onConfirm={() => { if (education) mutation.mutate(education.id) }} open={education !== null} title="删除院校经历" />
}

function educationToForm(value: TalentEducation): EducationFormValues {
  return { school: value.school, degree: value.degree ?? "", major: value.major ?? "", start_on: value.start_on, end_on: value.end_on ?? "" }
}

function educationFormToInput(value: EducationFormValues): TalentEducationInput {
  return { school: value.school.trim(), degree: emptyToNull(value.degree), major: emptyToNull(value.major), start_on: value.start_on, end_on: emptyToNull(value.end_on) }
}

function validateEducation(value: EducationFormValues): string | null {
  if (!value.school.trim()) return "请填写学校"
  if (!value.start_on) return "请选择入学月份"
  if (value.end_on && value.end_on < value.start_on) return "毕业月份不能早于入学月份"
  return null
}

function showError(error: unknown) { toast.error(error instanceof Error ? error.message : "请求失败") }
