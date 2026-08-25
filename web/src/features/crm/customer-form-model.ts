import { emptyToNull } from "./crm-api"
import type { Customer, CustomerInput, CustomerStatus } from "./types"

export type CustomerFormValues = {
  name: string
  status: CustomerStatus
  source: string
  notes: string
  next_action: string
  next_follow_up_on: string
}

export const EMPTY_CUSTOMER_FORM: CustomerFormValues = {
  name: "",
  status: "潜在客户",
  source: "",
  notes: "",
  next_action: "",
  next_follow_up_on: "",
}

export function customerToForm(customer: Customer): CustomerFormValues {
  return {
    name: customer.name,
    status: customer.status,
    source: customer.source ?? "",
    notes: customer.notes ?? "",
    next_action: customer.next_action ?? "",
    next_follow_up_on: customer.next_follow_up_on ?? "",
  }
}

export function customerFormToInput(values: CustomerFormValues): CustomerInput {
  return {
    name: values.name.trim(),
    status: values.status,
    source: emptyToNull(values.source),
    notes: emptyToNull(values.notes),
    next_action: emptyToNull(values.next_action),
    next_follow_up_on: emptyToNull(values.next_follow_up_on),
  }
}

export function validateCustomerForm(values: CustomerFormValues): string | null {
  if (!values.name.trim()) return "请填写客户名称"
  if (values.next_follow_up_on && !values.next_action.trim()) return "设置跟进日期时请填写下一步行动"
  return null
}
