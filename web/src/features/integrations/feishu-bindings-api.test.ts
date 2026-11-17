import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { fetchFeishuBindings, runFeishuBindingAction, testFeishuBinding } from "./feishu-bindings-api"
import type { FeishuResourceBinding } from "./types"

const binding: FeishuResourceBinding = {
  id: "binding-1",
  resource_type: "bitable",
  purpose: "rss_candidates",
  config: { app_token: "bascn_main", table_id: "tbl_main" },
  enabled: true,
  created_at: "2026-11-10T00:00:00Z",
  updated_at: "2026-11-10T00:00:00Z",
}

describe("feishu bindings api", () => {
  it("accepts a well-formed binding list", async () => {
    server.use(http.get("/api/integrations/feishu_bot/bindings", () => HttpResponse.json([binding])))

    await expect(fetchFeishuBindings()).resolves.toEqual([binding])
  })

  it.each([
    ["config missing table_id", [{ ...binding, config: { app_token: "bascn_main" } }]],
    ["enabled not boolean", [{ ...binding, enabled: "yes" }]],
    ["not an array", { items: [] }],
  ])("rejects a malformed list: %s", async (_, body) => {
    server.use(http.get("/api/integrations/feishu_bot/bindings", () => HttpResponse.json(body)))

    await expect(fetchFeishuBindings()).rejects.toThrow("绑定响应格式无效")
  })

  it("treats a failed probe as data, not an exception", async () => {
    server.use(http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json({
      success: false,
      failed_stage: "fields",
      stages: [{ stage: "fields", success: false, message: "缺少字段「去重键」" }],
      message: null,
    })))

    const result = await testFeishuBinding("binding-1")
    expect(result.success).toBe(false)
    expect(result.failed_stage).toBe("fields")
    expect(result.stages[0]?.message).toBe("缺少字段「去重键」")
  })

  it("rejects a malformed probe response", async () => {
    server.use(http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json({ success: "yes" })))

    await expect(testFeishuBinding("binding-1")).rejects.toThrow("绑定响应格式无效")
  })

  it("posts enable/disable to the dedicated endpoints", async () => {
    const calls: string[] = []
    server.use(
      http.post("/api/integrations/feishu_bot/bindings/binding-1/enable", () => {
        calls.push("enable")
        return HttpResponse.json(binding)
      }),
      http.post("/api/integrations/feishu_bot/bindings/binding-1/disable", () => {
        calls.push("disable")
        return HttpResponse.json({ ...binding, enabled: false })
      }),
    )

    await runFeishuBindingAction({ action: "enable", id: "binding-1" })
    await runFeishuBindingAction({ action: "disable", id: "binding-1" })
    expect(calls).toEqual(["enable", "disable"])
  })
})
