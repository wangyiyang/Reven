import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { TalentDetailPage } from "./talent-detail-page"
import type { Talent, TalentEducation, TalentExperience, TalentInteraction } from "./types"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const talentId = "11111111-1111-1111-1111-111111111111"
const talent: Talent = {
  id: talentId,
  name: "林晚",
  organization: "远山工作室",
  tags: ["插画", "品牌设计"],
  phone: "13800001111",
  email: "linwan@example.com",
  wechat: "wx-linwan",
  preferences: ["咖啡", "徒步"],
  capability: "视觉设计",
  engagement_terms: "月结，需签保密协议",
  availability: "每周 20 小时",
  rate_amount: "500.00",
  rate_unit: "按天",
  rating: 4,
  status: "接洽中",
  notes: "老朋友介绍，靠谱",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}
const interaction: TalentInteraction = {
  id: "33333333-3333-3333-3333-333333333333",
  talent_id: talentId,
  occurred_on: "2026-08-20",
  channel: "微信",
  summary: "沟通了品牌视觉报价",
  next_action: "发送作品集",
  next_due_on: "2020-01-01",
  created_at: "2026-08-20T08:00:00Z",
}
const experience: TalentExperience = {
  id: "44444444-4444-4444-4444-444444444444",
  talent_id: talentId,
  company: "远山设计",
  title: "视觉设计师",
  description: "负责品牌视觉体系",
  start_on: "2023-03-01",
  end_on: null,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}
const endedExperience: TalentExperience = {
  id: "55555555-5555-5555-5555-555555555555",
  talent_id: talentId,
  company: "晨光互动",
  title: "设计助理",
  description: null,
  start_on: "2020-01-01",
  end_on: "2021-06-01",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}
const education: TalentEducation = {
  id: "66666666-6666-6666-6666-666666666666",
  talent_id: talentId,
  school: "中央美术学院",
  degree: "本科",
  major: "视觉传达",
  start_on: "2016-09-01",
  end_on: "2020-06-01",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}

