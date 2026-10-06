import { apiRequest } from "@/lib/api"

import type {
  Contact,
  ContactInput,
  Customer,
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

export function getCustomer(customerId: string): Promise<Customer> {
  return apiRequest<Customer>(`/crm/customers/${customerId}`)
}

export function updateCustomer(customerId: string, input: CustomerInput): Promise<Customer> {
  return apiRequest<Customer>(`/crm/customers/${customerId}`, jsonRequest("PUT", input))
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
    jsonRequest("PUT", input),
  )
}

export function deleteFollowUp(customerId: string, followUpId: string): Promise<void> {
  return apiRequest<void>(`/crm/customers/${customerId}/follow-ups/${followUpId}`, { method: "DELETE" })
}

function jsonRequest(method: "POST" | "PUT", body: object): RequestInit {
  return { method, body: JSON.stringify(body) }
}

export function emptyToNull(value: string): string | null {
  const normalized = value.trim()
  return normalized || null
}
