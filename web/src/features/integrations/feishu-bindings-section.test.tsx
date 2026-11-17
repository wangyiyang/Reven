import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { configuredFeishuBot, findCard, renderPage } from "./test-helpers"
import type { FeishuResourceBinding, Integration } from "./types"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const bindingEnabled: FeishuResourceBinding = {
  id: "binding-1",
  resource_type: "bitable",
  purpose: "rss_candidates",
  config: { app_token: "bascn_main", table_id: "tbl_main" },
  enabled: true,
  created_at: "2026-11-10T00:00:00Z",
  updated_at: "2026-11-10T00:00:00Z",
}

const bindingDisabled: FeishuResourceBinding = {
  ...bindingEnabled,
  id: "binding-2",
  enabled: false,
  config: { app_token: "bascn_backup", table_id: "tbl_backup" },
}

const PROBE_SUCCESS = {
  success: true,
  failed_stage: null,
  stages: [
    { stage: "fields", success: true, message: null },
    { stage: "search", success: true, message: null },
    { stage: "create", success: true, message: null },
    { stage: "delete", success: true, message: null },
  ],
  message: null,
}

function useBindings(bindings: FeishuResourceBinding[]) {
  server.use(http.get("/api/integrations/feishu_bot/bindings", () => HttpResponse.json(bindings)))
}

function useFeishuBot(integration: Integration = configuredFeishuBot) {
  server.use(http.get("/api/integrations", () => HttpResponse.json([integration])))
}

async function findBindingsSection() {
  const card = await findCard("飞书应用")
  const section = card.getByRole("region", { name: "多维表格绑定" })
  // 绑定列表是独立查询：等加载文案消失（查询落定）后再让用例同步断言行内容
  await waitFor(() => expect(within(section).queryByText("正在读取绑定列表…")).not.toBeInTheDocument())
  return within(section)
}