function renderPage(entry = `/talents/${talentId}`) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<TalentDetailPage />} path="/talents/:talentId" />
          <Route element={<p>人才列表</p>} path="/talents" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("TalentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(
      http.get("/api/talents/:talentId", () => HttpResponse.json(talent)),
      http.get("/api/talents/:talentId/interactions", () => HttpResponse.json([interaction])),
      http.get("/api/talents/:talentId/experiences", () => HttpResponse.json([experience, endedExperience])),
      http.get("/api/talents/:talentId/educations", () => HttpResponse.json([education])),
      // 编辑态的标签建议走与列表页同 key 的列表查询
      http.get("/api/talents", () => HttpResponse.json([talent])),
    )
  })

  it("展示人才档案摘要与跟进记录，逾期跟进有徽标", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "林晚" })).toBeInTheDocument()
    expect(screen.getByText("远山工作室")).toBeInTheDocument()
    expect(screen.getByText("月结，需签保密协议")).toBeInTheDocument()
    expect(screen.getByText("¥500.00 按天")).toBeInTheDocument()
    expect(screen.getByText("★ 4/5")).toBeInTheDocument()
    expect((await screen.findAllByText("插画"))[0]).toBeInTheDocument()
    const card = await screen.findByRole("article", { name: "2026-08-20 微信 跟进记录" })
    expect(card).toHaveTextContent("沟通了品牌视觉报价")
    expect(card).toHaveTextContent("下一步：发送作品集 · 2020-01-01")
    expect(within(card).getByText("已逾期")).toBeInTheDocument()
  })

  it("展示画像区与履历、院校时间线", async () => {
    renderPage()

    // 画像区：联系方式与喜好
    expect(await screen.findByText("13800001111")).toBeInTheDocument()
    expect(screen.getByText("linwan@example.com")).toBeInTheDocument()
    expect(screen.getByText("wx-linwan")).toBeInTheDocument()
    expect((await screen.findAllByText("咖啡"))[0]).toBeInTheDocument()

    // 履历时间线：至今在前、倒序、精度到月
    const current = await screen.findByRole("article", { name: "远山设计 视觉设计师 履历" })
    expect(current).toHaveTextContent("2023-03 — 至今")
    const ended = screen.getByRole("article", { name: "晨光互动 设计助理 履历" })
    expect(ended).toHaveTextContent("2020-01 — 2021-06")
    const articles = screen.getAllByRole("article")
    expect(articles.indexOf(current)).toBeLessThan(articles.indexOf(ended))

    // 院校时间线：精度到月、学位专业展示
    const educationCard = screen.getByRole("article", { name: "中央美术学院 院校经历" })
    expect(educationCard).toHaveTextContent("2016-09 — 2020-06")
    expect(educationCard).toHaveTextContent("本科 · 视觉传达")
  })

  it("新增履历提交月精度日期并刷新列表", async () => {
    let experiences = [experience, endedExperience]
    let requestBody: unknown
    server.use(
      http.get("/api/talents/:talentId/experiences", () => HttpResponse.json(experiences)),
      http.post("/api/talents/:talentId/experiences", async ({ request }) => {
        requestBody = await request.json()
        const created: TalentExperience = {
          ...experience,
          id: "77777777-7777-7777-7777-777777777777",
          company: "自由职业",
          title: "独立设计师",
          description: null,
          start_on: "2024-05-01",
          end_on: null,
        }
        experiences = [created, ...experiences]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()
    await screen.findByRole("article", { name: "远山设计 视觉设计师 履历" })
    await userEvent.type(screen.getByLabelText("公司"), "自由职业")
    await userEvent.type(screen.getByLabelText("职务"), "独立设计师")
    // 录入任意日，序列化层强制落为该月 1 日
    await userEvent.type(screen.getByLabelText("开始月份"), "2024-05-20")
    await userEvent.click(screen.getByRole("button", { name: "添加履历" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("履历已添加"))
    expect(requestBody).toMatchObject({
      company: "自由职业",
      title: "独立设计师",
      description: null,
      start_on: "2024-05-01",
      end_on: null,
    })
    expect((await screen.findAllByText("自由职业"))[0]).toBeInTheDocument()
  })

  it("编辑履历走嵌套路由 PUT", async () => {
    let experiences = [experience, endedExperience]
    let updatedBody: Record<string, unknown> | null = null
    let putPath = ""
    server.use(
      http.get("/api/talents/:talentId/experiences", () => HttpResponse.json(experiences)),
      http.put("/api/talents/:talentId/experiences/:experienceId", async ({ params, request }) => {
        putPath = new URL(request.url).pathname
        updatedBody = await request.json() as Record<string, unknown>
        experiences = experiences.map((item) =>
          item.id === params.experienceId ? { ...item, title: String(updatedBody?.title) } : item
        )
        return HttpResponse.json(experiences.find((item) => item.id === params.experienceId))
      }),
    )

    renderPage()
    const card = await screen.findByRole("article", { name: "远山设计 视觉设计师 履历" })
    await userEvent.click(within(card).getByRole("button", { name: "编辑" }))
    const title = screen.getByLabelText("职务")
    await userEvent.clear(title)
    await userEvent.type(title, "设计总监")
    await userEvent.click(screen.getByRole("button", { name: "保存履历" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("履历已更新"))
    expect(putPath).toBe(`/api/talents/${talentId}/experiences/${experience.id}`)
    expect(updatedBody).toMatchObject({ company: "远山设计", title: "设计总监", start_on: "2023-03-01", end_on: null })
  })

  it("删除院校经历前需要确认", async () => {
    let educations = [education]
    let deleted = false
    server.use(
      http.get("/api/talents/:talentId/educations", () => HttpResponse.json(educations)),
      http.delete("/api/talents/:talentId/educations/:educationId", () => {
        deleted = true
        educations = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    const card = await screen.findByRole("article", { name: "中央美术学院 院校经历" })
    await userEvent.click(within(card).getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("人才档案不受影响")
    expect(deleted).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: "确认删除这条院校经历" }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("院校经历已删除")
    expect(await screen.findByText("暂无院校经历，在上方录入一段教育经历完善画像。")).toBeInTheDocument()
  })

  it("新增跟随后提交完整数据并刷新列表", async () => {
    let interactions = [interaction]
    let requestBody: unknown
    server.use(
      http.get("/api/talents/:talentId/interactions", () => HttpResponse.json(interactions)),
      http.post("/api/talents/:talentId/interactions", async ({ request }) => {
        requestBody = await request.json()
        const created = { ...interaction, id: "55555555-5555-5555-5555-555555555555", summary: "确认了下期排期", next_due_on: null }
        interactions = [created, ...interactions]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()
    await userEvent.type(await screen.findByLabelText("沟通内容"), "确认了下期排期")
    await userEvent.click(screen.getByRole("button", { name: "记录跟进" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("跟进已记录"))
    expect(requestBody).toMatchObject({
      channel: "微信",
      summary: "确认了下期排期",
      next_action: null,
      next_due_on: null,
    })
    expect((await screen.findAllByText("确认了下期排期"))[0]).toBeInTheDocument()
  })

  it("编辑跟进走扁平路由 PATCH", async () => {
    let interactions = [interaction]
    let updatedBody: Record<string, unknown> | null = null
    server.use(
      http.get("/api/talents/:talentId/interactions", () => HttpResponse.json(interactions)),
      http.patch("/api/talents/interactions/:interactionId", async ({ request }) => {
        updatedBody = await request.json() as Record<string, unknown>
        interactions = interactions.map((item) => ({ ...item, summary: String(updatedBody?.summary) }))
        return HttpResponse.json(interactions[0])
      }),
    )

    renderPage()
    const card = await screen.findByRole("article", { name: "2026-08-20 微信 跟进记录" })
    await userEvent.click(within(card).getByRole("button", { name: "编辑" }))
    const summary = screen.getByLabelText("沟通内容")
    await userEvent.clear(summary)
    await userEvent.type(summary, "修正后的跟进内容")
    await userEvent.click(screen.getByRole("button", { name: "保存跟进" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("跟进已更新"))
    expect(updatedBody).toMatchObject({ summary: "修正后的跟进内容", channel: "微信", occurred_on: "2026-08-20" })
  })

  it("删除跟进前需要确认", async () => {
    let interactions = [interaction]
    let deleted = false
    server.use(
      http.get("/api/talents/:talentId/interactions", () => HttpResponse.json(interactions)),
      http.delete("/api/talents/interactions/:interactionId", () => {
        deleted = true
        interactions = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    const card = await screen.findByRole("article", { name: "2026-08-20 微信 跟进记录" })
    await userEvent.click(within(card).getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("人才档案不受影响")
    expect(deleted).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: "确认删除这条跟进" }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("跟进已删除")
    expect(await screen.findByText("暂无跟进记录。")).toBeInTheDocument()
  })

  it("编辑人才档案：保存成功后回只读态并展示更新数据", async () => {
    let current = talent
    let updatedBody: unknown
    server.use(
      http.get("/api/talents/:talentId", () => HttpResponse.json(current)),
      http.patch("/api/talents/:talentId", async ({ request }) => {
        updatedBody = await request.json()
        current = { ...talent, name: "林晚（更新）" }
        return HttpResponse.json(current)
      }),
    )

    renderPage()
    await screen.findByRole("heading", { name: "林晚" })
    await userEvent.click(screen.getByRole("button", { name: "编辑人才档案" }))
    const nameInput = screen.getByLabelText("姓名")
    expect(nameInput).toHaveValue("林晚")
    expect(screen.getByLabelText("费率金额")).toHaveValue(500)
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "林晚（更新）")
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("人才已更新"))
    expect(updatedBody).toMatchObject({
      name: "林晚（更新）",
      status: "接洽中",
      phone: "13800001111",
      email: "linwan@example.com",
      wechat: "wx-linwan",
      preferences: ["咖啡", "徒步"],
      rate_amount: "500.00",
      rate_unit: "按天",
      rating: 4,
    })
    expect(screen.queryByLabelText("姓名")).not.toBeInTheDocument()
    expect(await screen.findByRole("heading", { name: "林晚（更新）" })).toBeInTheDocument()
  })

  it("编辑校验失败时保留表单且不发送请求", async () => {
    let patched = false
    server.use(http.patch("/api/talents/:talentId", () => {
      patched = true
      return HttpResponse.json(talent)
    }))

    renderPage()
    await screen.findByRole("heading", { name: "林晚" })
    await userEvent.click(screen.getByRole("button", { name: "编辑人才档案" }))
    const rateInput = screen.getByLabelText("费率金额")
    expect(rateInput).toHaveValue(500)
    await userEvent.clear(rateInput)
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    expect(toast.error).toHaveBeenCalledWith("费率金额与单位需同时填写或同时留空")
    expect(patched).toBe(false)
    expect(screen.getByLabelText("姓名")).toHaveValue("林晚")
    expect(rateInput).toHaveValue(null)
  })

  it("带 ?edit=1 进入时自动进入编辑态", async () => {
    renderPage(`/talents/${talentId}?edit=1`)

    expect(await screen.findByLabelText("姓名")).toHaveValue("林晚")
    expect(screen.getByRole("button", { name: "保存修改" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "取消编辑" })).toBeInTheDocument()
  })

  it("人才不存在时展示可恢复的错误状态", async () => {
    server.use(http.get("/api/talents/:talentId", () => HttpResponse.json({ code: "TALENT_NOT_FOUND", message: "人才不存在" }, { status: 404 })))

    renderPage()

    expect(await screen.findByText("人才不存在或加载失败。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回人才库" })).toHaveAttribute("href", "/talents")
  })
})
