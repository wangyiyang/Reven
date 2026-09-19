import { apiRequest, ApiError } from "@/lib/api"
import type { Integration, Provider } from "./types"

export interface EgressResponse {
  available: boolean
  ip: string | null
}

export type IntegrationAction =
  | { action: "save"; provider: Provider; publicConfig: Record<string, unknown>; secret?: Record<string, string> }
  | { action: "delete"; provider: Provider }
  | { action: "test"; provider: Provider }
  | { action: "bootstrap"; provider: "notion" }

export interface RssRunError {
  stage?: string
  error_type: string
}

export interface RssRunHealth {
  run_date: string
  status: "running" | "screening" | "partial" | "completed"
  started_at: string
  finished_at: string | null
  candidate_count: number
  failure_count: number
  errors: RssRunError[]
  notification_error: string | null
}

export async function fetchLatestRssRun(): Promise<RssRunHealth | null> {
  try {
    const value = await apiRequest<unknown>("/rss/runs/latest")
    if (!isRssRunHealth(value)) throw new ApiError(200, "invalid_response", "每日任务状态响应格式无效")
    return value
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export async function fetchIntegrations(): Promise<Integration[]> {
  const value = await apiRequest<unknown>("/integrations")
  if (!Array.isArray(value) || !value.every(isIntegration)) {
    throw new ApiError(200, "invalid_response", "集成配置响应格式无效")
  }
  return value
}

export async function runIntegrationAction(action: IntegrationAction): Promise<{ message: string }> {
  if (action.action === "save") {
    const body = { public_config: action.publicConfig, ...(action.secret ? { secret: action.secret } : {}) }
    await requestIntegration(`/integrations/${action.provider}`, { method: "PUT", body: JSON.stringify(body) })
    return { message: "配置已保存" }
  }
  if (action.action === "delete") {
    await requestIntegration(`/integrations/${action.provider}/secret`, { method: "DELETE" })
    return { message: "密钥已删除" }
  }
  if (action.action === "test") {
    await requestIntegration(`/integrations/${action.provider}/test`, { method: "POST" })
    return { message: action.provider === "feishu" ? "测试消息已发送" : "连接测试已完成" }
  }
  const result = await apiRequest<unknown>("/integrations/notion/bootstrap-schema", { method: "POST" })
  if (!isBootstrapResult(result)) throw invalidResponse()
  return { message: "Notion 字段初始化完成" }
}

async function requestIntegration(path: string, init: RequestInit): Promise<Integration> {
  const result = await apiRequest<unknown>(path, init)
  if (!isIntegration(result)) throw invalidResponse()
  return result
}

function isIntegration(value: unknown): value is Integration {
  if (!isRecord(value) || !isProvider(value.provider) || !isRecord(value.public_config)) return false
  return (
    typeof value.secret_configured === "boolean"
    && nullableString(value.secret_hint)
    && typeof value.connection_status === "string"
    && nullableString(value.last_tested_at)
    && nullableString(value.last_error)
    && (value.last_latency_ms === null || typeof value.last_latency_ms === "number")
  )
}

function isProvider(value: unknown): value is Provider {
  return value === "notion" || value === "github" || value === "wechat" || value === "feishu"
    || value === "feishu_bot"
    || value === "translate_baidu" || value === "translate_aliyun" || value === "embedding"
}

function isRssRunHealth(value: unknown): value is RssRunHealth {
  if (!isRecord(value)) return false
  return (
    typeof value.run_date === "string"
    && (value.status === "running" || value.status === "screening" || value.status === "partial" || value.status === "completed")
    && typeof value.started_at === "string"
    && nullableString(value.finished_at)
    && typeof value.candidate_count === "number"
    && typeof value.failure_count === "number"
    && Array.isArray(value.errors) && value.errors.every(isRssRunError)
    && nullableString(value.notification_error)
  )
}

function isRssRunError(value: unknown): value is RssRunError {
  return isRecord(value) && typeof value.error_type === "string"
    && (value.stage === undefined || typeof value.stage === "string")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function isBootstrapResult(value: unknown): value is { patched: boolean; properties: string[] } {
  return isRecord(value) && typeof value.patched === "boolean"
    && Array.isArray(value.properties) && value.properties.every((item) => typeof item === "string")
}

function invalidResponse(): ApiError {
  return new ApiError(200, "invalid_response", "集成配置响应格式无效")
}