describe("Feishu bitable bindings section", () => {
  beforeEach(() => vi.clearAllMocks())

  it("renders bindings with app token, table id and status badges", async () => {
    useFeishuBot()
    useBindings([bindingEnabled, bindingDisabled])
    renderPage()

    const section = await findBindingsSection()
    expect(section.getByText(/bascn_main/)).toBeInTheDocument()
    expect(section.getByText(/tbl_main/)).toBeInTheDocument()
    expect(section.getByText(/bascn_backup/)).toBeInTheDocument()
    expect(section.getByText("已启用")).toBeInTheDocument()
    expect(section.getByText("已停用")).toBeInTheDocument()
  })

  it("shows an empty state when no binding exists", async () => {
    useFeishuBot()
    renderPage()

    const section = await findBindingsSection()
    expect(section.getByText("尚未配置绑定。")).toBeInTheDocument()
  })

  it("creates a binding through the drawer with the fixed resource/purpose pair", async () => {
    let requestBody: unknown
    const created: FeishuResourceBinding = {
      ...bindingDisabled,
      id: "binding-new",
      config: { app_token: "bascn_new", table_id: "tbl_new" },
      enabled: true,
    }
    let bindings: FeishuResourceBinding[] = []
    server.use(
      http.get("/api/integrations/feishu_bot/bindings", () => HttpResponse.json(bindings)),
      http.post("/api/integrations/feishu_bot/bindings", async ({ request }) => {
        requestBody = await request.json()
        bindings = [created]
        return HttpResponse.json(created)
      }),
    )
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    await user.click(card.getByRole("button", { name: "新增多维表格绑定" }))
    const drawer = screen.getByRole("dialog")
    await user.type(within(drawer).getByLabelText("应用 App Token"), " bascn_new ")
    await user.type(within(drawer).getByLabelText("数据表 Table ID"), "tbl_new")
    await user.click(within(drawer).getByLabelText(/创建后立即启用/))
    await user.click(within(drawer).getByRole("button", { name: "创建绑定" }))

    await waitFor(() => expect(requestBody).toEqual({
      resource_type: "bitable",
      purpose: "rss_candidates",
      config: { app_token: "bascn_new", table_id: "tbl_new" },
      enabled: true,
    }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已创建"))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    // 失效后重取列表，渲染新绑定
    expect(await card.findByText(/bascn_new/)).toBeInTheDocument()
  })

  it("edits only the binding config and keeps enable state on the list actions", async () => {
    let requestBody: unknown
    let requestPath = ""
    useBindings([bindingEnabled])
    server.use(http.put("/api/integrations/feishu_bot/bindings/:id", async ({ request, params }) => {
      requestBody = await request.json()
      requestPath = String(params.id)
      return HttpResponse.json({ ...bindingEnabled, config: { app_token: "bascn_main", table_id: "tbl_renamed" } })
    }))
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const section = await findBindingsSection()
    await user.click(section.getByRole("button", { name: "编辑绑定 bascn_main" }))
    const drawer = screen.getByRole("dialog")
    expect(within(drawer).getByLabelText("应用 App Token")).toHaveValue("bascn_main")
    expect(within(drawer).getByLabelText("数据表 Table ID")).toHaveValue("tbl_main")
    // 编辑态不渲染启用勾选：启停走 enable/disable 独立端点
    expect(within(drawer).queryByLabelText(/创建后立即启用/)).not.toBeInTheDocument()
    await user.clear(within(drawer).getByLabelText("数据表 Table ID"))
    await user.type(within(drawer).getByLabelText("数据表 Table ID"), "tbl_renamed")
    await user.click(within(drawer).getByRole("button", { name: "保存绑定" }))

    await waitFor(() => expect(requestBody).toEqual({ config: { app_token: "bascn_main", table_id: "tbl_renamed" } }))
    expect(requestPath).toBe("binding-1")
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已更新"))
  })

  it("disables an enabled binding and enables a disabled one", async () => {
    const calls: string[] = []
    useBindings([bindingEnabled, bindingDisabled])
    server.use(
      http.post("/api/integrations/feishu_bot/bindings/binding-1/disable", () => {
        calls.push("disable")
        return HttpResponse.json({ ...bindingEnabled, enabled: false })
      }),
      http.post("/api/integrations/feishu_bot/bindings/binding-2/enable", () => {
        calls.push("enable")
        return HttpResponse.json({ ...bindingDisabled, enabled: true })
      }),
    )
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const section = await findBindingsSection()
    await user.click(section.getByRole("button", { name: "停用绑定 bascn_main" }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已停用"))
    await user.click(section.getByRole("button", { name: "启用绑定 bascn_backup" }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已启用"))
    expect(calls).toEqual(["disable", "enable"])
  })

  it("requires confirmation before deleting a binding", async () => {
    const deleteRequest = vi.fn()
    useBindings([bindingEnabled])
    server.use(http.delete("/api/integrations/feishu_bot/bindings/binding-1", () => {
      deleteRequest()
      return new HttpResponse(null, { status: 204 })
    }))
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const section = await findBindingsSection()
    await user.click(section.getByRole("button", { name: "删除绑定 bascn_main" }))
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText(/RSS 候选将不再写入该多维表格/)).toBeInTheDocument()
    expect(deleteRequest).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole("button", { name: "确认删除绑定" }))
    await waitFor(() => expect(deleteRequest).toHaveBeenCalledOnce())
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已删除"))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("shows a passed probe with all stages acknowledged", async () => {
    useBindings([bindingEnabled])
    server.use(http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json(PROBE_SUCCESS)))
    useFeishuBot()
    renderPage()

    const section = await findBindingsSection()
    await userEvent.click(section.getByRole("button", { name: "测试绑定 bascn_main" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定测试通过"))
    expect(await section.findByText(/测试通过：字段校验、只读查询、写入与删除测试记录均成功/)).toBeInTheDocument()
  })

  it("shows the failed stage with its message when the probe fails", async () => {
    useBindings([bindingEnabled])
    server.use(http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json({
      success: false,
      failed_stage: "create",
      stages: [
        { stage: "fields", success: true, message: null },
        { stage: "search", success: true, message: null },
        { stage: "create", success: false, message: "应用未被添加为该表协作者" },
      ],
      message: null,
    })))
    useFeishuBot()
    renderPage()

    const section = await findBindingsSection()
    await userEvent.click(section.getByRole("button", { name: "测试绑定 bascn_main" }))

    const alert = await section.findByRole("alert")
    expect(alert).toHaveTextContent("测试未通过：写入测试记录阶段失败")
    expect(alert).toHaveTextContent("字段校验")
    expect(alert).toHaveTextContent("只读查询")
    expect(alert).toHaveTextContent("写入测试记录：应用未被添加为该表协作者")
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("绑定测试未通过，详见绑定列表中的分阶段结果"))
  })

  it("shows the probe message when credentials are unavailable before any stage runs", async () => {
    useBindings([bindingEnabled])
    server.use(http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json({
      success: false,
      failed_stage: null,
      stages: [],
      message: "飞书应用机器人未启用或凭证不可用",
    })))
    useFeishuBot()
    renderPage()

    const section = await findBindingsSection()
    await userEvent.click(section.getByRole("button", { name: "测试绑定 bascn_main" }))

    const alert = await section.findByRole("alert")
    expect(alert).toHaveTextContent("测试未通过")
    expect(alert).toHaveTextContent("飞书应用机器人未启用或凭证不可用")
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("飞书应用机器人未启用或凭证不可用"))
  })

  it("clears a stale test result after the binding config is updated", async () => {
    useBindings([bindingEnabled])
    server.use(
      http.post("/api/integrations/feishu_bot/bindings/binding-1/test", () => HttpResponse.json(PROBE_SUCCESS)),
      http.put("/api/integrations/feishu_bot/bindings/binding-1", () => HttpResponse.json(bindingEnabled)),
    )
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const section = await findBindingsSection()
    await user.click(section.getByRole("button", { name: "测试绑定 bascn_main" }))
    expect(await section.findByText(/测试通过/)).toBeInTheDocument()

    await user.click(section.getByRole("button", { name: "编辑绑定 bascn_main" }))
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "保存绑定" }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已更新"))
    await waitFor(() => expect(section.queryByText(/测试通过：字段校验/)).not.toBeInTheDocument())
  })

  it.each([
    ["bot disabled", { ...configuredFeishuBot, public_config: { whitelist_open_ids: ["ou_boss"], enabled: false } }],
    ["secret missing", { ...configuredFeishuBot, secret_configured: false, secret_hint: null }],
    ["integration absent", undefined],
  ])("disables creation with a hint when %s", async (_, integration) => {
    server.use(http.get("/api/integrations", () => HttpResponse.json(integration ? [integration] : [])))
    renderPage()

    const card = await findCard("飞书应用")
    expect(card.getByRole("button", { name: "新增多维表格绑定" })).toBeDisabled()
    expect(card.getByText(/需先在上方保存 App ID \/ App Secret 并勾选「启用机器人」/)).toBeInTheDocument()
  })

  it("keeps the drawer open and surfaces the backend conflict message on 409", async () => {
    server.use(http.post("/api/integrations/feishu_bot/bindings", () => HttpResponse.json(
      { code: "BINDING_PURPOSE_CONFLICT", message: "用途 rss_candidates 已存在启用的绑定，请先禁用其他绑定" },
      { status: 409 },
    )))
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    await user.click(card.getByRole("button", { name: "新增多维表格绑定" }))
    const drawer = screen.getByRole("dialog")
    await user.type(within(drawer).getByLabelText("应用 App Token"), "bascn_conflict")
    await user.type(within(drawer).getByLabelText("数据表 Table ID"), "tbl_conflict")
    await user.click(within(drawer).getByLabelText(/创建后立即启用/))
    await user.click(within(drawer).getByRole("button", { name: "创建绑定" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("用途 rss_candidates 已存在启用的绑定，请先禁用其他绑定"))
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })

  it("surfaces backend validation messages from 422 responses", async () => {
    server.use(http.post("/api/integrations/feishu_bot/bindings", () => HttpResponse.json(
      { detail: [{ loc: ["body", "config", "app_token"], msg: "String should match pattern '^\\S+$'", type: "string_pattern_mismatch" }] },
      { status: 422 },
    )))
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    await user.click(card.getByRole("button", { name: "新增多维表格绑定" }))
    const drawer = screen.getByRole("dialog")
    await user.type(within(drawer).getByLabelText("应用 App Token"), "bascn bad")
    await user.type(within(drawer).getByLabelText("数据表 Table ID"), "tbl_ok")
    await user.click(within(drawer).getByRole("button", { name: "创建绑定" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("String should match pattern '^\\S+$'"))
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })

  it("blocks duplicate submissions while a binding action is in flight", async () => {
    const createRequest = vi.fn()
    useBindings([])
    server.use(http.post("/api/integrations/feishu_bot/bindings", async () => {
      createRequest()
      await delay(120)
      return HttpResponse.json(bindingDisabled)
    }))
    useFeishuBot()
    const user = userEvent.setup()
    renderPage()

    const card = await findCard("飞书应用")
    await user.click(card.getByRole("button", { name: "新增多维表格绑定" }))
    const drawer = screen.getByRole("dialog")
    await user.type(within(drawer).getByLabelText("应用 App Token"), "bascn_new")
    await user.type(within(drawer).getByLabelText("数据表 Table ID"), "tbl_new")
    const submit = within(drawer).getByRole("button", { name: "创建绑定" })
    await user.dblClick(submit)

    expect(submit).toBeDisabled()
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("绑定已创建"))
    expect(createRequest).toHaveBeenCalledOnce()
  })
})
