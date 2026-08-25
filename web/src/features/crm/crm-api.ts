import { apiRequest } from "@/lib/api"

import type {
  Contact,
  ContactInput,
  Customer,
  CustomerFilters,
  CustomerInput,
  FollowUp,
  FollowUpInput,
} from "./types"

export const crmKeys = {
  customers: ["crm", "customers"] as const,
  customer: (customerId: string) => ["crm", "customer", customerId] as const,
  contacts: (customerId: string) => ["crm", "contacts", customerId] as const,
  followUps: (customerId: string) => ["crm", "follow-ups", customerId] as const,
}

export function listCustomers(filters: CustomerFilters): Promise<Customer[]> {
  const params = new URLSearchParams()
  if (filters.query.trim()) params.set("query", filters.query.trim())
  if (filters.status) params.set("status", filters.status)
  if (filters.due) params.set("due", filters.due)
  const suffix = params.size ? `?${params.toString()}` : ""
  return apiRequest<Customer[]>(`/crm/customers${suffix}`)
}

export function getCustomer(customerId: string): Promise<Customer> {
  return apiRequest<Customer>(`/crm/customers/${customerId}`)
}

export function createCustomer(input: CustomerInput): Promise<Customer> {
  return apiRequest<Customer>("/crm/customers", jsonRequest("POST", input))
}

export function updateCustomer(customerId: string, input: CustomerInput): Promise<Customer> {
  return apiRequest<Customer>(`/crm/customers/${customerId}`, jsonRequest("PUT", input))
}

export function deleteCustomer(customerId: string): Promise<void> {
  return apiRequest<void>(`/crm/customers/${customerId}`, { method: "DELETE" })
}

export function listContacts(customerId: string): Promise<Contact[]> {
  return apiRequest<Contact[]>(`/crm/customers/${customerId}/contacts`)
}

export function createContact(customerId: string, input: ContactInput): Promise<Contact> {
  return apiRequest<Contact>(`/crm/customers/${customerId}/contacts`, jsonRequest("POST", input))
}

export function updateContact(customerId: string, contactId: string, input: ContactInput): Promise<Contact> {
  return apiRequest<Contact>(
    `/crm/customers/${customerId}/contacts/${contactId}`,
    jsonRequest("PUT", input),
  )
}

export function deleteContact(customerId: string, contactId: string): Promise<void> {
  return apiRequest<void>(`/crm/customers/${customerId}/contacts/${contactId}`, { method: "DELETE" })
}

export function listFollowUps(customerId: string): Promise<FollowUp[]> {
  return apiRequest<FollowUp[]>(`/crm/customers/${customerId}/follow-ups`)
}

export function createFollowUp(customerId: string, input: FollowUpInput): Promise<FollowUp> {
  return apiRequest<FollowUp>(`/crm/customers/${customerId}/follow-ups`, jsonRequest("POST", input))
}

export function updateFollowUp(customerId: string, followUpId: string, input: FollowUpInput): Promise<FollowUp> {
  return apiRequest<FollowUp>(
    `/crm/customers/${customerId}/follow-ups/${followUpId}`,
    jsonRequest("PUT", historicalFollowUpInput(input)),
  )
}

export function deleteFollowUp(customerId: string, followUpId: string): Promise<void> {
  return apiRequest<void>(`/crm/customers/${customerId}/follow-ups/${followUpId}`, { method: "DELETE" })
}

function jsonRequest(method: "POST" | "PUT", body: object): RequestInit {
  return { method, body: JSON.stringify(body) }
}

function historicalFollowUpInput(input: FollowUpInput): Omit<FollowUpInput, "set_as_current"> {
  return {
    contact_id: input.contact_id,
    kind: input.kind,
    occurred_on: input.occurred_on,
    summary: input.summary,
    next_action: input.next_action,
    next_follow_up_on: input.next_follow_up_on,
  }
}

export function emptyToNull(value: string): string | null {
  const normalized = value.trim()
  return normalized || null
}
