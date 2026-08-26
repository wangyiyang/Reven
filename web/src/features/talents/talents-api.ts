import { apiRequest } from "@/lib/api"

import type { Talent, TalentFilters, TalentInput, TalentInteraction, TalentInteractionInput } from "./types"

export const talentsKeys = {
  talents: ["talents"] as const,
  talent: (talentId: string) => ["talents", "talent", talentId] as const,
  interactions: (talentId: string) => ["talents", "interactions", talentId] as const,
}

export function listTalents(filters: TalentFilters): Promise<Talent[]> {
  const params = new URLSearchParams()
  if (filters.query.trim()) params.set("q", filters.query.trim())
  if (filters.status) params.set("status", filters.status)
  if (filters.due) params.set("due", filters.due)
  if (filters.tag.trim()) params.set("tag", filters.tag.trim())
  const suffix = params.size ? `?${params.toString()}` : ""
  return apiRequest<Talent[]>(`/talents${suffix}`)
}

export function getTalent(talentId: string): Promise<Talent> {
  return apiRequest<Talent>(`/talents/${talentId}`)
}

export function createTalent(input: TalentInput): Promise<Talent> {
  return apiRequest<Talent>("/talents", jsonRequest("POST", input))
}

export function updateTalent(talentId: string, input: TalentInput): Promise<Talent> {
  return apiRequest<Talent>(`/talents/${talentId}`, jsonRequest("PATCH", input))
}

export function deleteTalent(talentId: string): Promise<void> {
  return apiRequest<void>(`/talents/${talentId}`, { method: "DELETE" })
}

export function listInteractions(talentId: string): Promise<TalentInteraction[]> {
  return apiRequest<TalentInteraction[]>(`/talents/${talentId}/interactions`)
}

export function createInteraction(talentId: string, input: TalentInteractionInput): Promise<TalentInteraction> {
  return apiRequest<TalentInteraction>(`/talents/${talentId}/interactions`, jsonRequest("POST", input))
}

export function updateInteraction(interactionId: string, input: TalentInteractionInput): Promise<TalentInteraction> {
  return apiRequest<TalentInteraction>(`/talents/interactions/${interactionId}`, jsonRequest("PATCH", input))
}

export function deleteInteraction(interactionId: string): Promise<void> {
  return apiRequest<void>(`/talents/interactions/${interactionId}`, { method: "DELETE" })
}

function jsonRequest(method: "POST" | "PATCH", body: object): RequestInit {
  return { method, body: JSON.stringify(body) }
}
