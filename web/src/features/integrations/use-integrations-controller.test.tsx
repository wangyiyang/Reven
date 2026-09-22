import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { delay, HttpResponse, http } from "msw"
import type { ReactNode } from "react"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { configuredRuntime } from "./test-helpers"
import { useIntegrationsController } from "./use-integrations-controller"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function renderController() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(() => useIntegrationsController(), { wrapper })
}

describe("useIntegrationsController", () => {
  beforeEach(() => vi.clearAllMocks())

  it("按 provider keyed 暴露控制器，携带集成状态且默认空闲", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])))
    const { result } = renderController()
    await waitFor(() => expect(result.current.integrations.isSuccess).toBe(true))

    const embedding = result.current.forProvider("embedding")
    expect(embedding.state.integration?.secret_hint).toBe("已配置 · ****9f2a")
    expect(embedding.state.busy).toBeNull()
    expect(embedding.state.disabled).toBe(false)
    expect(result.current.forProvider("feishu_bot").state.integration).toBeUndefined()
  })

  it("卡片动作映射为集成请求，busy 为按 provider 归属的结构化动作种类", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.put("/api/integrations/embedding", async ({ request }) => {
        requestBody = await request.json()
        await delay(50)
        return HttpResponse.json(configuredRuntime)
      }),
    )
    const { result } = renderController()
    await waitFor(() => expect(result.current.integrations.isSuccess).toBe(true))

    act(() => result.current.forProvider("embedding").actions.replace({ model: "BAAI/bge-m3" }, { api_key: "k1" }))

    await waitFor(() => expect(result.current.forProvider("embedding").state.busy).toBe("save"))
    expect(result.current.forProvider("feishu_bot").state.busy).toBeNull()
    expect(result.current.forProvider("feishu_bot").state.disabled).toBe(true)

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { model: "BAAI/bge-m3" },
      secret: { api_key: "k1" },
    }))
    await waitFor(() => expect(result.current.forProvider("embedding").state.busy).toBeNull())
    expect(toast.success).toHaveBeenCalledWith("配置已保存")
  })

  it("remove 以返回值传递删除是否成功", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.delete("/api/integrations/embedding/secret", () =>
        HttpResponse.json({ code: "failed", message: "删除失败" }, { status: 503 })),
    )
    const { result } = renderController()
    await waitFor(() => expect(result.current.integrations.isSuccess).toBe(true))

    let removed: boolean | undefined
    await act(async () => {
      removed = await result.current.forProvider("embedding").actions.remove()
    })

    expect(removed).toBe(false)
    expect(toast.error).toHaveBeenCalledWith("删除失败")
  })

  it("失败的请求之后释放动作锁，后续动作可用", async () => {
    let calls = 0
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.post("/api/integrations/embedding/test", () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ code: "failed", message: "连接失败" }, { status: 503 })
        return HttpResponse.json(configuredRuntime)
      }),
    )
    const { result } = renderController()
    await waitFor(() => expect(result.current.integrations.isSuccess).toBe(true))

    act(() => result.current.forProvider("embedding").actions.test())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("连接失败"))
    expect(result.current.forProvider("embedding").state.disabled).toBe(false)

    act(() => result.current.forProvider("embedding").actions.test())
    await waitFor(() => expect(calls).toBe(2))
  })
})
