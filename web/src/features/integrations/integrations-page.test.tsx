import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { IntegrationsPage } from "./integrations-page"
import { server } from "@/test/server"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const configuredWechat = {
  provider: "wechat",
  public_config: { app_id: "wx123", author: "王翊仰" },
  secret_configured: true,
  secret_hint: "已配置 · ****9f2a",
  connection_status: "连接正常",
  last_tested_at: "2026-07-30T00:01:00Z",
  last_error: null,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <IntegrationsPage />
    </QueryClientProvider>,
  )
}

describe("IntegrationsPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows a loading skeleton without implying integrations are unconfigured", async () => {
    server.use(http.get("/api/integrations", async () => {
      await delay(80)
      return HttpResponse.json([configuredWechat])
    }))

    renderPage()

    expect(screen.getByRole("region", { name: "正在读取集成配置" })).toHaveAttribute("aria-busy", "true")
    expect(screen.queryByText("未配置")).not.toBeInTheDocument()
    expect(await screen.findByText("已配置 · ****9f2a")).toBeInTheDocument()
  })

  it("shows configured state without putting the secret into the input", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredWechat])))

    renderPage()

    expect(await screen.findByText("已配置 · ****9f2a")).toBeInTheDocument()
    expect(screen.getByLabelText("AppSecret")).toHaveValue("")
  })

  it("keeps the existing secret when saving an empty secret input", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat])),
      http.put("/api/integrations/wechat", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredWechat)
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "保存微信配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { app_id: "wx123", author: "王翊仰" },
    }))
  })

  it("replaces a secret through a separate explicit action", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat])),
      http.put("/api/integrations/wechat", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({ ...configuredWechat, secret_hint: "已配置 · ****new1" })
      }),
    )
    renderPage()

    await userEvent.type(await screen.findByLabelText("AppSecret"), "wechat-new1")
    await userEvent.click(screen.getByRole("button", { name: "替换微信密钥" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { app_id: "wx123", author: "王翊仰" },
      secret: { app_secret: "wechat-new1" },
    }))
  })

  it("requires explicit confirmation before deleting a secret", async () => {
    const deleteRequest = vi.fn()
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat])),
      http.delete("/api/integrations/wechat/secret", () => {
        deleteRequest()
        return HttpResponse.json({ ...configuredWechat, secret_configured: false, secret_hint: null })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除微信密钥" }))
    expect(deleteRequest).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "确认删除微信密钥" }))
    await waitFor(() => expect(deleteRequest).toHaveBeenCalledOnce())
  })

  it("returns keyboard focus to the delete trigger after dismissing confirmation", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredWechat])))
    renderPage()

    const trigger = await screen.findByRole("button", { name: "删除微信密钥" })
    await userEvent.click(trigger)
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    await userEvent.keyboard("{Escape}")

    expect(trigger).toHaveFocus()
  })

  it("only sends an active message when testing Feishu", async () => {
    const feishu = {
      provider: "feishu",
      public_config: { name: "发布通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
    }
    const tests: string[] = []
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat, feishu])),
      http.post("/api/integrations/:provider/test", ({ params }) => {
        tests.push(String(params.provider))
        return HttpResponse.json(params.provider === "feishu" ? { ...feishu, connection_status: "连接正常" } : configuredWechat)
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "测试微信连接" }))
    const feishuButton = screen.getByRole("button", { name: "发送飞书测试消息" })
    await waitFor(() => expect(feishuButton).toBeEnabled())
    await userEvent.click(feishuButton)
    await waitFor(() => expect(tests).toEqual(["wechat", "feishu"]))
    expect(screen.getByText("测试飞书会主动发送一条消息。")).toBeInTheDocument()
  })

  it("synchronously prevents duplicate Feishu test messages", async () => {
    const feishu = {
      provider: "feishu",
      public_config: { name: "发布通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
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
      public_config: { name: "发布通知" },
      secret_configured: true,
      secret_hint: "已配置 · ****-123",
      connection_status: "未测试",
      last_tested_at: null,
      last_error: null,
    }
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat, feishu])),
      http.post("/api/integrations/wechat/test", async () => {
        await delay(100)
        return HttpResponse.json(configuredWechat)
      }),
    )
    renderPage()
    const wechatButton = await screen.findByRole("button", { name: "测试微信连接" })
    const feishuButton = screen.getByRole("button", { name: "发送飞书测试消息" })

    await userEvent.click(wechatButton)

    expect(feishuButton).toBeDisabled()
    expect(screen.getByRole("status")).toHaveTextContent("其他操作暂时不可用")
    await waitFor(() => expect(feishuButton).toBeEnabled())
  })

  it("releases the action lock after a failed request", async () => {
    let calls = 0
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat])),
      http.post("/api/integrations/wechat/test", () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ code: "failed", message: "连接失败" }, { status: 503 })
        return HttpResponse.json(configuredWechat)
      }),
    )
    renderPage()
    const testButton = await screen.findByRole("button", { name: "测试微信连接" })

    await userEvent.click(testButton)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("连接失败"))
    await userEvent.click(testButton)

    await waitFor(() => expect(calls).toBe(2))
  })

  it("initializes Notion fields through the explicit action", async () => {
    const notion = {
      provider: "notion",
      public_config: {
        database_id: "22222222-2222-2222-2222-222222222222",
        data_source_id: "11111111-1111-1111-1111-111111111111",
      },
      secret_configured: true,
      secret_hint: "已配置 · ****aaaa",
      connection_status: "连接正常",
      last_tested_at: null,
      last_error: null,
    }
    let calls = 0
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([notion])),
      http.post("/api/integrations/notion/bootstrap-schema", () => {
        calls += 1
        return HttpResponse.json({ patched: true, properties: ["自动化状态"] })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "初始化字段" }))

    await waitFor(() => expect(calls).toBe(1))
  })

  it("moves focus to the stable save action after successful secret deletion", async () => {
    let secretConfigured = true
    const currentWechat = () => ({
      ...configuredWechat,
      secret_configured: secretConfigured,
      secret_hint: secretConfigured ? configuredWechat.secret_hint : null,
    })
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([currentWechat()])),
      http.delete("/api/integrations/wechat/secret", () => {
        secretConfigured = false
        return HttpResponse.json(currentWechat())
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除微信密钥" }))
    await userEvent.click(screen.getByRole("button", { name: "确认删除微信密钥" }))

    const stableTarget = await screen.findByRole("button", { name: "保存微信配置" })
    await waitFor(() => expect(stableTarget).toHaveFocus())
    expect(screen.queryByRole("button", { name: "删除微信密钥" })).not.toBeInTheDocument()
  })

  it.each([
    ["malformed", () => HttpResponse.json({ provider: "wechat" })],
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
      http.get("/api/integrations", () => HttpResponse.json([configuredWechat])),
      http.post("/api/integrations/wechat/test", () => HttpResponse.json({ ok: true })),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "测试微信连接" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("集成配置响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
  })
})
