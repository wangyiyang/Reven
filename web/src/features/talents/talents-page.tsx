import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"

import { listTalents, talentsKeys } from "./talents-api"
import { TalentForm } from "./talent-form"
import {
  EMPTY_TALENT_FORM,
  talentFormToInput,
  talentToForm,
  validateTalentForm,
  type TalentFormValues,
} from "./talent-form-model"
import { TalentList } from "./talent-list"
import type { Talent, TalentFilters } from "./types"
import { useCreateTalent, useDeleteTalent, useUpdateTalent } from "./use-talent-mutations"

const EMPTY_FILTERS: TalentFilters = { query: "", status: "", due: "", tag: "" }

export function TalentsPage() {
  const [form, setForm] = useState<TalentFormValues>(EMPTY_TALENT_FORM)
  const [editing, setEditing] = useState<Talent | null>(null)
  const [deleting, setDeleting] = useState<Talent | null>(null)
  const [filters, setFilters] = useState<TalentFilters>(EMPTY_FILTERS)
  const talentsQuery = useQuery({
    queryKey: [...talentsKeys.talents, filters],
    queryFn: () => listTalents(filters),
  })
  const resetForm = () => { setForm(EMPTY_TALENT_FORM); setEditing(null) }
  const createMutation = useCreateTalent(resetForm)
  const updateMutation = useUpdateTalent(resetForm)
  const deleteMutation = useDeleteTalent(() => setDeleting(null))
  const tagSuggestions = useMemo(
    () => [...new Set((talentsQuery.data ?? []).flatMap((talent) => talent.tags))].sort(),
    [talentsQuery.data],
  )

  function submitTalent() {
    const error = validateTalentForm(form)
    if (error) return toast.error(error)
    const input = talentFormToInput(form)
    if (editing) updateMutation.mutate({ talentId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(talent: Talent) {
    setEditing(talent)
    setForm(talentToForm(talent))
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeading />
      <TalentEditorCard
        busy={createMutation.isPending || updateMutation.isPending}
        editing={editing !== null}
        form={form}
        onCancel={resetForm}
        onChange={setForm}
        onSubmit={submitTalent}
        tagSuggestions={tagSuggestions}
      />
      <TalentListCard
        failed={talentsQuery.isError}
        filters={filters}
        loading={talentsQuery.isLoading}
        onDelete={setDeleting}
        onEdit={startEdit}
        onFiltersChange={setFilters}
        onRetry={() => void talentsQuery.refetch()}
        talents={talentsQuery.data}
      />
      <TalentDeleteDialog mutation={deleteMutation} onClose={() => setDeleting(null)} talent={deleting} />
    </main>
  )
}

function PageHeading() {
  return (
    <div className="space-y-2">
      <p className="section-kicker">RELATIONSHIPS</p>
      <h1 className="text-2xl font-semibold text-[var(--ink)]">人才库</h1>
      <p className="text-sm text-[var(--muted)]">管理潜在合作者档案、费率与评分，并把每一次接洽推进到明确的下一步。</p>
    </div>
  )
}

type EditorCardProps = {
  form: TalentFormValues
  tagSuggestions: string[]
  editing: boolean
  busy: boolean
  onChange: (form: TalentFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

function TalentEditorCard(props: EditorCardProps) {
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">{props.editing ? "编辑人才" : "添加人才"}</h2></CardHeader>
      <CardContent><TalentForm {...props} values={props.form} /></CardContent>
    </Card>
  )
}

function TalentListCard(props: Parameters<typeof TalentList>[0]) {
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">人才列表</h2></CardHeader>
      <CardContent><TalentList {...props} /></CardContent>
    </Card>
  )
}

type DeleteMutation = ReturnType<typeof useDeleteTalent>

function TalentDeleteDialog({ talent, mutation, onClose }: { talent: Talent | null; mutation: DeleteMutation; onClose: () => void }) {
  return (
    <ConfirmDialog
      busy={mutation.isPending}
      confirmLabel={`确认删除「${talent?.name ?? ""}」`}
      description="该人才的跟进记录也会被删除，且无法恢复。"
      onClose={onClose}
      onConfirm={() => { if (talent) mutation.mutate(talent.id) }}
      open={talent !== null}
      title="删除人才"
    />
  )
}
