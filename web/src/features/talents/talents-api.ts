import { apiRequest } from "@/lib/api"

import type {
  Talent,
  TalentEducation,
  TalentEducationInput,
  TalentExperience,
  TalentExperienceInput,
  TalentInteraction,
  TalentInteractionInput,
} from "./types"

export const talentsKeys = {
  talents: ["talents"] as const,
  talent: (talentId: string) => ["talents", "talent", talentId] as const,
  interactions: (talentId: string) => ["talents", "interactions", talentId] as const,
  experiences: (talentId: string) => ["talents", "experiences", talentId] as const,
  educations: (talentId: string) => ["talents", "educations", talentId] as const,
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

export function listExperiences(talentId: string): Promise<TalentExperience[]> {
  return apiRequest<TalentExperience[]>(`/talents/${talentId}/experiences`)
}

export function createExperience(talentId: string, input: TalentExperienceInput): Promise<TalentExperience> {
  return apiRequest<TalentExperience>(`/talents/${talentId}/experiences`, jsonRequest("POST", withMonthPrecision(input)))
}

export function updateExperience(
  talentId: string,
  experienceId: string,
  input: TalentExperienceInput,
): Promise<TalentExperience> {
  return apiRequest<TalentExperience>(
    `/talents/${talentId}/experiences/${experienceId}`,
    jsonRequest("PUT", withMonthPrecision(input)),
  )
}

export function deleteExperience(talentId: string, experienceId: string): Promise<void> {
  return apiRequest<void>(`/talents/${talentId}/experiences/${experienceId}`, { method: "DELETE" })
}

export function listEducations(talentId: string): Promise<TalentEducation[]> {
  return apiRequest<TalentEducation[]>(`/talents/${talentId}/educations`)
}

export function createEducation(talentId: string, input: TalentEducationInput): Promise<TalentEducation> {
  return apiRequest<TalentEducation>(`/talents/${talentId}/educations`, jsonRequest("POST", withMonthPrecision(input)))
}

export function updateEducation(
  talentId: string,
  educationId: string,
  input: TalentEducationInput,
): Promise<TalentEducation> {
  return apiRequest<TalentEducation>(
    `/talents/${talentId}/educations/${educationId}`,
    jsonRequest("PUT", withMonthPrecision(input)),
  )
}

export function deleteEducation(talentId: string, educationId: string): Promise<void> {
  return apiRequest<void>(`/talents/${talentId}/educations/${educationId}`, { method: "DELETE" })
}

/**
 * 履历/院校录入精度到月：无论 date 控件给出哪一天，提交前一律落为该月 1 日。
 * 浏览器拥有这层类型化序列化，API 只接受完整 YYYY-MM-DD，DB 不做二次猜测。
 */
function withMonthPrecision<T extends { start_on: string; end_on: string | null }>(input: T): T {
  return { ...input, start_on: monthStart(input.start_on), end_on: monthStart(input.end_on) }
}

function monthStart(day: string): string
function monthStart(day: string | null): string | null
function monthStart(day: string | null): string | null {
  return day === null ? null : `${day.slice(0, 7)}-01`
}

/** 展示精度到月；end_on 为空表示至今。 */
export function formatMonth(day: string | null): string {
  return day === null ? "至今" : day.slice(0, 7)
}

function jsonRequest(method: "POST" | "PATCH" | "PUT", body: object): RequestInit {
  return { method, body: JSON.stringify(body) }
}
