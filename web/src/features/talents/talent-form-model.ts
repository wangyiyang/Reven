import { emptyToNull } from "../crm/crm-api"

import type { RateUnit, Talent, TalentInput, TalentStatus } from "./types"

export type TalentFormValues = {
  name: string
  organization: string
  tags: string[]
  phone: string
  email: string
  wechat: string
  preferences: string[]
  capability: string
  engagement_terms: string
  availability: string
  rate_amount: string
  rate_unit: RateUnit | ""
  rating: string
  status: TalentStatus
  notes: string
}

export const EMPTY_TALENT_FORM: TalentFormValues = {
  name: "",
  organization: "",
  tags: [],
  phone: "",
  email: "",
  wechat: "",
  preferences: [],
  capability: "",
  engagement_terms: "",
  availability: "",
  rate_amount: "",
  rate_unit: "",
  rating: "",
  status: "候选",
  notes: "",
}

export function talentToForm(talent: Talent): TalentFormValues {
  return {
    name: talent.name,
    organization: talent.organization ?? "",
    tags: talent.tags,
    phone: talent.phone ?? "",
    email: talent.email ?? "",
    wechat: talent.wechat ?? "",
    preferences: talent.preferences,
    capability: talent.capability ?? "",
    engagement_terms: talent.engagement_terms ?? "",
    availability: talent.availability ?? "",
    rate_amount: talent.rate_amount ?? "",
    rate_unit: talent.rate_unit ?? "",
    rating: talent.rating === null ? "" : String(talent.rating),
    status: talent.status,
    notes: talent.notes ?? "",
  }
}

export function talentFormToInput(values: TalentFormValues): TalentInput {
  return {
    name: values.name.trim(),
    organization: emptyToNull(values.organization),
    tags: values.tags,
    phone: emptyToNull(values.phone),
    email: emptyToNull(values.email),
    wechat: emptyToNull(values.wechat),
    preferences: values.preferences,
    capability: emptyToNull(values.capability),
    engagement_terms: emptyToNull(values.engagement_terms),
    availability: emptyToNull(values.availability),
    rate_amount: values.rate_amount.trim() || null,
    rate_unit: values.rate_unit || null,
    rating: values.rating ? Number(values.rating) : null,
    status: values.status,
    notes: emptyToNull(values.notes),
  }
}

export function validateTalentForm(values: TalentFormValues): string | null {
  if (!values.name.trim()) return "请填写人才姓名"
  if (values.email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) return "邮箱格式不正确"
  const hasAmount = values.rate_amount.trim() !== ""
  const hasUnit = values.rate_unit !== ""
  if (hasAmount !== hasUnit) return "费率金额与单位需同时填写或同时留空"
  if (hasAmount && (Number.isNaN(Number(values.rate_amount)) || Number(values.rate_amount) < 0)) {
    return "费率金额需为不小于 0 的数字"
  }
  if (values.tags.length > 20) return "标签最多 20 个"
  if (values.preferences.length > 20) return "喜好最多 20 个"
  return null
}

export function appendTag(tags: string[], draft: string): string[] {
  const tag = draft.trim()
  if (!tag || tags.includes(tag)) return tags
  return [...tags, tag]
}

export function removeTag(tags: string[], tag: string): string[] {
  return tags.filter((item) => item !== tag)
}
