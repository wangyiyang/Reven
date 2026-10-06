import { emptyToNull } from "./crm-api"
import type { Customer, CustomerInput, CustomerStatus } from "./types"

export type CustomerFormValues = {
  name: string
  status: CustomerStatus
  source: string
  notes: string
}

export const EMPTY_CUSTOMER_FORM: CustomerFormValues = {
  name: "",
  status: "潜在客户",
  source: "",
  notes: "",
}

export function customerToForm(customer: Customer): CustomerFormValues {
  return {
    name: customer.name,
    status: customer.status,
    source: customer.source ?? "",
    notes: customer.notes ?? "",
  }
}

export function customerFormToInput(values: CustomerFormValues): CustomerInput {
  return {
    name: values.name.trim(),
    status: values.status,
    source: emptyToNull(values.source),
    notes: emptyToNull(values.notes),
  }
}

export function validateCustomerForm(values: CustomerFormValues): string | null {
  if (!values.name.trim()) return "请填写客户名称"
  return null
}
