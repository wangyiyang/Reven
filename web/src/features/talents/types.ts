export const TALENT_STATUSES = ["候选", "接洽中", "已合作", "搁置"] as const
export const INTERACTION_CHANNELS = ["面谈", "电话语音", "微信", "邮件"] as const
export const RATE_UNITS = ["按小时", "按天", "按项目"] as const
export const DUE_FILTERS = ["overdue", "today", "upcoming", "none"] as const

export type TalentStatus = (typeof TALENT_STATUSES)[number]
export type InteractionChannel = (typeof INTERACTION_CHANNELS)[number]
export type RateUnit = (typeof RATE_UNITS)[number]
export type DueFilter = (typeof DUE_FILTERS)[number]

export type Talent = {
  id: string
  name: string
  organization: string | null
  tags: string[]
  phone: string | null
  email: string | null
  wechat: string | null
  preferences: string[]
  capability: string | null
  engagement_terms: string | null
  availability: string | null
  rate_amount: string | null
  rate_unit: RateUnit | null
  rating: number | null
  status: TalentStatus
  notes: string | null
  created_at: string
  updated_at: string
}

export type TalentInput = {
  name: string
  organization: string | null
  tags: string[]
  phone: string | null
  email: string | null
  wechat: string | null
  preferences: string[]
  capability: string | null
  engagement_terms: string | null
  availability: string | null
  rate_amount: string | null
  rate_unit: RateUnit | null
  rating: number | null
  status: TalentStatus
  notes: string | null
}

export type TalentFilters = {
  /** 列表接口的搜索参数名（后端约定为 q，seam 按 filters 键名直出查询参数） */
  q: string
  status: TalentStatus | ""
  due: DueFilter | ""
  tag: string
}

export type TalentInteraction = {
  id: string
  talent_id: string
  occurred_on: string
  channel: InteractionChannel
  summary: string | null
  next_action: string | null
  next_due_on: string | null
  created_at: string
}

export type TalentInteractionInput = {
  occurred_on: string
  channel: InteractionChannel
  summary: string | null
  next_action: string | null
  next_due_on: string | null
}

export type TalentExperience = {
  id: string
  talent_id: string
  company: string
  title: string
  description: string | null
  start_on: string
  end_on: string | null
  created_at: string
  updated_at: string
}

export type TalentExperienceInput = {
  company: string
  title: string
  description: string | null
  start_on: string
  end_on: string | null
}

export type TalentEducation = {
  id: string
  talent_id: string
  school: string
  degree: string | null
  major: string | null
  start_on: string
  end_on: string | null
  created_at: string
  updated_at: string
}

export type TalentEducationInput = {
  school: string
  degree: string | null
  major: string | null
  start_on: string
  end_on: string | null
}
