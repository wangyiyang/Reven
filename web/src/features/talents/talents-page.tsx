import { useMemo } from "react"

import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { useResourceList } from "@/lib/use-resource-list"

import { talentsKeys } from "./talents-api"
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

const EMPTY_FILTERS: TalentFilters = { q: "", status: "", due: "", tag: "" }

export function TalentsPage() {
  const list = useResourceList<Talent, TalentFormValues, TalentFilters>({
    key: "talents",
    path: "/talents",
    updateMethod: "PATCH",
    initialForm: EMPTY_TALENT_FORM,
    initialFilters: EMPTY_FILTERS,
    toPayload: talentFormToInput,
    toForm: talentToForm,
    validate: validateTalentForm,
    detailKeyOf: (talent) => talentsKeys.talent(talent.id),
    messages: {
      created: "人才已添加",
      updated: "人才已更新",
      deleted: "人才已删除",
      saveFailed: "请求失败",
      updateFailed: "请求失败",
      deleteFailed: "请求失败",
    },
  })
  const tagSuggestions = useMemo(
    () => [...new Set((list.itemsQuery.data ?? []).flatMap((talent) => talent.tags))].sort(),
    [list.itemsQuery.data],
  )

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeading />
      <TalentEditorCard
        busy={list.isSaving}
        editing={list.editingId !== null}
        form={list.form}
        onCancel={list.cancelEdit}
        onChange={list.setForm}
        onSubmit={list.submit}
        tagSuggestions={tagSuggestions}
      />
      <TalentListCard
        failed={list.itemsQuery.isError}
        filters={list.filters}
        loading={list.itemsQuery.isLoading}
        onDelete={list.requestRemove}
        onEdit={list.startEdit}
        onFiltersChange={list.setFilters}
        onRetry={() => void list.itemsQuery.refetch()}
        talents={list.itemsQuery.data}
      />
      <ConfirmDialog
        busy={list.isRemoving}
        confirmLabel={`确认删除「${list.deleting?.name ?? ""}」`}
        description="该人才的跟进记录也会被删除，且无法恢复。"
        onClose={list.cancelRemove}
        onConfirm={list.confirmRemove}
        open={list.deleting !== null}
        title="删除人才"
      />
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
