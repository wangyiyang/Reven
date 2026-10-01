import { apiRequest, ApiError } from "@/lib/api"
import { PROVIDERS, type AgentModelTestResult, type Integration, type Provider } from "./types"

export type IntegrationAction =
  | { action: "save"; provider: Provider; publicConfig: Record<string, unknown>; secret?: Record<string, unknown> }
  | { action: "delete"; provider: Provider }
  | { action: "test"; provider: Provider }
  | { action: "set-default-model"; provider: Provider; ref: string }
  | { action: "test-model"; provider: Provider; ref: string }

export interface IntegrationActionResult {
  message: string
  /** false 表示业务失败（如连接测试未通过）：不抛错，由控制器 toast.error 并局部更新缓存 */
  ok?: boolean
  /** test 动作回传的最新集成状态，供控制器 setQueryData 局部更新（避免整表 refetch 清空暂存） */
  integration?: Integration
  /** test-model 动作的行级测试结果（其他动作无此字段） */
  modelTest?: AgentModelTestResult
}

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

export async function runIntegrationAction(action: IntegrationAction): Promise<IntegrationActionResult> {
  if (action.action === "save") {
    const body = { public_config: action.publicConfig, ...(action.secret ? { secret: action.secret } : {}) }
    await requestIntegration(`/integrations/${action.provider}`, { method: "PUT", body: JSON.stringify(body) })
    return { message: action.secret ? "配置与密钥已保存" : "配置已保存" }
  }
  if (action.action === "delete") {
    await requestIntegration(`/integrations/${action.provider}/secret`, { method: "DELETE" })
    return { message: "密钥已删除" }
  }
  if (action.action === "set-default-model") {
    await requestIntegration(`/integrations/${action.provider}/default-model`, {
      method: "POST",
      body: JSON.stringify({ ref: action.ref }),
    })
    return { message: `已把 ${action.ref} 设为默认模型` }
  }
  if (action.action === "test-model") {
    const result = await requestModelTest(action.provider, action.ref)
    return {
      message: result.success
        ? `${action.ref} 连接正常${result.latency_ms !== null ? `（${result.latency_ms} ms）` : ""}`
        : `${action.ref} 连接测试失败${result.message ? `：${result.message}` : ""}`,
      modelTest: result,
    }
  }
  const result = await requestIntegration(`/integrations/${action.provider}/test`, { method: "POST" })
  const sendsMessage = action.provider === "feishu_bot"
  // 连接未通过不作为异常抛出：回传最新集成状态，控制器据此局部更新缓存并 toast.error（#179）
  if (result.connection_status !== "连接正常") {
    return {
      message: result.last_error || (sendsMessage ? "测试消息发送失败" : "连接测试失败"),
      ok: false,
      integration: result,
    }
  }
  return { message: sendsMessage ? "测试消息已发送" : "连接测试已完成", ok: true, integration: result }
}

async function requestIntegration(path: string, init: RequestInit): Promise<Integration> {
  const result = await apiRequest<unknown>(path, init)
  if (!isIntegration(result)) throw invalidResponse()
  return result
}

async function requestModelTest(provider: Provider, ref: string): Promise<AgentModelTestResult> {
  const result = await apiRequest<unknown>(`/integrations/${provider}/test`, {
    method: "POST",
    body: JSON.stringify({ model_ref: ref }),
  })
  if (!isAgentModelTest(result)) throw invalidResponse()
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
    && (value.model_key_refs === undefined || value.model_key_refs === null
      || (Array.isArray(value.model_key_refs) && value.model_key_refs.every((item) => typeof item === "string")))
  )
}

function isAgentModelTest(value: unknown): value is AgentModelTestResult {
  if (!isRecord(value)) return false
  return (
    typeof value.ref === "string"
    && typeof value.success === "boolean"
    && nullableString(value.message)
    && (value.latency_ms === null || typeof value.latency_ms === "number")
    && typeof value.tested_at === "string"
  )
}

function isProvider(value: unknown): value is Provider {
  return PROVIDERS.some((definition) => definition.provider === value)
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

function invalidResponse(): ApiError {
  return new ApiError(200, "invalid_response", "集成配置响应格式无效")
}
