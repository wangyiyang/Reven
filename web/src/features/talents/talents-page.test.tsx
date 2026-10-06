import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { TalentsPage } from "./talents-page"
import type { Talent } from "./types"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const talent: Talent = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "林晚",
  organization: "远山工作室",
  tags: ["插画", "品牌设计"],
  phone: "13800001111",
  email: "linwan@example.com",
  wechat: "wx-linwan",
  preferences: ["咖啡", "徒步"],
  capability: "视觉设计",
  engagement_terms: null,
  availability: "每周 20 小时",
  rate_amount: "500.00",
  rate_unit: "按天",
  rating: 4,
  status: "接洽中",
  notes: null,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><TalentsPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("TalentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/talents", () => HttpResponse.json([talent])))
  })

  it("展示人才、状态、标签、费率与评分", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "人才库" })).toBeInTheDocument()
    expect((await screen.findAllByText("林晚"))[0]).toBeInTheDocument()
    expect(screen.getAllByText("接洽中")[0]).toBeInTheDocument()
    expect(screen.getAllByText("插画")[0]).toBeInTheDocument()
    expect(screen.getAllByText("¥500.00 按天")[0]).toBeInTheDocument()
    expect(screen.getAllByText("★ 4/5")[0]).toBeInTheDocument()
    expect(screen.getByRole("article", { name: "林晚 人才摘要" })).toBeInTheDocument()
    // 列表页不再常驻表单，新建走抽屉
    expect(screen.queryByLabelText("姓名")).not.toBeInTheDocument()
  })

  it("把搜索、状态、到期和标签转换为查询参数", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/talents", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json([talent])
    }))

    renderPage()
    await screen.findByRole("article", { name: "林晚 人才摘要" })
    await userEvent.type(screen.getByLabelText("搜索"), "林晚")
    await userEvent.selectOptions(screen.getByLabelText("状态", { selector: "#talents-status-filter" }), "接洽中")
    await userEvent.selectOptions(screen.getByLabelText("跟进到期"), "overdue")
    await userEvent.type(screen.getByLabelText("标签筛选"), "插画")

    await waitFor(() => {
      const latest = requests.at(-1)
      expect(latest?.searchParams.get("q")).toBe("林晚")
      expect(latest?.searchParams.get("status")).toBe("接洽中")
      expect(latest?.searchParams.get("due")).toBe("overdue")
      expect(latest?.searchParams.get("tag")).toBe("插画")
    })
    expect(screen.getAllByText("已逾期")[0]).toBeInTheDocument()
  })

  it("空态时展示空态文案且不渲染摘要卡片", async () => {
    server.use(http.get("/api/talents", () => HttpResponse.json([])))

    renderPage()

    // 移动/桌面双视口各渲染一份空态（结构由 ResponsiveList 单测覆盖）
    expect(await screen.findAllByText("暂无匹配人才。")).toHaveLength(2)
    expect(screen.queryAllByRole("article")).toHaveLength(0)
  })

  it("新建人才走抽屉，提交标签、费率与评分并刷新列表", async () => {
    let requestBody: unknown
    let talents = [talent]
    server.use(
      http.get("/api/talents", () => HttpResponse.json(talents)),
      http.post("/api/talents", async ({ request }) => {
        requestBody = await request.json()
        const created: Talent = { ...talent, id: "22222222-2222-2222-2222-222222222222", name: "周航", rate_amount: "800", rate_unit: "按小时" }
        talents = [...talents, created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()
    await screen.findByRole("article", { name: "林晚 人才摘要" })
    await userEvent.click(screen.getByRole("button", { name: "新建人才" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("新建人才")
    await userEvent.type(within(dialog).getByLabelText("姓名"), " 周航 ")
    await userEvent.type(within(dialog).getByLabelText("机构"), "独立顾问")
    await userEvent.type(within(dialog).getByLabelText("标签"), "前端")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加标签" }))
    await userEvent.type(within(dialog).getByLabelText("费率金额"), "800")
    await userEvent.selectOptions(within(dialog).getByLabelText("费率单位"), "按小时")
    await userEvent.selectOptions(within(dialog).getByLabelText("评分"), "5")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加人才" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("人才已添加"))
    expect(requestBody).toEqual({
      name: "周航",
      organization: "独立顾问",
      tags: ["前端"],
      phone: null,
      email: null,
      wechat: null,
      preferences: [],
      capability: null,
      engagement_terms: null,
      availability: null,
      rate_amount: "800",
      rate_unit: "按小时",
      rating: 5,
      status: "候选",
      notes: null,
    })
    // 保存成功后关闭抽屉、停留列表页并刷新列表
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect((await screen.findAllByText("周航"))[0]).toBeInTheDocument()
  })

  it("客户端验证失败时保留已确认标签和表单字段", async () => {
    let posted = false
    server.use(http.post("/api/talents", () => {
      posted = true
      return HttpResponse.json(talent, { status: 201 })
    }))

    renderPage()
    await userEvent.click(screen.getByRole("button", { name: "新建人才" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(within(dialog).getByLabelText("姓名"), "待验证人才")
    await userEvent.type(within(dialog).getByLabelText("标签"), "插画")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加标签" }))
    await userEvent.type(within(dialog).getByLabelText("费率金额"), "500")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加人才" }))

    expect(toast.error).toHaveBeenCalledWith("费率金额与单位需同时填写或同时留空")
    expect(posted).toBe(false)
    expect(within(dialog).getByLabelText("姓名")).toHaveValue("待验证人才")
    expect(within(dialog).getByRole("button", { name: "移除标签 插画" })).toBeInTheDocument()
    expect(within(dialog).getByLabelText("费率金额")).toHaveValue(500)
  })

  it("确认后删除人才并刷新列表", async () => {
    let talents = [talent]
    let deleted = false
    server.use(
      http.get("/api/talents", () => HttpResponse.json(talents)),
      http.delete("/api/talents/:talentId", () => {
        deleted = true
        talents = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "删除 林晚" }))[0])
    const dialog = await screen.findByRole("dialog")
    expect(deleted).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("人才已删除")
    expect(await screen.findAllByText("暂无匹配人才。")).toHaveLength(2)
  })

  it("请求失败时展示重试入口且不报告成功", async () => {
    server.use(http.get("/api/talents", () => HttpResponse.json({ code: "failed", message: "暂时不可用" }, { status: 503 })))

    renderPage()

    expect(await screen.findByText("人才列表加载失败。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
  })
})
