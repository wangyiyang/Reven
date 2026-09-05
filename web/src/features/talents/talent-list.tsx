import { AlertTriangle, CalendarClock } from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

import { TALENT_STATUSES, type DueFilter, type Talent, type TalentFilters, type TalentStatus } from "./types"

type TalentListProps = {
  talents: Talent[] | undefined
  loading: boolean
  failed: boolean
  filters: TalentFilters
  onFiltersChange: (filters: TalentFilters) => void
  onRetry: () => void
  onEdit: (talent: Talent) => void
  onDelete: (talent: Talent) => void
}

const selectClassName = "h-10 rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
const emptyTalentsMessage = "暂无匹配人才。"

export function TalentList(props: TalentListProps) {
  const tagOptions = [...new Set((props.talents ?? []).flatMap((talent) => talent.tags))].sort()
  return (
    <div className="space-y-4">
      <TalentFiltersBar filters={props.filters} onChange={props.onFiltersChange} tagOptions={tagOptions} />
      <TalentListState {...props} />
      {!props.loading && !props.failed ? <MobileTalents {...props} /> : null}
      {!props.loading && !props.failed ? <DesktopTalents {...props} /> : null}
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
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="姓名或机构"
          value={filters.query}
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

function TalentActions({ talent, labeled, onEdit, onDelete }: { talent: Talent; labeled?: boolean } & Pick<TalentListProps, "onEdit" | "onDelete">) {
  return (
    <div className="flex justify-end gap-1 lg:justify-start">
      <Button aria-label={labeled ? `编辑 ${talent.name}` : undefined} onClick={() => onEdit(talent)} size="sm" type="button" variant="ghost">编辑</Button>
      <Button aria-label={labeled ? `删除 ${talent.name}` : undefined} onClick={() => onDelete(talent)} size="sm" type="button" variant="ghost">删除</Button>
    </div>
  )
}

function MobileTalents(props: TalentListProps) {
  const talents = props.talents ?? []
  return (
    <div className="grid gap-3 lg:hidden">
      {talents.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--muted)]">{emptyTalentsMessage}</p>
      ) : talents.map((talent) => (
        <article aria-label={`${talent.name} 人才摘要`} className="rounded-lg border border-[var(--line)] p-4" key={talent.id}>
          <div className="flex items-start justify-between gap-3">
            <Link className="font-semibold" to={`/talents/${talent.id}`}>{talent.name}</Link>
            <Badge>{talent.status}</Badge>
          </div>
          <p className="mt-2 text-sm text-[var(--muted)]">{talent.organization ?? "未记录机构"}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TagBadges tags={talent.tags} />
            <DueFilterBadge due={props.filters.due} />
          </div>
          <p className="mt-2 text-sm"><RateText talent={talent} /> · <RatingText rating={talent.rating} /></p>
          <div className="mt-3"><TalentActions labeled talent={talent} onEdit={props.onEdit} onDelete={props.onDelete} /></div>
        </article>
      ))}
    </div>
  )
}

function DesktopTalents(props: TalentListProps) {
  const talents = props.talents ?? []
  return (
    <div className="hidden lg:block">
      <Table>
        <TableHeader><TableRow><TableHead>人才</TableHead><TableHead>状态</TableHead><TableHead>标签</TableHead><TableHead>费率</TableHead><TableHead>评分</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>
          {talents.length === 0 ? (
            <TableRow>
              <TableCell className="py-8 text-center text-sm text-[var(--muted)]" colSpan={6}>{emptyTalentsMessage}</TableCell>
            </TableRow>
          ) : talents.map((talent) => (
            <TableRow key={talent.id}>
              <TableCell>
                <Link className="font-medium" to={`/talents/${talent.id}`}>{talent.name}</Link>
                <p className="text-xs text-[var(--muted)]">{talent.organization ?? "—"}</p>
              </TableCell>
              <TableCell><div className="flex items-center gap-2"><Badge>{talent.status}</Badge><DueFilterBadge due={props.filters.due} /></div></TableCell>
              <TableCell className="max-w-64"><TagBadges tags={talent.tags} /></TableCell>
              <TableCell><RateText talent={talent} /></TableCell>
              <TableCell><RatingText rating={talent.rating} /></TableCell>
              <TableCell><TalentActions talent={talent} onEdit={props.onEdit} onDelete={props.onDelete} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
