import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { configuredFeishuBot, configuredRuntime, findCard, renderPage } from "./test-helpers"
import type { Integration } from "./types"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe("Feishu application integration", () => {
  beforeEach(() => vi.clearAllMocks())

  it("only offers the application bot for notifications and review", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredFeishuBot])))
    renderPage()

    const card = await findCard("飞书应用")
    expect(screen.queryByRole("heading", { name: "飞书" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Webhook")).not.toBeInTheDocument()
    expect(card.getByText(/每日汇总和候选素材审核卡片/)).toBeInTheDocument()
    expect(card.getByLabelText("接收人 Open ID（审核白名单）")).toHaveValue("ou_boss\nou_ops")
    expect(card.getByLabelText("启用机器人")).toBeChecked()
    expect(card.getByText("已配置 · ****alue")).toBeInTheDocument()
    expect(card.getByLabelText("App ID")).toHaveValue("")
    expect(card.getByLabelText("App Secret")).toHaveValue("")
    expect(card.getByLabelText("App Secret")).toHaveAttribute("type", "password")
  })

  it("serializes recipients as a string list and preserves the secret on config saves", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredFeishuBot])),
      http.put("/api/integrations/feishu_bot", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredFeishuBot)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    const recipients = card.getByLabelText("接收人 Open ID（审核白名单）")
    await user.clear(recipients)
    await user.type(recipients, "ou_boss, ou_ops\nou_backup，ou_editor")
    await user.click(card.getByLabelText("启用机器人"))
    await user.click(card.getByRole("button", { name: "保存飞书应用配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { whitelist_open_ids: ["ou_boss", "ou_ops", "ou_backup", "ou_editor"], enabled: false },
    }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("配置已保存"))
  })

  it("requires both credentials for explicit replacement and clears them after saving", async () => {
    let requestBody: unknown
    let integration = configuredFeishuBot
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([integration])),
      http.put("/api/integrations/feishu_bot", async ({ request }) => {
        requestBody = await request.json()
        integration = { ...configuredFeishuBot, secret_hint: "已配置 · ****cret" }
        return HttpResponse.json(integration)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    const replace = card.getByRole("button", { name: "替换飞书应用密钥" })
    expect(replace).toBeDisabled()
    await user.type(card.getByLabelText("App ID"), "cli_new")
    expect(replace).toBeDisabled()
    await user.type(card.getByLabelText("App Secret"), "new-secret")
    await user.click(replace)

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { whitelist_open_ids: ["ou_boss", "ou_ops"], enabled: true },
      secret: { app_id: "cli_new", app_secret: "new-secret" },
    }))
    await waitFor(() => expect(card.getByLabelText("App Secret")).toHaveValue(""))
    expect(card.getByLabelText("App ID")).toHaveValue("")
    expect(card.getByText("已配置 · ****cret")).toBeInTheDocument()
  })

  it("sends a test notification with saved recipients even when the bot is disabled", async () => {
    const testRequest = vi.fn()
    const disabled = { ...configuredFeishuBot, public_config: { whitelist_open_ids: ["ou_boss"], enabled: false } }
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([disabled])),
      http.post("/api/integrations/feishu_bot/test", () => {
        testRequest()
        return HttpResponse.json(disabled)
      }),
    )
    renderPage()

    const card = await findCard("飞书应用")
    expect(card.getByLabelText("启用机器人")).not.toBeChecked()
    expect(card.getByText(/向已保存的接收人发送一条测试消息/)).toBeInTheDocument()
    await userEvent.click(card.getByRole("button", { name: "发送飞书测试消息" }))

    await waitFor(() => expect(testRequest).toHaveBeenCalledOnce())
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("测试消息已发送"))
  })

  it("requires configured credentials before enabling test messages", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([])))
    renderPage()

    const card = await findCard("飞书应用")
    expect(card.getByRole("button", { name: "发送飞书测试消息" })).toBeDisabled()
    expect(card.getByText(/设置 App ID 和App Secret 后发送测试消息/)).toBeInTheDocument()
  })

  it("prevents duplicate test messages and shows the pending state", async () => {
    const testRequest = vi.fn()
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredFeishuBot])),
      http.post("/api/integrations/feishu_bot/test", async () => {
        testRequest()
        await delay(150)
        return HttpResponse.json(configuredFeishuBot)
      }),
    )
    renderPage()

    const testButton = await screen.findByRole("button", { name: "发送飞书测试消息" })
    await userEvent.dblClick(testButton)

    expect(testButton).toBeDisabled()
    expect(screen.getByLabelText("处理中")).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("其他操作暂时不可用")
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("测试消息已发送"))
    expect(testRequest).toHaveBeenCalledOnce()
    expect(testButton).toBeEnabled()
  })

  it("disables every card action while another integration is busy", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredRuntime, configuredFeishuBot])),
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

  it.each([
    ["missing permissions", "缺少 im:message:send_as_bot 权限", ["ou_boss"]],
    ["empty recipients", "请先配置通知接收人 Open ID", []],
    ["invalid credentials", "应用凭证无效", ["ou_boss"]],
    ["partial delivery", "部分接收人发送失败", ["ou_boss", "ou_ops"]],
  ])("reports %s without claiming a test message was sent", async (_, message, recipients) => {
    let integration: Integration = {
      ...configuredFeishuBot,
      public_config: { whitelist_open_ids: recipients, enabled: true },
    }
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([integration])),
      http.post("/api/integrations/feishu_bot/test", () => {
        integration = { ...integration, connection_status: "连接失败", last_error: message }
        return HttpResponse.json(integration)
      }),
    )
    renderPage()
    const testButton = await screen.findByRole("button", { name: "发送飞书测试消息" })

    await userEvent.click(testButton)

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message))
    expect(toast.success).not.toHaveBeenCalled()
    expect(await screen.findByRole("alert")).toHaveTextContent(message)
    expect(testButton).toBeEnabled()
  })
})
