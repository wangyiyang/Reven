import { ApiError } from "@/lib/api"
import type {
  ArticleDetail,
  ArticleList,
  ArticleSummary,
  ChannelName,
  ChannelResult,
  ContentSyncRun,
  ContentSyncSummary,
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
    selected_cover_asset_id: typeof data.selected_cover_asset_id === "string" ? data.selected_cover_asset_id : null,
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
    brand_binding_key: typeof data.brand_binding_key === "string" ? data.brand_binding_key : "legacy",
    brand: parseJobBrand(data.brand),
    created_at: dateTime(data.created_at, "任务详情"),
    updated_at: dateTime(data.updated_at, "任务详情"),
  }
}

function parseJobBrand(value: unknown): JobDetail["brand"] {
  if (value === null || value === undefined) return null
  const data = record(value, "任务品牌绑定")
  const fingerprint = record(data.version_fingerprint ?? {}, "任务品牌绑定")
  return {
    binding_key: typeof data.binding_key === "string" ? data.binding_key : "",
    version_fingerprint: {
      brand_version: typeof fingerprint.brand_version === "number" ? fingerprint.brand_version : undefined,
      wechat_template_version:
        typeof fingerprint.wechat_template_version === "number" ? fingerprint.wechat_template_version : null,
      blog_template_version:
        typeof fingerprint.blog_template_version === "number" ? fingerprint.blog_template_version : null,
    },
  }
}

export function parsePreview(value: unknown): { html: string } {
  return { html: string(record(value, "微信预览").html, "微信预览") }
}

export function parsePortableMarkdown(value: unknown): { markdown: string } {
  return { markdown: string(record(value, "可移植 Markdown").markdown, "可移植 Markdown") }
}

export function parseAction(value: unknown): { ok: boolean; job_id: string } {
  const data = record(value, "任务操作")
  return { ok: boolean(data.ok, "任务操作"), job_id: string(data.job_id, "任务操作") }
}

export function parseSyncRun(value: unknown): ContentSyncRun {
  const data = record(value, "同步操作")
  return {
    id: string(data.id, "同步操作"),
    article_id: string(data.article_id, "同步操作"),
    status: string(data.status, "同步操作"),
    stage: string(data.stage, "同步操作"),
    progress_current: integer(data.progress_current, "同步操作"),
    progress_total: integer(data.progress_total, "同步操作"),
    current_media: nullableString(data.current_media, "同步操作"),
    error_stage: nullableString(data.error_stage, "同步操作"),
    error_code: nullableString(data.error_code, "同步操作"),
    error_message: nullableError(data.error_message, "同步操作"),
    error_media: nullableString(data.error_media, "同步操作"),
    retryable: boolean(data.retryable, "同步操作"),
    attempt_count: integer(data.attempt_count, "同步操作"),
    created_at: dateTime(data.created_at, "同步操作"),
    updated_at: dateTime(data.updated_at, "同步操作"),
    created: data.created === undefined ? null : nullableBoolean(data.created, "同步操作"),
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
    target_channels: stringArray(data.target_channels, "稿件"),
    planned_at: nullableDateTime(data.planned_at, "稿件"),
    notion_last_edited_at: dateTime(data.notion_last_edited_at, "稿件"),
    last_synced_at: dateTime(data.last_synced_at, "稿件"),
    cover_valid: boolean(data.cover_valid, "稿件"),
    content_sync: parseContentSync(data.content_sync),
    blog_status: nullableString(data.blog_status, "稿件"),
    wechat_status: nullableString(data.wechat_status, "稿件"),
  }
}

function parseContentSync(value: unknown): ContentSyncSummary {
  const data = record(value, "内容同步状态")
  const current = data.current_snapshot === null ? null : record(data.current_snapshot, "内容快照")
  return {
    status: string(data.status, "内容同步状态"),
    outputs_enabled: boolean(data.outputs_enabled, "内容同步状态"),
    error: nullableError(data.error, "内容同步状态"),
    current_snapshot: current === null ? null : {
      id: string(current.id, "内容快照"),
      synced_at: dateTime(current.synced_at, "内容快照"),
      source_last_edited_at: dateTime(current.source_last_edited_at, "内容快照"),
      content_hash: string(current.content_hash, "内容快照"),
      character_count: integer(current.character_count, "内容快照"),
      media_count: integer(current.media_count, "内容快照"),
    },
    latest_run: data.latest_run === null ? null : parseSyncRun(data.latest_run),
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

/** 稿件目标渠道只做展示，容忍发布链路外的渠道值（如「掘金」），不因陌生值打挂整页 */
function stringArray(value: unknown, name: string): string[] {
  return array(value, name).map((item) => string(item, name))
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

function nullableBoolean(value: unknown, name: string): boolean | null {
  if (value === null) return null
  return boolean(value, name)
}

function invalid(name: string): never {
  throw new ApiError(200, "invalid_response", `${name}响应格式无效`)
}
