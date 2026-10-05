import { apiRequest } from "@/lib/api"

export type DashboardFinanceSummary = {
  receivable_cents: number
  receivable_count: number
  overdue_receivable_cents: number
  overdue_receivable_count: number
}

export type DashboardRssRun = {
  status: string
  failure_count: number
  finished_at: string | null
}

export type DashboardRssSummary = {
  candidate_count: number
  saved_count: number
  latest_run: DashboardRssRun | null
}

export type DashboardCrmDueItem = {
  customer_id: string
  name: string
  next_action: string | null
  next_follow_up_on: string
  overdue_days: number
}

export type DashboardCrmSummary = {
  overdue_count: number
  today_count: number
  due_items: DashboardCrmDueItem[]
}

export type DashboardProjectItem = {
  id: string
  name: string
  due_on: string | null
  overdue: boolean
}

export type DashboardProjectSummary = {
  active_count: number
  items: DashboardProjectItem[]
}

export type DashboardIntegrationSummary = {
  missing_providers: string[]
  cos_configured: boolean
}

export type DashboardSummary = {
  finance: DashboardFinanceSummary
  rss: DashboardRssSummary
  crm: DashboardCrmSummary
  projects: DashboardProjectSummary
  integrations: DashboardIntegrationSummary
}

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return apiRequest<DashboardSummary>("/dashboard/summary")
}

/** 集成缺失横幅的 localStorage 持久化键；值为已关闭缺失 key 的 JSON 数组 */
export const MISSING_INTEGRATIONS_DISMISSED_KEY = "dashboard.missing-integrations.dismissed"

/** COS 不在 integrations API 内（走环境变量），横幅里用固定 key 表示 */
export const COS_MISSING_KEY = "cos"

export const PROVIDER_LABELS: Record<string, string> = {
  feishu_bot: "飞书应用",
  translate_baidu: "百度翻译",
  translate_aliyun: "阿里翻译",
  embedding: "Embedding",
  "agent-llm": "Agent LLM",
}

/** 当前缺失项 key 列表：5 个 DB provider 缺失 + COS 未配置 */
export function missingIntegrationKeys(summary: DashboardIntegrationSummary): string[] {
  return [...summary.missing_providers, ...(summary.cos_configured ? [] : [COS_MISSING_KEY])]
}

export function missingIntegrationLabel(key: string): string {
  return key === COS_MISSING_KEY ? "腾讯云 COS（环境变量）" : (PROVIDER_LABELS[key] ?? key)
}

export function loadDismissedMissingKeys(): string[] {
  try {
    const raw = localStorage.getItem(MISSING_INTEGRATIONS_DISMISSED_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((key): key is string => typeof key === "string")
  } catch {
    return []
  }
}

export function saveDismissedMissingKeys(keys: string[]): void {
  try {
    localStorage.setItem(MISSING_INTEGRATIONS_DISMISSED_KEY, JSON.stringify(keys))
  } catch {
    // 存储不可用（隐私模式等）：仅保持会话内状态
  }
}
