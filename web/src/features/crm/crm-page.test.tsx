import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { CrmPage } from "./crm-page"
import type { Customer } from "./types"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const customer: Customer = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "星河科技",
  status: "跟进中",
  source: "朋友介绍",
  notes: "关注企业知识库",
  next_action: "发送报价方案",
  next_follow_up_on: "2020-01-01",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><CrmPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("CrmPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/crm/customers", () => HttpResponse.json([customer])))
  })

  it("展示客户、关系状态、逾期语义和移动端摘要", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "CRM" })).toBeInTheDocument()
    expect(screen.getByLabelText("备注")).toHaveClass("text-[var(--ink)]", "placeholder:text-[var(--muted)]")
    expect((await screen.findAllByText("星河科技"))[0]).toBeInTheDocument()
    expect(screen.getAllByText("跟进中")[0]).toBeInTheDocument()
    expect(screen.getAllByText(/逾期 · 2020-01-01/)[0]).toBeInTheDocument()
    expect(screen.getByRole("article", { name: "星河科技 客户摘要" })).toBeInTheDocument()
  })

  it("把搜索、状态和跟进计划转换为查询参数", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/crm/customers", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json([customer])
    }))

    renderPage()
    await screen.findByRole("article", { name: "星河科技 客户摘要" })
    await userEvent.type(screen.getByLabelText("搜索"), "星河")
    await userEvent.selectOptions(screen.getByLabelText("关系状态", { selector: "#crm-status-filter" }), "跟进中")
    await userEvent.selectOptions(screen.getByLabelText("跟进计划"), "today")

    await waitFor(() => {
      const latest = requests.at(-1)
      expect(latest?.searchParams.get("query")).toBe("星河")
      expect(latest?.searchParams.get("status")).toBe("跟进中")
      expect(latest?.searchParams.get("due")).toBe("today")
    })
  })

  it("创建客户后刷新列表并清空表单", async () => {
    let requestBody: unknown
    let customers = [customer]
    server.use(
      http.get("/api/crm/customers", () => HttpResponse.json(customers)),
      http.post("/api/crm/customers", async ({ request }) => {
        requestBody = await request.json()
        const created = { ...customer, id: "22222222-2222-2222-2222-222222222222", name: "远山工作室", next_follow_up_on: null }
        customers = [...customers, created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()
    await userEvent.type(await screen.findByLabelText("客户名称"), " 远山工作室 ")
    await userEvent.selectOptions(screen.getByLabelText("关系状态", { selector: "#crm-customer-status" }), "潜在客户")
    await userEvent.type(screen.getByLabelText("客户来源"), "官网")
    await userEvent.click(screen.getByRole("button", { name: "添加客户" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("客户已添加"))
    expect(requestBody).toEqual({
      name: "远山工作室",
      status: "潜在客户",
      source: "官网",
      notes: null,
      next_action: null,
      next_follow_up_on: null,
    })
    expect(screen.getByLabelText("客户名称")).toHaveValue("")
    expect((await screen.findAllByText("远山工作室"))[0]).toBeInTheDocument()
  })

  it("跟进日期缺少下一步行动时不提交", async () => {
    let posted = false
    server.use(http.post("/api/crm/customers", () => {
      posted = true
      return HttpResponse.json(customer, { status: 201 })
    }))

    renderPage()
    await userEvent.type(await screen.findByLabelText("客户名称"), "待验证客户")
    await userEvent.type(screen.getByLabelText("下次跟进日期"), "2026-09-01")
    await userEvent.click(screen.getByRole("button", { name: "添加客户" }))

    expect(toast.error).toHaveBeenCalledWith("设置跟进日期时请填写下一步行动")
    expect(posted).toBe(false)
  })

  it("支持编辑客户，并在确认后删除", async () => {
    let customers = [customer]
    let updatedBody: unknown
    let deleted = false
    server.use(
      http.get("/api/crm/customers", () => HttpResponse.json(customers)),
      http.put("/api/crm/customers/:customerId", async ({ request }) => {
        updatedBody = await request.json()
        customers = [{ ...customer, name: "星河科技有限公司" }]
        return HttpResponse.json(customers[0])
      }),
      http.delete("/api/crm/customers/:customerId", () => {
        deleted = true
        customers = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "编辑 星河科技" }))[0])
    const nameInput = screen.getByLabelText("客户名称")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "星河科技有限公司")
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("客户已更新"))
    expect(updatedBody).toMatchObject({ name: "星河科技有限公司", status: "跟进中" })

    await userEvent.click((await screen.findAllByRole("button", { name: "删除 星河科技有限公司" }))[0])
    const dialog = await screen.findByRole("dialog")
    expect(deleted).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("客户已删除")
    expect(await screen.findByText("暂无匹配客户。")).toBeInTheDocument()
  })

  it("请求失败时展示重试入口且不报告成功", async () => {
    server.use(http.get("/api/crm/customers", () => HttpResponse.json({ code: "failed", message: "暂时不可用" }, { status: 503 })))

    renderPage()

    expect(await screen.findByText("客户列表加载失败。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
  })
})
