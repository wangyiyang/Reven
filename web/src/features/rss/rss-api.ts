import { apiRequest, ApiError } from "@/lib/api"
import type { RssKeyword, RssSource } from "./types"

export interface RssSourceInput {
  name: string
  feed_url: string
  enabled: boolean
}

export interface RssKeywordInput {
  term: string
  kind: "positive" | "negative"
  enabled: boolean
}

export type RssSettingsAction =
  | { action: "create-source"; input: RssSourceInput }
  | { action: "update-source"; id: string; input: RssSourceInput }
  | { action: "delete-source"; id: string }
  | { action: "create-keyword"; input: RssKeywordInput }
  | { action: "update-keyword"; id: string; input: RssKeywordInput }
  | { action: "delete-keyword"; id: string }

export interface RssSettingsActionResult {
  message: string
  queryKey: "rss-sources" | "rss-keywords"
}

export async function fetchRssSources(): Promise<RssSource[]> {
  const value = await apiRequest<unknown>("/rss/sources")
  if (!Array.isArray(value) || !value.every(isRssSource)) throw invalidResponse()
  return value
}

export async function fetchRssKeywords(): Promise<RssKeyword[]> {
  const value = await apiRequest<unknown>("/rss/keywords")
  if (!Array.isArray(value) || !value.every(isRssKeyword)) throw invalidResponse()
  return value
}

export async function runRssSettingsAction(action: RssSettingsAction): Promise<RssSettingsActionResult> {
  if (action.action === "delete-source") {
    await apiRequest<void>(`/rss/sources/${action.id}`, { method: "DELETE" })
    return { message: "RSS 源已删除", queryKey: "rss-sources" }
  }
  if (action.action === "delete-keyword") {
    await apiRequest<void>(`/rss/keywords/${action.id}`, { method: "DELETE" })
    return { message: "关键词已删除", queryKey: "rss-keywords" }
  }
  if (action.action === "create-keyword" || action.action === "update-keyword") {
    const creating = action.action === "create-keyword"
    const path = creating ? "/rss/keywords" : `/rss/keywords/${action.id}`
    const keyword = await apiRequest<unknown>(path, {
      method: creating ? "POST" : "PUT",
      body: JSON.stringify(action.input),
    })
    if (!isRssKeyword(keyword)) throw invalidResponse()
    return { message: creating ? "关键词已添加" : "关键词已更新", queryKey: "rss-keywords" }
  }
  const creating = action.action === "create-source"
  const path = creating ? "/rss/sources" : `/rss/sources/${action.id}`
  const value = await apiRequest<unknown>(path, {
    method: creating ? "POST" : "PUT",
    body: JSON.stringify(action.input),
  })
  if (!isRssSource(value)) throw invalidResponse()
  return { message: creating ? "RSS 源已添加" : "RSS 源已更新", queryKey: "rss-sources" }
}

function isRssSource(value: unknown): value is RssSource {
  return isRecord(value)
    && typeof value.id === "string"
    && typeof value.name === "string"
    && isHttpUrl(value.feed_url)
    && typeof value.enabled === "boolean"
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string"
}

function isRssKeyword(value: unknown): value is RssKeyword {
  return isRecord(value)
    && typeof value.id === "string"
    && typeof value.term === "string"
    && (value.kind === "positive" || value.kind === "negative")
    && typeof value.enabled === "boolean"
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string"
}

function isHttpUrl(value: unknown): value is string {
  if (typeof value !== "string") return false
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:"
  } catch {
    return false
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function invalidResponse(): ApiError {
  return new ApiError(200, "invalid_response", "RSS 配置响应格式无效")
}
