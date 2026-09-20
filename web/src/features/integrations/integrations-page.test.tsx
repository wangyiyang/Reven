import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { configuredRuntime, findCard, renderPage } from "./test-helpers"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe("IntegrationsPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows a loading skeleton without implying integrations are unconfigured", async () => {
    server.use(http.get("/api/integrations", async () => {
      await delay(80)
      return HttpResponse.json([configuredRuntime])
    }))

    renderPage()

    expect(screen.getByRole("region", { name: "正在读取集成配置" })).toHaveAttribute("aria-busy", "true")
    expect(screen.queryByText("未配置")).not.toBeInTheDocument()
    expect(await screen.findByText("已配置 · ****9f2a")).toBeInTheDocument()
  })

  it("shows configured state without putting the secret into the input", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])))

    renderPage()

    expect(await screen.findByText("已配置 · ****9f2a")).toBeInTheDocument()
    expect((await findCard("Embedding")).getByLabelText("API Key")).toHaveValue("")
  })

  it("keeps the existing secret when saving an empty secret input", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.put("/api/integrations/embedding", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredRuntime)
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "保存Embedding配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { base_url: "https://api.siliconflow.cn", model: "BAAI/bge-m3" },
    }))
  })

  it("replaces a secret through a separate explicit action", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.put("/api/integrations/embedding", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({ ...configuredRuntime, secret_hint: "已配置 · ****new1" })
      }),
    )
    renderPage()

    await userEvent.type((await findCard("Embedding")).getByLabelText("API Key"), "embedding-new1")
    await userEvent.click(screen.getByRole("button", { name: "替换Embedding密钥" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { base_url: "https://api.siliconflow.cn", model: "BAAI/bge-m3" },
      secret: { api_key: "embedding-new1" },
    }))
  })

  it("requires explicit confirmation before deleting a secret", async () => {
    const deleteRequest = vi.fn()
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.delete("/api/integrations/embedding/secret", () => {
        deleteRequest()
        return HttpResponse.json({ ...configuredRuntime, secret_configured: false, secret_hint: null })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除Embedding密钥" }))
    expect(deleteRequest).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "确认删除Embedding密钥" }))
    await waitFor(() => expect(deleteRequest).toHaveBeenCalledOnce())
  })

  it("returns keyboard focus to the delete trigger after dismissing confirmation", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])))
    renderPage()

    const trigger = await screen.findByRole("button", { name: "删除Embedding密钥" })
    await userEvent.click(trigger)
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    await userEvent.keyboard("{Escape}")

    expect(trigger).toHaveFocus()
  })

  it("only sends an active message when testing Feishu", async () => {
    const feishu = {
      provider: "feishu",
      public_config: { name: "RSS 汇总通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
      last_latency_ms: null,
    }
    const tests: string[] = []
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime, feishu])),
      http.post("/api/integrations/:provider/test", ({ params }) => {
        tests.push(String(params.provider))
        return HttpResponse.json(params.provider === "feishu" ? { ...feishu, connection_status: "连接正常" } : configuredRuntime)
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "测试Embedding连接" }))
    const feishuButton = screen.getByRole("button", { name: "发送飞书测试消息" })
    await waitFor(() => expect(feishuButton).toBeEnabled())
    await userEvent.click(feishuButton)
    await waitFor(() => expect(tests).toEqual(["embedding", "feishu"]))
    expect(screen.getByText("测试飞书会主动发送一条消息。")).toBeInTheDocument()
  })

  it("synchronously prevents duplicate Feishu test messages", async () => {
    const feishu = {
      provider: "feishu",
      public_config: { name: "RSS 汇总通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
      last_latency_ms: null,
    }
    let calls = 0
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([feishu])),
      http.post("/api/integrations/feishu/test", async () => {
        calls += 1
        await delay(80)
        return HttpResponse.json({ ...feishu, connection_status: "连接正常" })
      }),
    )
    renderPage()

    await userEvent.dblClick(await screen.findByRole("button", { name: "发送飞书测试消息" }))

    await waitFor(() => expect(calls).toBe(1))
  })

  it("disables every card action while a cross-card action is running", async () => {
    const feishu = {
      provider: "feishu",
      public_config: { name: "RSS 汇总通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
      last_latency_ms: null,
    }
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime, feishu])),
      http.post("/api/integrations/embedding/test", async () => {
        await delay(100)
        return HttpResponse.json(configuredRuntime)
      }),
    )
    renderPage()
    const embeddingButton = await screen.findByRole("button", { name: "测试Embedding连接" })
    const feishuButton = screen.getByRole("button", { name: "发送飞书测试消息" })

    await userEvent.click(embeddingButton)

    expect(feishuButton).toBeDisabled()
    expect(screen.getByRole("status")).toHaveTextContent("其他操作暂时不可用")
    await waitFor(() => expect(feishuButton).toBeEnabled())
  })

  it("releases the action lock after a failed request", async () => {
    let calls = 0
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.post("/api/integrations/embedding/test", () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ code: "failed", message: "连接失败" }, { status: 503 })
        return HttpResponse.json(configuredRuntime)
      }),
    )
    renderPage()
    const testButton = await screen.findByRole("button", { name: "测试Embedding连接" })

    await userEvent.click(testButton)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("连接失败"))
    await userEvent.click(testButton)

    await waitFor(() => expect(calls).toBe(2))
  })

  it("moves focus to the stable save action after successful secret deletion", async () => {
    let secretConfigured = true
    const currentRuntime = () => ({
      ...configuredRuntime,
      secret_configured: secretConfigured,
      secret_hint: secretConfigured ? configuredRuntime.secret_hint : null,
    })
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([currentRuntime()])),
      http.delete("/api/integrations/embedding/secret", () => {
        secretConfigured = false
        return HttpResponse.json(currentRuntime())
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除Embedding密钥" }))
    await userEvent.click(screen.getByRole("button", { name: "确认删除Embedding密钥" }))

    const stableTarget = await screen.findByRole("button", { name: "保存Embedding配置" })
    await waitFor(() => expect(stableTarget).toHaveFocus())
    expect(screen.queryByRole("button", { name: "删除Embedding密钥" })).not.toBeInTheDocument()
  })

  it.each([
    ["malformed", () => HttpResponse.json({ provider: "embedding" })],
    ["empty", () => new HttpResponse(null, { status: 200 })],
  ])("shows a recoverable error for %s successful responses", async (_, response) => {
    server.use(http.get("/api/integrations", response))
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent(/响应格式无效|空响应/)
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument()
    expect(screen.queryByText("未配置")).not.toBeInTheDocument()
  })

  it("does not report success when an action returns malformed JSON", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime])),
      http.post("/api/integrations/embedding/test", () => HttpResponse.json({ ok: true })),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "测试Embedding连接" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("集成配置响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
  })

})
