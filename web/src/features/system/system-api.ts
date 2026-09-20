import { ApiError, apiRequest } from "@/lib/api"

export interface Heartbeat {
  available: boolean
  last_heartbeat_at: string | null
}

export async function fetchSystemHealth() {
  const value = await apiRequest<unknown>("/health")
  if (!isRecord(value) || typeof value.service !== "string" || typeof value.status !== "string") {
    throw invalidResponse()
  }
  return { service: value.service, status: value.status }
}

export async function fetchSystemStatus() {
  const value = await apiRequest<unknown>("/system/status")
  if (!isRecord(value) || !isRecord(value.database) || typeof value.database.available !== "boolean"
    || !isHeartbeat(value.rss_discovery)) throw invalidResponse()
  return { database: { available: value.database.available }, rss_discovery: value.rss_discovery }
}

function isHeartbeat(value: unknown): value is Heartbeat {
  return isRecord(value) && typeof value.available === "boolean"
    && (value.last_heartbeat_at === null || (typeof value.last_heartbeat_at === "string"
      && !Number.isNaN(Date.parse(value.last_heartbeat_at))))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function invalidResponse() {
  return new ApiError(200, "invalid_response", "系统状态响应格式无效")
}
