import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { IntegrationsPage } from "./integrations-page"
import { server } from "@/test/server"

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
    await userEvent.click(screen.getByRole("button", { name: "发送飞书测试消息" }))
    await waitFor(() => expect(tests).toEqual(["wechat", "feishu"]))
    expect(screen.getByText("测试飞书会主动发送一条消息。")).toBeInTheDocument()
  })
})
