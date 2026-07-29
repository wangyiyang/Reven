import { Search, X } from "lucide-react"
import type { FormEvent, ReactNode } from "react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export interface ArticleFilterValues {
  status: string
  channel: string
  query: string
}

const statuses = ["全部状态", "待发布", "等待中", "处理中", "阻塞", "失败", "已完成", "已交付"]
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
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onChange({ ...values, query })
  }
  return (
    <form className="grid gap-4 border-y border-[var(--ink)] py-5 md:grid-cols-[12rem_12rem_1fr_auto]" onSubmit={submit}>
      <Field label="状态">
        <Select value={values.status || "全部状态"} onValueChange={(status) => onChange({ ...values, status: status === "全部状态" ? "" : status })}>
          <SelectTrigger aria-label="状态"><SelectValue /></SelectTrigger>
          <SelectContent>{statuses.map((status) => <SelectItem key={status} value={status}>{status}</SelectItem>)}</SelectContent>
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
          <Search aria-hidden className="absolute top-3 left-0 text-[var(--muted)]" size={15} />
          <Input aria-label="搜索标题" className="pl-6" maxLength={200} onChange={(event) => setQuery(event.target.value)} value={query} />
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
  return <div><Label className="mb-1 block text-[10px] tracking-[0.12em] text-[var(--muted)] uppercase">{label}</Label>{children}</div>
}
