import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { findCard, renderPage } from "./test-helpers"
import type { Integration } from "./types"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const PRO_REF = "deepseek-official/deepseek-v4-pro"
const QWEN_REF = "siliconflow/Qwen/Qwen3-32B"

const configuredAgentLlm: Integration = {
  provider: "agent-llm",
  public_config: {
    provider: "deepseek-official",
    model: "deepseek-v4-flash",
    models: [
      { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: true },
      { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
    ],
  },
  secret_configured: true,
  secret_hint: "已配置 · ****aaaa",
  connection_status: "未测试",
  last_tested_at: null,
  last_error: null,
  last_latency_ms: null,
  model_key_refs: [PRO_REF],
}

function useAgentLlm(integration: Integration = configuredAgentLlm) {
  server.use(http.get("/api/integrations", () => HttpResponse.json([integration])))
}

async function findModelsSection() {
  const card = await findCard("Agent LLM")
  const section = card.getByRole("region", { name: "附加模型列表" })
  return within(section as HTMLElement)
}

describe("Agent LLM 多模型管理", () => {
  beforeEach(() => vi.clearAllMocks())

  it("展示默认模型与附加模型列表（启停与密钥徽标）", async () => {
    useAgentLlm()
    renderPage()

    const section = await findModelsSection()
    expect(section.getByText("deepseek-official/deepseek-v4-flash")).toBeInTheDocument()
    expect(section.getByText("默认")).toBeInTheDocument()
    expect(section.getByText(PRO_REF)).toBeInTheDocument()
    expect(section.getByText("独立密钥")).toBeInTheDocument()
    expect(section.getByText(QWEN_REF)).toBeInTheDocument()
    expect(section.getByText("已停用")).toBeInTheDocument()
    expect(section.getByText("共用默认密钥")).toBeInTheDocument()
    expect(section.getByText("https://api.siliconflow.cn")).toBeInTheDocument()
  })

  it("新增模型随保存配置提交 models[]，独立密钥走 secret.model_keys 且不回显", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: "新增模型" }))
    await userEvent.type(section.getByLabelText("Provider"), "openai")
    await userEvent.type(section.getByLabelText("模型"), "gpt-5-mini")
    await userEvent.type(section.getByLabelText("Base URL（可选）"), "https://api.openai.com")
    await userEvent.type(section.getByLabelText("独立 API Key（可选）"), "sk-openai-should-not-render")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))

    expect(section.getByText("openai/gpt-5-mini")).toBeInTheDocument()
    expect(section.getByText("独立密钥待保存")).toBeInTheDocument()
    expect(section.getByText(/模型列表有未保存的更改/)).toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: true },
          { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
          { provider: "openai", model: "gpt-5-mini", base_url: "https://api.openai.com", enabled: true },
        ],
      },
      secret: { model_keys: { "openai/gpt-5-mini": "sk-openai-should-not-render" } },
    }))
    expect(document.body.textContent).not.toContain("sk-openai-should-not-render")
  })

  it("新增模型校验空字段与重复 ref", async () => {
    useAgentLlm()
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: "新增模型" }))
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))
    expect(section.getByRole("alert")).toHaveTextContent("Provider 和模型不能为空")

    await userEvent.type(section.getByLabelText("Provider"), "deepseek-official")
    await userEvent.type(section.getByLabelText("模型"), "deepseek-v4-pro")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))
    expect(section.getByRole("alert")).toHaveTextContent("已在列表中")

    await userEvent.click(section.getByRole("button", { name: "取消" }))
    expect(section.queryByLabelText("Provider")).not.toBeInTheDocument()
  })

  it("编辑模型并清除独立密钥：保存时 model_keys 携带空串", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `编辑${PRO_REF}` }))
    expect(section.getByLabelText("独立 API Key（可选）")).toHaveValue("")
    await userEvent.click(section.getByLabelText("清除独立密钥（改用默认密钥）"))
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))
    expect(section.getByText("将清除独立密钥")).toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: true },
          { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
        ],
      },
      secret: { model_keys: { [PRO_REF]: "" } },
    }))
  })

  it("停用/启用本地暂存并随保存提交", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `停用${PRO_REF}` }))
    expect(section.getByText(/模型列表有未保存的更改/)).toBeInTheDocument()
    // 停用后该行不再提供「设默认」
    expect(section.queryByRole("button", { name: `把${PRO_REF}设为默认模型` })).not.toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: false },
          { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
        ],
      },
    }))
  })

  it("删除模型需确认，确认后本地移除并随保存提交", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `删除${PRO_REF}` }))
    expect(section.getByText(PRO_REF)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "确认删除模型" }))
    expect(section.queryByText(PRO_REF)).not.toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))

    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
        ],
      },
    }))
  })

  it("行级连接测试展示成功与失败结果", async () => {
    useAgentLlm()
    server.use(
      http.post("/api/integrations/agent-llm/test", async ({ request }) => {
        const body = await request.json() as { model_ref?: string }
        if (body.model_ref === PRO_REF) {
          return HttpResponse.json({ ref: PRO_REF, success: true, message: null, latency_ms: 123, tested_at: "2026-10-01T00:00:00Z" })
        }
        return HttpResponse.json({ ref: QWEN_REF, success: false, message: "Agent LLM 端点不可达（ConnectError）", latency_ms: null, tested_at: "2026-10-01T00:00:00Z" })
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `测试${PRO_REF}连接` }))
    expect(await section.findByText(/连接正常 · 123 ms/)).toBeInTheDocument()

    await userEvent.click(section.getByRole("button", { name: `测试${QWEN_REF}连接` }))
    expect(await section.findByRole("alert")).toHaveTextContent("连接失败：Agent LLM 端点不可达（ConnectError）")
    expect(toast.error).toHaveBeenCalledWith(`${QWEN_REF} 连接测试失败：Agent LLM 端点不可达（ConnectError）`)
  })

  it("设默认即时调用专用端点；有未保存更改时禁用", async () => {
    let requestBody: unknown
    const swapped: Integration = {
      ...configuredAgentLlm,
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-pro",
        models: [{ provider: "deepseek-official", model: "deepseek-v4-flash", enabled: true }],
      },
    }
    useAgentLlm()
    server.use(
      http.post("/api/integrations/agent-llm/default-model", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(swapped)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `把${PRO_REF}设为默认模型` }))
    await waitFor(() => expect(requestBody).toEqual({ ref: PRO_REF }))
    expect(toast.success).toHaveBeenCalledWith(`已把 ${PRO_REF} 设为默认模型`)
    // 刷新后默认行与列表同步
    expect(await section.findByText("deepseek-official/deepseek-v4-pro")).toBeInTheDocument()
  })

  it("未保存更改时「设默认」禁用", async () => {
    useAgentLlm()
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `停用${PRO_REF}` }))
    // 停用 PRO 后「设默认」只对启用行可见；先启用 QWEN 制造 dirty 状态再断言禁用
    await userEvent.click(section.getByRole("button", { name: `启用${QWEN_REF}` }))
    expect(section.getByRole("button", { name: `把${QWEN_REF}设为默认模型` })).toBeDisabled()
  })

  it("暂存模型编辑后点卡片级测试连接，暂存保留且状态局部更新（#179）", async () => {
    useAgentLlm()
    server.use(
      http.post("/api/integrations/agent-llm/test", () => HttpResponse.json({
        ...configuredAgentLlm,
        connection_status: "连接正常",
        last_tested_at: "2026-10-01T00:00:00Z",
        last_latency_ms: 88,
      })),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `停用${PRO_REF}` }))
    expect(section.getByText(/模型列表有未保存的更改/)).toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "测试Agent LLM连接" }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("连接测试已完成"))

    // 缓存局部更新为「连接正常」（GET 恒返回未测试，若触发 refetch 会回退）
    expect(card.getByText("连接正常")).toBeInTheDocument()
    // 暂存未被清空：PRO 行仍为暂存的停用态（服务端副本是启用），dirty 提示仍在
    expect(section.getByText(/模型列表有未保存的更改/)).toBeInTheDocument()
    expect(section.getByRole("button", { name: `启用${PRO_REF}` })).toBeInTheDocument()
  })

  it("暂存期间对未改动行做行级测试，暂存保留（#179）", async () => {
    useAgentLlm()
    server.use(
      http.post("/api/integrations/agent-llm/test", async ({ request }) => {
        const body = await request.json() as { model_ref?: string }
        return HttpResponse.json({ ref: body.model_ref, success: true, message: null, latency_ms: 42, tested_at: "2026-10-01T00:00:00Z" })
      }),
    )
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `停用${PRO_REF}` }))
    await userEvent.click(section.getByRole("button", { name: `测试${QWEN_REF}连接` }))
    expect(await section.findByText(/连接正常 · 42 ms/)).toBeInTheDocument()

    expect(section.getByText(/模型列表有未保存的更改/)).toBeInTheDocument()
    expect(section.getByRole("button", { name: `启用${PRO_REF}` })).toBeInTheDocument()
  })

  it("改 base_url 未保存的行禁用测试、隐藏过期结果并提示保存后可测试（#179）", async () => {
    useAgentLlm()
    server.use(
      http.post("/api/integrations/agent-llm/test", async ({ request }) => {
        const body = await request.json() as { model_ref?: string }
        return HttpResponse.json({ ref: body.model_ref, success: true, message: null, latency_ms: 42, tested_at: "2026-10-01T00:00:00Z" })
      }),
    )
    renderPage()
    const section = await findModelsSection()

    // 先测一次：展示「连接正常」（测的是服务端已保存配置）
    await userEvent.click(section.getByRole("button", { name: `测试${QWEN_REF}连接` }))
    expect(await section.findByText(/连接正常 · 42 ms/)).toBeInTheDocument()

    // 改 base_url 未保存：行级测试若放行会误测旧配置
    await userEvent.click(section.getByRole("button", { name: `编辑${QWEN_REF}` }))
    const baseUrlInput = section.getByLabelText("Base URL（可选）")
    await userEvent.clear(baseUrlInput)
    await userEvent.type(baseUrlInput, "https://invalid.example.com")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))

    const testButton = section.getByRole("button", { name: `测试${QWEN_REF}连接` })
    expect(testButton).toBeDisabled()
    expect(testButton).toHaveAttribute("title", "保存后可测试")
    expect(section.getByText("已暂存更改，保存后可测试")).toBeInTheDocument()
    // 过期测试结果不再展示，避免误导
    expect(section.queryByText(/连接正常/)).not.toBeInTheDocument()
  })

  it("新增未保存的行禁用测试（服务端按已保存条目测试，未保存条目会 404）（#179）", async () => {
    useAgentLlm()
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: "新增模型" }))
    await userEvent.type(section.getByLabelText("Provider"), "openai")
    await userEvent.type(section.getByLabelText("模型"), "gpt-5-mini")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))

    expect(section.getByRole("button", { name: "测试openai/gpt-5-mini连接" })).toBeDisabled()
    expect(section.getByText("已暂存更改，保存后可测试")).toBeInTheDocument()
  })

  it("重命名附加模型时暂存独立密钥随迁新 ref（#179）", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const section = await findModelsSection()

    // QWEN 暂存新独立密钥
    await userEvent.click(section.getByRole("button", { name: `编辑${QWEN_REF}` }))
    await userEvent.type(section.getByLabelText("独立 API Key（可选）"), "sk-qwen-new")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))
    expect(section.getByText("独立密钥待保存")).toBeInTheDocument()

    // 重命名 model：ref 变化，暂存密钥随迁而非静默丢弃
    await userEvent.click(section.getByRole("button", { name: `编辑${QWEN_REF}` }))
    const modelInput = section.getByLabelText("模型")
    await userEvent.clear(modelInput)
    await userEvent.type(modelInput, "Qwen/Qwen3-30B-A3B")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))

    const renamedRef = "siliconflow/Qwen/Qwen3-30B-A3B"
    expect(section.getByText(renamedRef)).toBeInTheDocument()
    expect(section.getByText("独立密钥待保存")).toBeInTheDocument()

    const card = await findCard("Agent LLM")
    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))
    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: true },
          { provider: "siliconflow", model: "Qwen/Qwen3-30B-A3B", base_url: "https://api.siliconflow.cn", enabled: false },
        ],
      },
      secret: { model_keys: { [renamedRef]: "sk-qwen-new" } },
    }))
  })

  it("重命名配有已保存独立密钥的模型时提示密钥将被清除（#179）", async () => {
    useAgentLlm()
    renderPage()
    const section = await findModelsSection()

    await userEvent.click(section.getByRole("button", { name: `编辑${PRO_REF}` }))
    expect(section.queryByText(/重命名后原独立密钥将被清除/)).not.toBeInTheDocument()

    const modelInput = section.getByLabelText("模型")
    await userEvent.clear(modelInput)
    await userEvent.type(modelInput, "deepseek-v4-pro-max")
    expect(section.getByText(/重命名后原独立密钥将被清除/)).toBeInTheDocument()

    // 重新输入新密钥后警告消失
    await userEvent.type(section.getByLabelText("独立 API Key（可选）"), "sk-pro-new")
    expect(section.queryByText(/重命名后原独立密钥将被清除/)).not.toBeInTheDocument()
  })

  it("「保存配置」合并提交已输入的主 API Key 与暂存模型密钥（#179）", async () => {
    let requestBody: unknown
    useAgentLlm()
    server.use(
      http.put("/api/integrations/agent-llm", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(configuredAgentLlm)
      }),
    )
    renderPage()
    const card = await findCard("Agent LLM")
    const section = await findModelsSection()

    await userEvent.type(card.getByLabelText("API Key"), "sk-main-new")
    await userEvent.click(section.getByRole("button", { name: `编辑${PRO_REF}` }))
    await userEvent.type(section.getByLabelText("独立 API Key（可选）"), "sk-pro-new")
    await userEvent.click(section.getByRole("button", { name: "确认模型" }))

    await userEvent.click(card.getByRole("button", { name: "保存Agent LLM配置" }))
    await waitFor(() => expect(requestBody).toEqual({
      public_config: {
        provider: "deepseek-official",
        model: "deepseek-v4-flash",
        models: [
          { provider: "deepseek-official", model: "deepseek-v4-pro", enabled: true },
          { provider: "siliconflow", model: "Qwen/Qwen3-32B", base_url: "https://api.siliconflow.cn", enabled: false },
        ],
      },
      secret: { api_key: "sk-main-new", model_keys: { [PRO_REF]: "sk-pro-new" } },
    }))
    expect(toast.success).toHaveBeenCalledWith("配置与密钥已保存")
  })
})
