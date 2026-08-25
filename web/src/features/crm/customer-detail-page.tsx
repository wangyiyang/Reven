import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, CalendarClock } from "lucide-react"
import { Link, Navigate, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

import { ContactsSection } from "./contacts-section"
import { crmKeys, getCustomer } from "./crm-api"
import { FollowUpsSection } from "./follow-ups-section"
import type { Customer } from "./types"

export function CustomerDetailPage() {
  const { customerId } = useParams()
  if (!customerId) return <Navigate replace to="/crm" />
  return <CustomerDetail customerId={customerId} />
}

function CustomerDetail({ customerId }: { customerId: string }) {
  const customerQuery = useQuery({ queryKey: crmKeys.customer(customerId), queryFn: () => getCustomer(customerId) })
  if (customerQuery.isLoading) return <PageState message="正在加载客户…" />
  if (customerQuery.isError || !customerQuery.data) {
    return <PageState action={() => void customerQuery.refetch()} message="客户不存在或加载失败。" />
  }
  return (
    <main className="page-enter mx-auto w-full max-w-6xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <DetailHeading customer={customerQuery.data} />
      <CustomerSummary customer={customerQuery.data} />
      <div className="grid gap-6 xl:grid-cols-2"><ContactsSection customerId={customerId} /><FollowUpsSection customerId={customerId} /></div>
    </main>
  )
}

function DetailHeading({ customer }: { customer: Customer }) {
  return (
    <div className="space-y-3">
      <Link className="inline-flex items-center gap-1 text-sm" to="/crm"><ArrowLeft aria-hidden size={15} />返回客户列表</Link>
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold text-[var(--ink)]">{customer.name}</h1><Badge>{customer.status}</Badge></div>
      <p className="text-sm text-[var(--muted)]">{customer.source ? `来源：${customer.source}` : "尚未记录客户来源"}</p>
    </div>
  )
}

function CustomerSummary({ customer }: { customer: Customer }) {
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">当前推进</h2></CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div><p className="text-xs text-[var(--muted)]">下一步行动</p><p className="mt-1 whitespace-pre-wrap text-sm">{customer.next_action ?? "尚未安排"}</p></div>
        <div><p className="text-xs text-[var(--muted)]">下次跟进</p><p className="mt-1 flex items-center gap-2 text-sm"><CalendarClock aria-hidden size={15} />{customer.next_follow_up_on ?? "无计划"}</p></div>
        {customer.notes ? <div className="md:col-span-2"><p className="text-xs text-[var(--muted)]">备注</p><p className="mt-1 whitespace-pre-wrap text-sm">{customer.notes}</p></div> : null}
      </CardContent>
    </Card>
  )
}

function PageState({ message, action }: { message: string; action?: () => void }) {
  return (
    <main className="mx-auto flex min-h-[50vh] max-w-xl flex-col items-center justify-center gap-4 px-5 text-center">
      <p className="text-sm text-[var(--muted)]">{message}</p>
      <div className="flex gap-2"><Link className="inline-flex h-9 items-center rounded-md border border-[var(--line)] px-3 text-xs font-semibold text-[var(--ink)] hover:no-underline" to="/crm">返回 CRM</Link>{action ? <Button onClick={action} size="sm" type="button">重新加载</Button> : null}</div>
    </main>
  )
}
