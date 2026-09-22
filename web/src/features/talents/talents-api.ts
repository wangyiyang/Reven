import { apiRequest } from "@/lib/api"

import type { Talent, TalentInteraction, TalentInteractionInput } from "./types"

export const talentsKeys = {
  talents: ["talents"] as const,
  talent: (talentId: string) => ["talents", "talent", talentId] as const,
  interactions: (talentId: string) => ["talents", "interactions", talentId] as const,
}

export function getTalent(talentId: string): Promise<Talent> {
  return apiRequest<Talent>(`/talents/${talentId}`)
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
