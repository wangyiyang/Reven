import { ApiError } from "@/lib/api"
import type {
  ArticleDetail,
  ArticleList,
  ArticleSummary,
  ChannelName,
  ChannelResult,
  JobDetail,
  JobSummary,
  ValidationItem,
} from "./types"

const channels = new Set<ChannelName>(["个人博客", "微信公众号"])

export function parseArticleList(value: unknown): ArticleList {
  const data = record(value, "稿件列表")
  return {
    items: array(data.items, "稿件列表").map(parseArticleSummary),
    total: integer(data.total, "稿件列表", 0),
    page: integer(data.page, "稿件列表", 1),
    page_size: integer(data.page_size, "稿件列表", 1),
  }
}

export function parseArticleDetail(value: unknown): ArticleDetail {
  const data = record(value, "稿件详情")
  return {
    ...parseArticleSummary(data),
    notion_metadata: record(data.notion_metadata, "稿件详情"),
    cover_metadata: record(data.cover_metadata, "稿件详情"),
    last_error: nullableError(data.last_error, "稿件详情"),
    content_hash: nullableString(data.content_hash, "稿件详情"),
    validation_errors: validationItems(data.validation_errors),
    validation_warnings: validationItems(data.validation_warnings),
    blog: nullableChannelResult(data.blog),
    wechat: nullableChannelResult(data.wechat),
    jobs: array(data.jobs, "稿件详情").map((item) => parseJobSummary(item)),
    jobs_total: integer(data.jobs_total, "稿件详情"),
    jobs_has_more: boolean(data.jobs_has_more, "稿件详情"),
  }
}

export function parseJobDetail(value: unknown): JobDetail {
  const data = record(value, "任务详情")
  return {
    ...parseJobSummary(data, "任务详情"),
    article_id: string(data.article_id, "任务详情"),
    snapshot_metadata: record(data.snapshot_metadata, "任务详情"),
    blog: parseChannelResult(data.blog),
    wechat: parseChannelResult(data.wechat),
    wechat_html: nullableString(data.wechat_html, "任务详情"),
    attempt_count: integer(data.attempt_count, "任务详情"),
    created_at: dateTime(data.created_at, "任务详情"),
    updated_at: dateTime(data.updated_at, "任务详情"),
  }
}

export function parsePreview(value: unknown): { html: string } {
  return { html: string(record(value, "微信预览").html, "微信预览") }
}

export function parseAction(value: unknown): { ok: boolean; job_id: string } {
  const data = record(value, "任务操作")
  return { ok: boolean(data.ok, "任务操作"), job_id: string(data.job_id, "任务操作") }
}

export function parseSync(value: unknown): {
  created: number
  updated: number
  failed: number
  duration_ms: number
} {
  const data = record(value, "同步操作")
  return {
    created: integer(data.created, "同步操作"),
    updated: integer(data.updated, "同步操作"),
    failed: integer(data.failed, "同步操作"),
    duration_ms: integer(data.duration_ms, "同步操作"),
  }
}

function parseArticleSummary(value: unknown): ArticleSummary {
  const data = record(value, "稿件")
  return {
    id: string(data.id, "稿件"),
    title: string(data.title, "稿件"),
    notion_url: string(data.notion_url, "稿件"),
    notion_status: string(data.notion_status, "稿件"),
    automation_status: string(data.automation_status, "稿件"),
    target_channels: channelArray(data.target_channels, "稿件"),
    planned_at: nullableDateTime(data.planned_at, "稿件"),
    notion_last_edited_at: dateTime(data.notion_last_edited_at, "稿件"),
    last_synced_at: dateTime(data.last_synced_at, "稿件"),
    cover_valid: boolean(data.cover_valid, "稿件"),
    blog_status: nullableString(data.blog_status, "稿件"),
    wechat_status: nullableString(data.wechat_status, "稿件"),
  }
}

function parseJobSummary(value: unknown, name = "任务"): JobSummary {
  const data = record(value, name)
  return {
    id: string(data.id, name),
    overall_status: string(data.overall_status, name),
    target_channels: channelArray(data.target_channels, name),
    scheduled_at: dateTime(data.scheduled_at, name),
    content_hash: nullableString(data.content_hash, name),
    blog_status: string(data.blog_status, name),
    wechat_status: string(data.wechat_status, name),
  }
}

function nullableChannelResult(value: unknown): ChannelResult | null {
  return value === null ? null : parseChannelResult(value)
}

function parseChannelResult(value: unknown): ChannelResult {
  const data = record(value, "渠道状态")
  const rawResult = record(data.result, "渠道状态")
  const result: Record<string, string | number> = {}
  for (const [key, item] of Object.entries(rawResult)) {
    if (typeof item !== "string" && typeof item !== "number") invalid("渠道状态")
    result[key] = item
  }
  return {
    status: string(data.status, "渠道状态"),
    error: nullableError(data.error, "渠道状态"),
    result,
  }
}

function validationItems(value: unknown): ValidationItem[] {
  return array(value, "校验结果").map((item) => {
    const data = record(item, "校验结果")
    return {
      code: optionalString(data.code, "校验结果"),
      field: optionalString(data.field, "校验结果"),
      message: optionalString(data.message, "校验结果"),
    }
  })
}

function channelArray(value: unknown, name: string): ChannelName[] {
  return array(value, name).map((item) => {
    if (typeof item !== "string" || !channels.has(item as ChannelName)) invalid(name)
    return item as ChannelName
  })
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid(name)
  return value as Record<string, unknown>
}

function array(value: unknown, name: string): unknown[] {
  if (!Array.isArray(value)) invalid(name)
  return value
}

function string(value: unknown, name: string): string {
  if (typeof value !== "string") invalid(name)
  return value
}

function optionalString(value: unknown, name: string): string | undefined {
  if (value === undefined) return undefined
  return string(value, name)
}

function nullableString(value: unknown, name: string): string | null {
  if (value === null) return null
  return string(value, name)
}

function nullableError(value: unknown, name: string): string | null {
  const parsed = nullableString(value, name)
  if (parsed === null) return null
  return parsed
    .replace(/https?:\/\/\S+/gi, "[已脱敏地址]")
    .replace(/(bearer|token|secret|password|appsecret)\s*[:=]?\s*\S+/gi, "$1=***")
    .slice(0, 1000)
}

function integer(value: unknown, name: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) invalid(name)
  return value
}

function nullableDateTime(value: unknown, name: string): string | null {
  if (value === null) return null
  return dateTime(value, name)
}

function dateTime(value: unknown, name: string): string {
  const parsed = string(value, name)
  const awareIso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
  if (!awareIso.test(parsed) || !Number.isFinite(Date.parse(parsed))) invalid(name)
  return parsed
}

function boolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") invalid(name)
  return value
}

function invalid(name: string): never {
  throw new ApiError(200, "invalid_response", `${name}响应格式无效`)
}
