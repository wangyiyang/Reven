export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message?: string,
  ) {
    super(message ?? "请求失败")
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  const body = await response.json().catch(() => null) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiError(response.status, body?.code ?? "request_failed", body?.message)
  }
  return body as T
}
