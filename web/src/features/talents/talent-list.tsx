import { AlertTriangle, CalendarClock } from "lucide-react"
import { Link, useNavigate } from "react-router-dom"

import { ResponsiveList } from "@/components/responsive-list"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import { TALENT_STATUSES, type DueFilter, type Talent, type TalentFilters, type TalentStatus } from "./types"

type TalentListProps = {
  talents: Talent[] | undefined
  loading: boolean
  failed: boolean
  filters: TalentFilters
  onFiltersChange: (filters: TalentFilters) => void
  onRetry: () => void
  onDelete: (talent: Talent) => void
}

const selectClassName = "h-10 rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
const emptyTalentsMessage = "暂无匹配人才。"

export function TalentList(props: TalentListProps) {
  const navigate = useNavigate()
  const tagOptions = [...new Set((props.talents ?? []).flatMap((talent) => talent.tags))].sort()
  return (
    <div className="space-y-4">
      <TalentFiltersBar filters={props.filters} onChange={props.onFiltersChange} tagOptions={tagOptions} />
      <TalentListState {...props} />
      {!props.loading && !props.failed ? (
        <ResponsiveList
          actions={[
            { label: "编辑", ariaLabel: (talent) => `编辑 ${talent.name}`, onClick: (talent) => void navigate(`/talents/${talent.id}?edit=1`) },
            { label: "删除", ariaLabel: (talent) => `删除 ${talent.name}`, onClick: props.onDelete },
          ]}
          card={(talent) => ({
            title: <Link to={`/talents/${talent.id}`}>{talent.name}</Link>,
            status: <Badge>{talent.status}</Badge>,
            body: <p className="mt-2 text-sm text-[var(--muted)]">{talent.organization ?? "未记录机构"}</p>,
            meta: (
              <>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <TagBadges tags={talent.tags} />
                  <DueFilterBadge due={props.filters.due} />
                </div>
                <p className="mt-2 text-sm"><RateText talent={talent} /> · <RatingText rating={talent.rating} /></p>
              </>
            ),
          })}
          cardLabel={(talent) => `${talent.name} 人才摘要`}
          columns={[
            {
              header: "人才",
              cell: (talent) => (
                <>
                  <Link className="font-medium" to={`/talents/${talent.id}`}>{talent.name}</Link>
                  <p className="text-xs text-[var(--muted)]">{talent.organization ?? "—"}</p>
                </>
              ),
            },
            {
              header: "状态",
              cell: (talent) => (
                <div className="flex items-center gap-2">
                  <Badge>{talent.status}</Badge>
                  <DueFilterBadge due={props.filters.due} />
                </div>
              ),
            },
            { header: "标签", className: "max-w-64", cell: (talent) => <TagBadges tags={talent.tags} /> },
            { header: "费率", cell: (talent) => <RateText talent={talent} /> },
            { header: "评分", cell: (talent) => <RatingText rating={talent.rating} /> },
          ]}
          emptyText={emptyTalentsMessage}
          items={props.talents}
          keyOf={(talent) => talent.id}
        />
      ) : null}
    </div>
  )
}

function TalentFiltersBar({ filters, onChange, tagOptions }: { filters: TalentFilters; onChange: TalentListProps["onFiltersChange"]; tagOptions: string[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto] md:items-end">
      <div className="space-y-2">
        <Label htmlFor="talents-search">搜索</Label>
        <Input
          id="talents-search"
          onChange={(event) => onChange({ ...filters, q: event.target.value })}
          placeholder="姓名或机构"
          value={filters.q}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="talents-status-filter">状态</Label>
        <select
          className={selectClassName}
          id="talents-status-filter"
          onChange={(event) => onChange({ ...filters, status: event.target.value as TalentStatus | "" })}
          value={filters.status}
        >
          <option value="">全部状态</option>
          {TALENT_STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="talents-due-filter">跟进到期</Label>
        <select
          className={selectClassName}
          id="talents-due-filter"
          onChange={(event) => onChange({ ...filters, due: event.target.value as DueFilter | "" })}
          value={filters.due}
        >
          <option value="">全部</option>
          <option value="overdue">已逾期</option>
          <option value="today">今天</option>
          <option value="upcoming">未来</option>
          <option value="none">无计划</option>
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="talents-tag-filter">标签筛选</Label>
        <Input
          id="talents-tag-filter"
          list="talents-tag-options"
          onChange={(event) => onChange({ ...filters, tag: event.target.value })}
          placeholder="精确匹配单个标签"
          value={filters.tag}
        />
        <datalist id="talents-tag-options">
          {tagOptions.map((tag) => <option key={tag} value={tag} />)}
        </datalist>
      </div>
    </div>
  )
}

function TalentListState({ loading, failed, onRetry }: TalentListProps) {
  if (loading) return <p className="py-8 text-center text-sm text-[var(--muted)]">正在加载人才…</p>
  if (failed) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-sm text-[var(--muted)]">
        <p>人才列表加载失败。</p>
        <Button onClick={onRetry} size="sm" type="button" variant="outline">重新加载</Button>
      </div>
    )
  }
  return null
}

function DueFilterBadge({ due }: { due: DueFilter | "" }) {
  if (due === "overdue") {
    return <span className="flex items-center gap-1 text-xs text-[var(--danger)]"><AlertTriangle aria-hidden size={13} />已逾期</span>
  }
  if (due === "today") {
    return <span className="flex items-center gap-1 text-xs font-semibold"><CalendarClock aria-hidden size={13} />今天到期</span>
  }
  return null
}

function TagBadges({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null
  return <div className="flex flex-wrap gap-1">{tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}</div>
}

function RateText({ talent }: { talent: Talent }) {
  if (talent.rate_amount === null || talent.rate_unit === null) return <span className="text-[var(--muted)]">—</span>
  return <span>¥{talent.rate_amount} {talent.rate_unit}</span>
}

function RatingText({ rating }: { rating: number | null }) {
  if (rating === null) return <span className="text-[var(--muted)]">—</span>
  return <span>★ {rating}/5</span>
}
