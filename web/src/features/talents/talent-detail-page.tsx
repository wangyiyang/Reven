import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { useMemo, useState } from "react"
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom"
import { toast } from "sonner"

import { apiRequest } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

import { InteractionsSection } from "./interactions-section"
import { EducationsSection } from "./educations-section"
import { ExperiencesSection } from "./experiences-section"
import { TalentForm } from "./talent-form"
import { talentFormToInput, talentToForm, validateTalentForm, type TalentFormValues } from "./talent-form-model"
import { getTalent, talentsKeys } from "./talents-api"
import type { Talent, TalentFilters, TalentInput } from "./types"

// 与列表页 initialFilters 同构：query key 结构一致，从列表页进入时命中其列表缓存
const LIST_FILTERS: TalentFilters = { q: "", status: "", due: "", tag: "" }

export function TalentDetailPage() {
  const { talentId } = useParams()
  if (!talentId) return <Navigate replace to="/talents" />
  return <TalentDetail talentId={talentId} />
}

function TalentDetail({ talentId }: { talentId: string }) {
  const talentQuery = useQuery({ queryKey: talentsKeys.talent(talentId), queryFn: () => getTalent(talentId) })
  if (talentQuery.isLoading) return <PageState message="正在加载人才…" />
  if (talentQuery.isError || !talentQuery.data) {
    return <PageState action={() => void talentQuery.refetch()} message="人才不存在或加载失败。" />
  }
  return (
    <main className="page-enter mx-auto w-full max-w-6xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <DetailHeading talent={talentQuery.data} />
      <TalentSummary talent={talentQuery.data} />
      <ExperiencesSection talentId={talentId} />
      <EducationsSection talentId={talentId} />
      <InteractionsSection talentId={talentId} />
    </main>
  )
}

function DetailHeading({ talent }: { talent: Talent }) {
  return (
    <div className="space-y-3">
      <Link className="inline-flex items-center gap-1 text-sm" to="/talents"><ArrowLeft aria-hidden size={15} />返回人才库</Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">{talent.name}</h1>
        <Badge>{talent.status}</Badge>
        {talent.rating !== null ? <span className="text-sm text-[var(--muted)]">★ {talent.rating}/5</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-[var(--muted)]">{talent.organization ?? "未记录机构"}</p>
        {talent.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}
      </div>
    </div>
  )
}

function SummaryItem({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 whitespace-pre-wrap text-sm">{value ?? "未记录"}</p>
    </div>
  )
}

function TalentSummary({ talent }: { talent: Talent }) {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [editing, setEditing] = useState(() => searchParams.get("edit") === "1")
  const [form, setForm] = useState<TalentFormValues>(() => talentToForm(talent))
  // 编辑态的标签建议：与列表页同 key 的列表查询，从列表页过来时命中缓存
  const tagsQuery = useQuery({
    queryKey: [...talentsKeys.talents, LIST_FILTERS],
    queryFn: () => apiRequest<Talent[]>("/talents"),
    enabled: editing,
  })
  const tagSuggestions = useMemo(
    () => [...new Set((tagsQuery.data ?? []).flatMap((item) => item.tags))].sort(),
    [tagsQuery.data],
  )
  const updateMutation = useMutation({
    mutationFn: (input: TalentInput) =>
      apiRequest<Talent>(`/talents/${talent.id}`, { method: "PATCH", body: JSON.stringify(input) }),
    onSuccess: async (updated) => {
      queryClient.setQueryData(talentsKeys.talent(updated.id), updated)
      await queryClient.invalidateQueries({ queryKey: talentsKeys.talents })
      setEditing(false)
      toast.success("人才已更新")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "请求失败"),
  })

  function startEdit() {
    setForm(talentToForm(talent))
    setEditing(true)
  }

  function submit() {
    const error = validateTalentForm(form)
    if (error) return toast.error(error)
    updateMutation.mutate(talentFormToInput(form))
  }

  const rate = talent.rate_amount !== null && talent.rate_unit !== null
    ? `¥${talent.rate_amount} ${talent.rate_unit}`
    : null
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-medium text-[var(--ink)]">人才档案</h2>
          {editing ? null : <Button aria-label="编辑人才档案" onClick={startEdit} size="sm" type="button" variant="outline">编辑</Button>}
        </div>
      </CardHeader>
      {editing ? (
        <CardContent>
          <TalentForm
            busy={updateMutation.isPending}
            editing
            onCancel={() => setEditing(false)}
            onChange={setForm}
            onSubmit={submit}
            tagSuggestions={tagSuggestions}
            values={form}
          />
        </CardContent>
      ) : (
        <CardContent className="grid gap-4 md:grid-cols-2">
          <SummaryItem label="电话" value={talent.phone} />
          <SummaryItem label="邮箱" value={talent.email} />
          <SummaryItem label="微信" value={talent.wechat} />
          <div>
            <p className="text-xs text-[var(--muted)]">喜好</p>
            {talent.preferences.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-2">
                {talent.preferences.map((preference) => <Badge key={preference}>{preference}</Badge>)}
              </div>
            ) : <p className="mt-1 text-sm">未记录</p>}
          </div>
          <SummaryItem label="能力" value={talent.capability} />
          <SummaryItem label="可用时间" value={talent.availability} />
          <SummaryItem label="合作条件" value={talent.engagement_terms} />
          <SummaryItem label="费率" value={rate} />
          {talent.notes ? <div className="md:col-span-2"><SummaryItem label="备注" value={talent.notes} /></div> : null}
        </CardContent>
      )}
    </Card>
  )
}

function PageState({ message, action }: { message: string; action?: () => void }) {
  return (
    <main className="mx-auto flex min-h-[50vh] max-w-xl flex-col items-center justify-center gap-4 px-5 text-center">
      <p className="text-sm text-[var(--muted)]">{message}</p>
      <div className="flex gap-2"><Link className="inline-flex h-9 items-center rounded-md border border-[var(--line)] px-3 text-xs font-semibold text-[var(--ink)] hover:no-underline" to="/talents">返回人才库</Link>{action ? <Button onClick={action} size="sm" type="button">重新加载</Button> : null}</div>
    </main>
  )
}
