import { useQuery } from "@tanstack/react-query"
import { Search, X } from "lucide-react"
import type { FormEvent, ReactNode } from "react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiRequest } from "@/lib/api"
import { parseStatusFacets } from "./response-parsers"

export interface ArticleFilterValues {
  status: string
  channel: string
  query: string
}

const ALL_STATUSES = "全部状态"
const channels = ["全部渠道", "个人博客", "微信公众号"]

export function ArticleFilters({
  values,
  onChange,
}: {
  values: ArticleFilterValues
  onChange: (values: ArticleFilterValues) => void
}) {
  const [query, setQuery] = useState(values.query)
  useEffect(() => setQuery(values.query), [values.query])
  // 状态选项来自后端真实值域聚合，避免与稿件实际状态脱节
  const facets = useQuery({
    queryKey: ["article-status-facets"],
    queryFn: async () => parseStatusFacets(await apiRequest<unknown>("/articles/status-facets")),
    staleTime: 60_000,
  })
  const statusOptions = [ALL_STATUSES, ...(facets.data ?? [])]
  // URL 中的 status 可能不在当前值域内（如 Notion 侧刚改过状态名），补入选项避免下拉显示空白
  if (values.status && !statusOptions.includes(values.status)) statusOptions.push(values.status)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onChange({ ...values, query })
  }
  return (
    <form className="grid gap-4 border-y border-[var(--line)] py-5 md:grid-cols-[12rem_12rem_1fr_auto]" onSubmit={submit}>
      <Field label="状态">
        <Select value={values.status || ALL_STATUSES} onValueChange={(status) => onChange({ ...values, status: status === ALL_STATUSES ? "" : status })}>
          <SelectTrigger aria-label="状态"><SelectValue /></SelectTrigger>
          <SelectContent>{statusOptions.map((status) => <SelectItem key={status} value={status}>{status}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Field label="渠道">
        <Select value={values.channel || "全部渠道"} onValueChange={(channel) => onChange({ ...values, channel: channel === "全部渠道" ? "" : channel })}>
          <SelectTrigger aria-label="渠道"><SelectValue /></SelectTrigger>
          <SelectContent>{channels.map((channel) => <SelectItem key={channel} value={channel}>{channel}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Field label="搜索标题">
        <div className="relative">
          <Search aria-hidden className="absolute top-1/2 left-3 -translate-y-1/2 text-[var(--muted)]" size={15} />
          <Input aria-label="搜索标题" className="pl-9" maxLength={200} onChange={(event) => setQuery(event.target.value)} value={query} />
        </div>
      </Field>
      <div className="flex items-end gap-2">
        <Button size="sm" type="submit">筛选</Button>
        <Button aria-label="清除筛选" onClick={() => { setQuery(""); onChange({ status: "", channel: "", query: "" }) }} size="sm" type="button" variant="ghost"><X aria-hidden size={14} /></Button>
      </div>
    </form>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><Label className="mb-1 block text-xs text-[var(--muted)]">{label}</Label>{children}</div>
}
