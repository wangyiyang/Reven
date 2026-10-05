import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { useResourceList } from "@/lib/use-resource-list"

import { crmKeys } from "./crm-api"
import { CustomerFormDrawer } from "./customer-form-drawer"
import {
  EMPTY_CUSTOMER_FORM,
  customerFormToInput,
  customerToForm,
  validateCustomerForm,
  type CustomerFormValues,
} from "./customer-form-model"
import { CustomerList } from "./customer-list"
import type { Customer, CustomerFilters } from "./types"

const EMPTY_FILTERS: CustomerFilters = { query: "", status: "", due: "" }

export function CrmPage() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const list = useResourceList<Customer, CustomerFormValues, CustomerFilters>({
    key: crmKeys.customers,
    path: "/crm/customers",
    initialForm: EMPTY_CUSTOMER_FORM,
    initialFilters: EMPTY_FILTERS,
    toPayload: customerFormToInput,
    toForm: customerToForm,
    validate: validateCustomerForm,
    detailKeyOf: (customer) => crmKeys.customer(customer.id),
    onSaved: () => setDrawerOpen(false),
    messages: {
      created: "客户已添加",
      updated: "客户已更新",
      deleted: "客户已删除",
      saveFailed: "请求失败",
      updateFailed: "请求失败",
      deleteFailed: "请求失败",
    },
  })

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeading onCreate={() => setDrawerOpen(true)} />
      <CustomerListCard
        customers={list.itemsQuery.data}
        failed={list.itemsQuery.isError}
        filters={list.filters}
        loading={list.itemsQuery.isLoading}
        onDelete={list.requestRemove}
        onFiltersChange={list.setFilters}
        onRetry={() => void list.itemsQuery.refetch()}
      />
      <CustomerFormDrawer
        busy={list.isSaving}
        editing={list.editingId !== null}
        onChange={list.setForm}
        onClose={() => setDrawerOpen(false)}
        onSubmit={list.submit}
        open={drawerOpen}
        values={list.form}
      />
      <ConfirmDialog
        busy={list.isRemoving}
        confirmLabel={`确认删除「${list.deleting?.name ?? ""}」`}
        description="该客户的联系人和跟进记录也会被删除，且无法恢复。"
        onClose={list.cancelRemove}
        onConfirm={list.confirmRemove}
        open={list.deleting !== null}
        title="删除客户"
      />
    </main>
  )
}

function PageHeading({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-2">
        <p className="section-kicker">RELATIONSHIPS</p>
        <h1 className="text-2xl font-semibold text-[var(--ink)]">CRM</h1>
        <p className="text-sm text-[var(--muted)]">维护客户关系、记录跟进，并把每一次沟通推进到明确的下一步。</p>
      </div>
      <Button onClick={onCreate} type="button">新建客户</Button>
    </div>
  )
}

function CustomerListCard(props: Parameters<typeof CustomerList>[0]) {
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">客户列表</h2></CardHeader>
      <CardContent><CustomerList {...props} /></CardContent>
    </Card>
  )
}
