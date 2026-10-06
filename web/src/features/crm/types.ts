export const CUSTOMER_STATUSES = ["潜在客户", "跟进中", "合作客户", "暂停跟进", "已流失"] as const
export const FOLLOW_UP_KINDS = ["电话", "会议", "微信", "邮件", "其他"] as const
export const DUE_FILTERS = ["overdue", "today", "upcoming", "none"] as const

export type CustomerStatus = (typeof CUSTOMER_STATUSES)[number]
export type FollowUpKind = (typeof FOLLOW_UP_KINDS)[number]
export type DueFilter = (typeof DUE_FILTERS)[number]

export type Customer = {
  id: string
  name: string
  status: CustomerStatus
  source: string | null
  notes: string | null
  /** 只读派生值：来自该客户最新一条跟进记录，无跟进时为 null */
  next_action: string | null
  /** 只读派生值：来自该客户最新一条跟进记录，无跟进时为 null */
  next_due_on: string | null
  created_at: string
  updated_at: string
}

export type CustomerInput = {
  name: string
  status: CustomerStatus
  source: string | null
  notes: string | null
}

export type CustomerFilters = {
  query: string
  status: CustomerStatus | ""
  due: DueFilter | ""
}

export type Contact = {
  id: string
  customer_id: string
  name: string
  role: string | null
  phone: string | null
  email: string | null
  wechat: string | null
  is_primary: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export type ContactInput = {
  name: string
  role: string | null
  phone: string | null
  email: string | null
  wechat: string | null
  is_primary: boolean
  notes: string | null
}

export type FollowUp = {
  id: string
  customer_id: string
  contact_id: string | null
  contact_name_snapshot: string | null
  kind: FollowUpKind
  occurred_on: string
  summary: string
  next_action: string | null
  next_due_on: string | null
  created_at: string
  updated_at: string
}

export type FollowUpInput = {
  contact_id: string | null
  kind: FollowUpKind
  occurred_on: string
  summary: string
  next_action: string | null
  next_due_on: string | null
}
