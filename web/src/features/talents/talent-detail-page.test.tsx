import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { TalentDetailPage } from "./talent-detail-page"
import type { Talent, TalentInteraction } from "./types"

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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/talents/${talentId}`]}>
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

  it("人才不存在时展示可恢复的错误状态", async () => {
    server.use(http.get("/api/talents/:talentId", () => HttpResponse.json({ code: "TALENT_NOT_FOUND", message: "人才不存在" }, { status: 404 })))

    renderPage()

    expect(await screen.findByText("人才不存在或加载失败。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回人才库" })).toHaveAttribute("href", "/talents")
  })
})
