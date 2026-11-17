export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message?: string,
  ) {
    super(message ?? "请求失败")
  }
}

export function redirectToLogin(): void {
  if (typeof window === "undefined" || window.location.pathname === "/login") return
  const next = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/login?next=${next}`)
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase()
  const headers = new Headers(init?.headers)
  headers.set("Content-Type", "application/json")
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) headers.set("X-Reven-CSRF", "1")
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
  })
  const text = await response.text()
  const body = parseJson(text)
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) redirectToLogin()
    const error = isObject(body) ? body : null
    throw new ApiError(
      response.status,
      typeof error?.code === "string" ? error.code : "request_failed",
      errorMessage(error),
    )
  }
  if (response.status === 204) return undefined as T
  if (body === undefined) throw new ApiError(response.status, "invalid_response", "服务返回了空响应")
  return body as T
}

function parseJson(text: string): unknown {
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

// 优先 {message}；FastAPI 校验错误（422）回退 {detail: string | [{msg, …}]}，
// 保证后端返回的可读校验信息能透传到 toast/面板
function errorMessage(error: Record<string, unknown> | null): string | undefined {
  if (typeof error?.message === "string") return error.message
  const detail = error?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (isObject(item) && typeof item.msg === "string" ? item.msg : ""))
      .filter(Boolean)
    if (messages.length > 0) return messages.join("；")
  }
  return undefined
}
