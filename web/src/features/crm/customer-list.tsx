import { AlertTriangle, CalendarClock } from "lucide-react"
import { Link } from "react-router-dom"

import { ResponsiveList } from "@/components/responsive-list"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import { CUSTOMER_STATUSES, type Customer, type CustomerFilters, type CustomerStatus, type DueFilter } from "./types"
import { todayInShanghai } from "./date-utils"

type CustomerListProps = {
  customers: Customer[] | undefined
  loading: boolean
  failed: boolean
  filters: CustomerFilters
  onFiltersChange: (filters: CustomerFilters) => void
  onRetry: () => void
  onEdit: (customer: Customer) => void
  onDelete: (customer: Customer) => void
}

const selectClassName = "h-10 rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

export function CustomerList(props: CustomerListProps) {
  return (
    <div className="space-y-4">
      <CustomerFiltersBar filters={props.filters} onChange={props.onFiltersChange} />
      <CustomerListState {...props} />
      {!props.loading && !props.failed && (props.customers?.length ?? 0) > 0 ? (
        <ResponsiveList
          actions={[
            { label: "编辑", ariaLabel: (customer) => `编辑 ${customer.name}`, onClick: props.onEdit },
            { label: "删除", ariaLabel: (customer) => `删除 ${customer.name}`, onClick: props.onDelete },
          ]}
          card={(customer) => ({
            title: <Link to={`/crm/customers/${customer.id}`}>{customer.name}</Link>,
            status: <Badge>{customer.status}</Badge>,
            body: (
              <>
                <p className="mt-2 text-sm text-[var(--muted)]">{customer.next_action ?? "尚未安排下一步"}</p>
                <FollowUpState dueOn={customer.next_follow_up_on} />
              </>
            ),
          })}
          cardLabel={(customer) => `${customer.name} 客户摘要`}
          columns={[
            {
              header: "客户",
              cell: (customer) => <Link className="font-medium" to={`/crm/customers/${customer.id}`}>{customer.name}</Link>,
            },
            { header: "状态", cell: (customer) => <Badge>{customer.status}</Badge> },
            { header: "来源", cell: (customer) => customer.source ?? "—" },
            {
              header: "下一步",
              className: "max-w-72",
              cell: (customer) => <span className="line-clamp-2">{customer.next_action ?? "—"}</span>,
            },
            { header: "跟进日期", cell: (customer) => <FollowUpState dueOn={customer.next_follow_up_on} /> },
          ]}
          emptyText="暂无匹配客户。"
          items={props.customers}
          keyOf={(customer) => customer.id}
        />
      ) : null}
    </div>
  )
}

function CustomerFiltersBar({ filters, onChange }: Pick<CustomerListProps, "filters"> & { onChange: CustomerListProps["onFiltersChange"] }) {
  return (
    <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
      <div className="space-y-2">
        <Label htmlFor="crm-customer-search">搜索</Label>
        <Input
          id="crm-customer-search"
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="客户名称、联系人或联系方式"
          value={filters.query}
        />
      </div>
      <StatusFilter filters={filters} onChange={onChange} />
      <DueFilterSelect filters={filters} onChange={onChange} />
    </div>
  )
}

function StatusFilter({ filters, onChange }: Pick<CustomerListProps, "filters"> & { onChange: CustomerListProps["onFiltersChange"] }) {
  return (
    <div className="space-y-2">
      <Label htmlFor="crm-status-filter">关系状态</Label>
      <select
        className={selectClassName}
        id="crm-status-filter"
        onChange={(event) => onChange({ ...filters, status: event.target.value as CustomerStatus | "" })}
        value={filters.status}
      >
        <option value="">全部状态</option>
        {CUSTOMER_STATUSES.map((status) => <option key={status}>{status}</option>)}
      </select>
    </div>
  )
}

function DueFilterSelect({ filters, onChange }: Pick<CustomerListProps, "filters"> & { onChange: CustomerListProps["onFiltersChange"] }) {
  return (
    <div className="space-y-2">
      <Label htmlFor="crm-due-filter">跟进计划</Label>
      <select
        className={selectClassName}
        id="crm-due-filter"
        onChange={(event) => onChange({ ...filters, due: event.target.value as DueFilter | "" })}
        value={filters.due}
      >
        <option value="">全部计划</option>
        <option value="overdue">已逾期</option>
        <option value="today">今天</option>
        <option value="upcoming">未来</option>
        <option value="none">无计划</option>
      </select>
    </div>
  )
}

function CustomerListState({ customers, loading, failed, onRetry }: CustomerListProps) {
  if (loading) return <p className="py-8 text-center text-sm text-[var(--muted)]">正在加载客户…</p>
  if (failed) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-sm text-[var(--muted)]">
        <p>客户列表加载失败。</p>
        <Button onClick={onRetry} size="sm" type="button" variant="outline">重新加载</Button>
      </div>
    )
  }
  if (customers?.length === 0) return <p className="py-8 text-center text-sm text-[var(--muted)]">暂无匹配客户。</p>
  return null
}

function FollowUpState({ dueOn }: { dueOn: string | null }) {
  if (!dueOn) return <span className="text-xs text-[var(--muted)]">无计划</span>
  const today = todayInShanghai()
  if (dueOn < today) return <span className="flex items-center gap-1 text-xs text-[var(--danger)]"><AlertTriangle aria-hidden size={13} />逾期 · {dueOn}</span>
  if (dueOn === today) return <span className="flex items-center gap-1 text-xs font-semibold"><CalendarClock aria-hidden size={13} />今天</span>
  return <span className="text-xs text-[var(--muted)]">计划于 {dueOn}</span>
}
