import { apiRequest, ApiError } from "@/lib/api"
import type { BindingTestResult, BindingTestStage, FeishuBitableBindingConfig, FeishuResourceBinding } from "./types"

/** 绑定表单输入（create/update 共用：仅 config；启停走 enable/disable 独立端点） */
export interface FeishuBindingInput {
  app_token: string
  table_id: string
}

export type FeishuBindingAction =
  | { action: "create"; input: FeishuBindingInput; enabled: boolean }
  | { action: "update"; id: string; input: FeishuBindingInput }
  | { action: "enable"; id: string }
  | { action: "disable"; id: string }
  | { action: "delete"; id: string }

export interface FeishuBindingActionResult {
  message: string
}

const BINDINGS_PATH = "/integrations/feishu_bot/bindings"

export async function fetchFeishuBindings(): Promise<FeishuResourceBinding[]> {
  const value = await apiRequest<unknown>(BINDINGS_PATH)
  if (!Array.isArray(value) || !value.every(isFeishuResourceBinding)) throw invalidResponse()
  return value
}

export async function runFeishuBindingAction(action: FeishuBindingAction): Promise<FeishuBindingActionResult> {
  if (action.action === "create") {
    // resource_type/purpose 当前唯一受支持组合（bitable/rss_candidates），由后端 Literal 白名单兜底校验
    const body = {
      resource_type: "bitable",
      purpose: "rss_candidates",
      config: action.input,
      enabled: action.enabled,
    }
    const value = await apiRequest<unknown>(BINDINGS_PATH, { method: "POST", body: JSON.stringify(body) })
    if (!isFeishuResourceBinding(value)) throw invalidResponse()
    return { message: "绑定已创建" }
  }
  if (action.action === "update") {
    const value = await apiRequest<unknown>(`${BINDINGS_PATH}/${action.id}`, {
      method: "PUT",
      body: JSON.stringify({ config: action.input }),
    })
    if (!isFeishuResourceBinding(value)) throw invalidResponse()
    return { message: "绑定已更新" }
  }
  if (action.action === "enable" || action.action === "disable") {
    const enabling = action.action === "enable"
    const value = await apiRequest<unknown>(`${BINDINGS_PATH}/${action.id}/${enabling ? "enable" : "disable"}`, { method: "POST" })
    if (!isFeishuResourceBinding(value)) throw invalidResponse()
    return { message: enabling ? "绑定已启用" : "绑定已停用" }
  }
  await apiRequest<void>(`${BINDINGS_PATH}/${action.id}`, { method: "DELETE" })
  return { message: "绑定已删除" }
}

export async function testFeishuBinding(id: string): Promise<BindingTestResult> {
  const value = await apiRequest<unknown>(`${BINDINGS_PATH}/${id}/test`, { method: "POST" })
  if (!isBindingTestResult(value)) throw invalidResponse()
  return value
}

function isFeishuResourceBinding(value: unknown): value is FeishuResourceBinding {
  if (!isRecord(value)) return false
  return (
    typeof value.id === "string"
    && typeof value.resource_type === "string"
    && typeof value.purpose === "string"
    && isBitableConfig(value.config)
    && typeof value.enabled === "boolean"
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string"
  )
}

function isBitableConfig(value: unknown): value is FeishuBitableBindingConfig {
  return isRecord(value) && typeof value.app_token === "string" && typeof value.table_id === "string"
}

function isBindingTestResult(value: unknown): value is BindingTestResult {
  if (!isRecord(value)) return false
  return (
    typeof value.success === "boolean"
    && nullableString(value.failed_stage)
    && Array.isArray(value.stages) && value.stages.every(isBindingTestStage)
    && nullableString(value.message)
  )
}

function isBindingTestStage(value: unknown): value is BindingTestStage {
  return isRecord(value) && typeof value.stage === "string" && typeof value.success === "boolean" && nullableString(value.message)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string"
}

function invalidResponse(): ApiError {
  return new ApiError(200, "invalid_response", "绑定响应格式无效")
}
