import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"

import { crmKeys, listCustomers } from "./crm-api"
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
import { useCreateCustomer, useDeleteCustomer, useUpdateCustomer } from "./use-customer-mutations"

const EMPTY_FILTERS: CustomerFilters = { query: "", status: "", due: "" }

export function CrmPage() {
  const [form, setForm] = useState<CustomerFormValues>(EMPTY_CUSTOMER_FORM)
  const [editing, setEditing] = useState<Customer | null>(null)
  const [deleting, setDeleting] = useState<Customer | null>(null)
  const [filters, setFilters] = useState<CustomerFilters>(EMPTY_FILTERS)
  const customersQuery = useQuery({
    queryKey: [...crmKeys.customers, filters],
    queryFn: () => listCustomers(filters),
  })
  const resetForm = () => { setForm(EMPTY_CUSTOMER_FORM); setEditing(null) }
  const createMutation = useCreateCustomer(resetForm)
  const updateMutation = useUpdateCustomer(resetForm)
  const deleteMutation = useDeleteCustomer(() => setDeleting(null))

  function submitCustomer() {
    const error = validateCustomerForm(form)
    if (error) return toast.error(error)
    const input = customerFormToInput(form)
    if (editing) updateMutation.mutate({ customerId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(customer: Customer) {
    setEditing(customer)
    setForm(customerToForm(customer))
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeading />
      <CustomerEditorCard
        busy={createMutation.isPending || updateMutation.isPending}
        editing={editing !== null}
        form={form}
        onCancel={resetForm}
        onChange={setForm}
        onSubmit={submitCustomer}
      />
      <CustomerListCard
        customers={customersQuery.data}
        failed={customersQuery.isError}
        filters={filters}
        loading={customersQuery.isLoading}
        onDelete={setDeleting}
        onEdit={startEdit}
        onFiltersChange={setFilters}
        onRetry={() => void customersQuery.refetch()}
      />
      <CustomerDeleteDialog customer={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
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

type DeleteMutation = ReturnType<typeof useDeleteCustomer>

function CustomerDeleteDialog({ customer, mutation, onClose }: { customer: Customer | null; mutation: DeleteMutation; onClose: () => void }) {
  return (
    <ConfirmDialog
      busy={mutation.isPending}
      confirmLabel={`确认删除「${customer?.name ?? ""}」`}
      description="该客户的联系人和跟进记录也会被删除，且无法恢复。"
      onClose={onClose}
      onConfirm={() => { if (customer) mutation.mutate(customer.id) }}
      open={customer !== null}
      title="删除客户"
    />
  )
}
