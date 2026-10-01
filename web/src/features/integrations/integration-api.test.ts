import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { fetchIntegrations, runIntegrationAction } from "./integration-api"

const integration = {
  public_config: {},
  secret_configured: true,
  secret_hint: "已配置 · ****1234",
  connection_status: "连接正常",
  last_tested_at: null,
  last_error: null,
  last_latency_ms: null,
}

describe("integration response validation", () => {
  it("accepts all supported providers", async () => {
    const providers = ["feishu_bot", "translate_baidu", "translate_aliyun", "embedding", "agent-llm"]
    server.use(http.get("/api/integrations", () => HttpResponse.json(
      providers.map((provider) => ({ ...integration, provider })),
    )))

    expect((await fetchIntegrations()).map((item) => item.provider)).toEqual(providers)
  })

  it.each(["notion", "github", "wechat", "feishu", "translate_tencent", "unknown"])("rejects the unsupported provider %s", async (provider) => {
    server.use(http.get("/api/integrations", () => HttpResponse.json([{ ...integration, provider }])))

    await expect(fetchIntegrations()).rejects.toThrow("集成配置响应格式无效")
  })

  it("does not treat an untested response as successful message delivery", async () => {
    server.use(http.post("/api/integrations/feishu_bot/test", () => HttpResponse.json({
      ...integration,
      provider: "feishu_bot",
      connection_status: "未测试",
    })))

    // 业务失败不抛错：以 ok:false + 最新集成状态返回，由控制器 toast.error 并局部更新缓存（#179）
    const result = await runIntegrationAction({ action: "test", provider: "feishu_bot" })
    expect(result.ok).toBe(false)
    expect(result.message).toBe("测试消息发送失败")
    expect(result.integration?.connection_status).toBe("未测试")
  })
})
