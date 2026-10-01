import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { configuredBaidu, configuredEmbedding, configuredFeishuBot, findCard, latestRun, renderPage } from "./test-helpers"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe("Integration providers", () => {
  beforeEach(() => vi.clearAllMocks())

  it("keeps supported providers and removes publication credentials and bootstrap", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([
      configuredBaidu, configuredEmbedding, configuredFeishuBot,
      { ...configuredEmbedding, provider: "agent-llm", public_config: { provider: "deepseek-official", model: "deepseek-v4-flash" } },
    ])))
    renderPage()
    await findCard("Embedding")
    for (const title of ["飞书应用", "百度翻译", "阿里翻译", "Embedding", "Agent LLM"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument()
    }
    for (const title of ["Notion", "GitHub", "微信", "飞书"]) {
      expect(screen.queryByRole("heading", { name: title })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole("button", { name: "初始化字段" })).not.toBeInTheDocument()
    expect(screen.queryByText("出口 IP")).not.toBeInTheDocument()
  })

  it("requires the embedding endpoint and model before saving", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([])))
    renderPage()
    const card = await findCard("Embedding")
    const save = card.getByRole("button", { name: "保存Embedding配置" })
    expect(save).toBeEnabled()
    await userEvent.clear(card.getByLabelText("模型"))
    expect(save).toBeDisabled()
    expect(card.getByRole("button", { name: "测试Embedding连接" })).toBeDisabled()
    await userEvent.type(card.getByLabelText("模型"), "BAAI/bge-m3")
    expect(save).toBeEnabled()
  })

  it("renders translate and embedding cards with their defaults", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([])))
    renderPage()

    const baidu = await findCard("百度翻译")
    expect(screen.getByRole("heading", { name: "阿里翻译" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "腾讯翻译" })).not.toBeInTheDocument()
    const embedding = await findCard("Embedding")

    expect(baidu.getByLabelText("优先级")).toHaveValue(1)
    expect(baidu.getByLabelText("参与故障切换")).toBeChecked()
    expect(baidu.getByLabelText("AppID")).toHaveValue("")
    expect(embedding.getByLabelText("Base URL")).toHaveValue("https://api.siliconflow.cn")
    expect(embedding.getByLabelText("模型")).toHaveValue("BAAI/bge-m3")
  })

  it("renders the Agent LLM card with defaults and omits an empty optional base_url on save", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([])),
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({
          provider: "agent-llm",
          public_config: { provider: "deepseek-official", model: "deepseek-v4-flash" },
          secret_configured: false,
          secret_hint: null,
          connection_status: "未测试",
          last_tested_at: null,
          last_error: null,
          last_latency_ms: null,
        })
      }),
    )
    renderPage()

    const card = await findCard("Agent LLM")
    expect(card.getByLabelText("Provider")).toHaveValue("deepseek-official")
    expect(card.getByLabelText("模型")).toHaveValue("deepseek-v4-flash")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { provider: "deepseek-official", model: "deepseek-v4-flash", models: [] },
    }))
  })

  it("serializes translate public config with number and boolean types", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([])),
      http.put("/api/integrations/translate_baidu", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({
          provider: "translate_baidu",
          public_config: { priority: 3, enabled: false },
          secret_configured: false,
          secret_hint: null,
          connection_status: "未测试",
          last_tested_at: null,
          last_error: null,
          last_latency_ms: null,
        })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("百度翻译")
    const priority = card.getByLabelText("优先级")
    await user.clear(priority)
    await user.type(priority, "3")
    await user.click(card.getByLabelText("参与故障切换"))
    await user.click(card.getByRole("button", { name: "保存百度翻译配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { priority: 3, enabled: false },
    }))
  })

  it("requires every secret field before replacing translate credentials", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredBaidu])),
      http.put("/api/integrations/translate_baidu", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredBaidu)
      }),
    )
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("百度翻译")
    const replaceButton = card.getByRole("button", { name: "替换百度翻译密钥" })
    expect(replaceButton).toBeDisabled()

    await user.type(card.getByLabelText("AppID"), "baidu-id")
    expect(replaceButton).toBeDisabled()

    await user.type(card.getByLabelText("密钥"), "baidu-key")
    expect(replaceButton).toBeEnabled()
    await user.click(replaceButton)

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { priority: 2, enabled: true },
      secret: { app_id: "baidu-id", app_key: "baidu-key" },
    }))
  })

  it("keeps existing translate secrets when saving config with empty secret inputs", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredBaidu])),
      http.put("/api/integrations/translate_baidu", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredBaidu)
      }),
    )
    renderPage()

    const card = await findCard("百度翻译")
    await userEvent.click(card.getByRole("button", { name: "保存百度翻译配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { priority: 2, enabled: true },
    }))
  })

  it("tests an embedding provider connection", async () => {
    const tests: string[] = []
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredEmbedding])),
      http.post("/api/integrations/embedding/test", () => {
        tests.push("embedding")
        return HttpResponse.json({ ...configuredEmbedding, connection_status: "连接正常", last_latency_ms: 180 })
      }),
    )
    renderPage()

    const card = await findCard("Embedding")
    await userEvent.click(card.getByRole("button", { name: "测试Embedding连接" }))

    await waitFor(() => expect(tests).toEqual(["embedding"]))
    expect(toast.success).toHaveBeenCalledWith("连接测试已完成")
  })

  it("merges typed secrets into save config instead of silently dropping them (#179)", async () => {
    let requestBody: unknown
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredEmbedding])),
      http.put("/api/integrations/embedding", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredEmbedding)
      }),
    )
    renderPage()
    const card = await findCard("Embedding")
    await userEvent.type(card.getByLabelText("API Key"), "sk-embed-new")
    await userEvent.click(card.getByRole("button", { name: "保存Embedding配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: { base_url: "https://api.siliconflow.cn", model: "BAAI/bge-m3" },
      secret: { api_key: "sk-embed-new" },
    }))
    expect(toast.success).toHaveBeenCalledWith("配置与密钥已保存")
  })

  it("updates the card locally when the connection test fails (#179)", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([configuredEmbedding])),
      http.post("/api/integrations/embedding/test", () =>
        HttpResponse.json({ ...configuredEmbedding, connection_status: "连接失败", last_error: "Embedding 端点不可达" })),
    )
    renderPage()

    const card = await findCard("Embedding")
    await userEvent.click(card.getByRole("button", { name: "测试Embedding连接" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Embedding 端点不可达"))
    // 失败状态以 setQueryData 局部写回（GET 恒返回未测试，若触发 refetch 会回退）
    expect(card.getByText("连接失败")).toBeInTheDocument()
    expect(card.getByRole("alert")).toHaveTextContent("Embedding 端点不可达")
  })

  it("shows the last test latency next to the test time", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([configuredBaidu])))
    renderPage()

    const card = await findCard("百度翻译")
    expect(card.getByText(/· 235 ms/)).toBeInTheDocument()
  })

  it("shows daily run health on translate and embedding cards", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([])),
      http.get("/api/rss/runs/latest", () => HttpResponse.json(latestRun)),
    )
    renderPage()

    expect(await screen.findAllByText("最近每日任务：成功")).toHaveLength(3)
  })

  it("lists deduplicated error types when the daily run is degraded", async () => {
    server.use(
      http.get("/api/integrations", () => HttpResponse.json([])),
      http.get("/api/rss/runs/latest", () => HttpResponse.json({
        ...latestRun,
        status: "partial",
        failure_count: 2,
        errors: [
          { stage: "embedding", error_type: "embedding_timeout" },
          { stage: "translate", error_type: "translate_http_429" },
          { stage: "embedding", error_type: "embedding_timeout" },
        ],
      })),
    )
    renderPage()

    expect(await screen.findAllByText("最近每日任务：降级 · embedding_timeout、translate_http_429")).toHaveLength(3)
  })

  it("shows an empty state when no daily run has been recorded", async () => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findAllByText("最近每日任务：暂无运行记录")).toHaveLength(3)
  })

})
