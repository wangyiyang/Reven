import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { useResourceList } from "@/lib/use-resource-list"

import { crmKeys } from "./crm-api"
import { CustomerForm } from "./customer-form"
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
  const list = useResourceList<Customer, CustomerFormValues, CustomerFilters>({
    key: crmKeys.customers,
    path: "/crm/customers",
    initialForm: EMPTY_CUSTOMER_FORM,
    initialFilters: EMPTY_FILTERS,
    toPayload: customerFormToInput,
    toForm: customerToForm,
    validate: validateCustomerForm,
    detailKeyOf: (customer) => crmKeys.customer(customer.id),
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
      <PageHeading />
      <CustomerEditorCard
        busy={list.isSaving}
        editing={list.editingId !== null}
        form={list.form}
        onCancel={list.cancelEdit}
        onChange={list.setForm}
        onSubmit={list.submit}
      />
      <CustomerListCard
        customers={list.itemsQuery.data}
        failed={list.itemsQuery.isError}
        filters={list.filters}
        loading={list.itemsQuery.isLoading}
        onDelete={list.requestRemove}
        onEdit={list.startEdit}
        onFiltersChange={list.setFilters}
        onRetry={() => void list.itemsQuery.refetch()}
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

function PageHeading() {
  return (
    <div className="space-y-2">
      <p className="section-kicker">RELATIONSHIPS</p>
      <h1 className="text-2xl font-semibold text-[var(--ink)]">CRM</h1>
      <p className="text-sm text-[var(--muted)]">维护客户关系、记录跟进，并把每一次沟通推进到明确的下一步。</p>
    </div>
  )
}

type EditorCardProps = {
  form: CustomerFormValues
  editing: boolean
  busy: boolean
  onChange: (form: CustomerFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

function CustomerEditorCard(props: EditorCardProps) {
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">{props.editing ? "编辑客户" : "添加客户"}</h2></CardHeader>
      <CardContent><CustomerForm {...props} values={props.form} /></CardContent>
    </Card>
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
