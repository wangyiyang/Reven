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
      typeof error?.message === "string" ? error.message : undefined,
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
