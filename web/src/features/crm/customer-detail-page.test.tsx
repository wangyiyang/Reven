import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { CustomerDetailPage } from "./customer-detail-page"
import type { Contact, Customer, FollowUp } from "./types"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const customerId = "11111111-1111-1111-1111-111111111111"
const customer: Customer = {
  id: customerId,
  name: "星河科技",
  status: "跟进中",
  source: "朋友介绍",
  notes: "关注企业知识库",
  next_action: "发送报价方案",
  next_due_on: "2026-09-01",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}
const contact: Contact = {
  id: "22222222-2222-2222-2222-222222222222",
  customer_id: customerId,
  name: "陈晨",
  role: "创始人",
  phone: "13800000000",
  email: "zhangsan@example.com",
  wechat: "chenchen",
  is_primary: true,
  notes: null,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}
const followUp: FollowUp = {
  id: "33333333-3333-3333-3333-333333333333",
  customer_id: customerId,
  contact_id: contact.id,
  contact_name_snapshot: contact.name,
  kind: "面谈",
  occurred_on: "2026-08-20",
  summary: "确认了知识库一期范围",
  next_action: "发送报价方案",
  next_due_on: "2026-09-01",
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
}

function renderPage(initialEntry = `/crm/customers/${customerId}`) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<CustomerDetailPage />} path="/crm/customers/:customerId" />
          <Route element={<p>CRM 列表</p>} path="/crm" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("CustomerDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(
      http.get("/api/crm/customers/:customerId", () => HttpResponse.json(customer)),
      http.get("/api/crm/customers/:customerId/contacts", () => HttpResponse.json([contact])),
      http.get("/api/crm/customers/:customerId/follow-ups", () => HttpResponse.json([followUp])),
    )
  })

  it("展示客户当前推进、联系人和跟进时间线", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "星河科技" })).toBeInTheDocument()
    expect(screen.getByText("发送报价方案")).toBeInTheDocument()
    expect(await screen.findByRole("article", { name: "陈晨 联系人摘要" })).toBeInTheDocument()
    expect(screen.getByText("主要联系人")).toBeInTheDocument()
    expect(await screen.findByText("确认了知识库一期范围")).toBeInTheDocument()
    expect(screen.getByText("· 陈晨")).toBeInTheDocument()
  })

  it("在窄桌面宽度下为日期、邮箱和主要联系人文案保留完整展示空间", async () => {
    renderPage()

    const contactCard = await screen.findByRole("article", { name: "陈晨 联系人摘要" })
    const sectionsGrid = screen.getByRole("heading", { name: "联系人" }).parentElement?.parentElement?.parentElement
    expect(sectionsGrid).toHaveClass("2xl:grid-cols-2")
    expect(sectionsGrid).not.toHaveClass("xl:grid-cols-2")
    expect(sectionsGrid?.parentElement).toHaveClass("max-w-7xl")

    const occurredOn = screen.getByLabelText("发生日期")
    expect(occurredOn.parentElement?.parentElement).toHaveClass("md:grid-cols-[minmax(0,1fr)_minmax(10rem,1fr)_minmax(0,1fr)]")

    const channels = within(contactCard).getByText(/zhangsan@example\.com/)
    expect(channels).toHaveClass("break-words")
    expect(channels).not.toHaveClass("break-all")
    expect(screen.getByRole("checkbox", { name: "设为主要联系人" }).closest("label")).toHaveClass("whitespace-nowrap")
    expect(within(contactCard).getByText("主要联系人")).toHaveClass("shrink-0", "whitespace-nowrap")
  })

  it("新增主要联系人时提交完整数据并刷新列表", async () => {
    let contacts = [contact]
    let requestBody: unknown
    server.use(
      http.get("/api/crm/customers/:customerId/contacts", () => HttpResponse.json(contacts)),
      http.post("/api/crm/customers/:customerId/contacts", async ({ request }) => {
        requestBody = await request.json()
        const created = { ...contact, id: "44444444-4444-4444-4444-444444444444", name: "林楠" }
        contacts = [{ ...contact, is_primary: false }, created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()
    await userEvent.type(await screen.findByLabelText("姓名"), "林楠")
    await userEvent.type(screen.getByLabelText("邮箱"), "lin@example.com")
    await userEvent.click(screen.getByRole("checkbox", { name: "设为主要联系人" }))
    await userEvent.click(screen.getByRole("button", { name: "添加联系人" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("联系人已添加"))
    expect(requestBody).toEqual({
      name: "林楠",
      role: null,
      phone: null,
      email: "lin@example.com",
      wechat: null,
      is_primary: true,
      notes: null,
    })
    expect(await screen.findByRole("article", { name: "林楠 联系人摘要" })).toBeInTheDocument()
  })

  it("新增跟进直接携带计划字段，不再出现同步开关；编辑历史同样不发送", async () => {
    let followUps = [followUp]
    let createdBody: Record<string, unknown> | null = null
    let updatedBody: Record<string, unknown> | null = null
    server.use(
      http.get("/api/crm/customers/:customerId/follow-ups", () => HttpResponse.json(followUps)),
      http.post("/api/crm/customers/:customerId/follow-ups", async ({ request }) => {
        createdBody = await request.json() as Record<string, unknown>
        const created = { ...followUp, id: "55555555-5555-5555-5555-555555555555", summary: String(createdBody.summary) }
        followUps = [created, ...followUps]
        return HttpResponse.json(created, { status: 201 })
      }),
      http.put("/api/crm/customers/:customerId/follow-ups/:followUpId", async ({ request }) => {
        updatedBody = await request.json() as Record<string, unknown>
        followUps = followUps.map((item) => item.id === followUp.id ? { ...item, summary: String(updatedBody?.summary) } : item)
        return HttpResponse.json(followUps.find((item) => item.id === followUp.id))
      }),
    )

    renderPage()
    // 表单不再出现「同步为当前计划」勾选：最新跟进的计划自动生效
    expect(await screen.findByLabelText("沟通内容")).toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: /同步/ })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("沟通内容"), "客户确认预算")
    await userEvent.type(screen.getByLabelText("约定的下一步"), "准备合同")
    await userEvent.type(screen.getByLabelText("下次跟进日期"), "2026-09-03")
    await userEvent.click(screen.getByRole("button", { name: "记录跟进" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("跟进已记录"))
    expect(createdBody).toMatchObject({
      summary: "客户确认预算",
      next_action: "准备合同",
      next_due_on: "2026-09-03",
    })
    expect(createdBody).not.toHaveProperty("set_as_current")
    expect(createdBody).not.toHaveProperty("next_follow_up_on")

    const historicalCard = screen.getByText("确认了知识库一期范围").closest("article")
    expect(historicalCard).not.toBeNull()
    await userEvent.click(within(historicalCard as HTMLElement).getByRole("button", { name: "编辑" }))
    const summary = screen.getByLabelText("沟通内容")
    await userEvent.clear(summary)
    await userEvent.type(summary, "修正后的历史记录")
    await userEvent.click(screen.getByRole("button", { name: "保存跟进" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("跟进已更新"))
    expect(updatedBody).toMatchObject({ summary: "修正后的历史记录" })
    expect(updatedBody).not.toHaveProperty("set_as_current")
  })

  it("零跟进时展示「记第一条跟进」引导并可唤起跟进表单", async () => {
    server.use(http.get("/api/crm/customers/:customerId/follow-ups", () => HttpResponse.json([])))

    renderPage()
    const guide = await screen.findByRole("button", { name: "记第一条跟进" })
    expect(screen.getByText(/暂无跟进记录。记录第一条跟进/)).toBeInTheDocument()

    await userEvent.click(guide)
    expect(screen.getByLabelText("沟通内容")).toHaveFocus()
  })

  it("删除联系人前需要确认，并保留历史快照提示", async () => {
    let deleted = false
    server.use(http.delete("/api/crm/customers/:customerId/contacts/:contactId", () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }))

    renderPage()
    const contactCard = await screen.findByRole("article", { name: "陈晨 联系人摘要" })
    await userEvent.click(within(contactCard).getByRole("button", { name: "删除" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("历史跟进会保留联系人姓名快照")
    expect(deleted).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))
    await waitFor(() => expect(deleted).toBe(true))
  })

  it("支持编辑联系人，并在确认后删除跟进", async () => {
    let contacts = [contact]
    let followUps = [followUp]
    let updatedContact: Record<string, unknown> | null = null
    let followUpDeleted = false
    server.use(
      http.get("/api/crm/customers/:customerId/contacts", () => HttpResponse.json(contacts)),
      http.get("/api/crm/customers/:customerId/follow-ups", () => HttpResponse.json(followUps)),
      http.put("/api/crm/customers/:customerId/contacts/:contactId", async ({ request }) => {
        updatedContact = await request.json() as Record<string, unknown>
        contacts = [{ ...contact, name: String(updatedContact.name) }]
        return HttpResponse.json(contacts[0])
      }),
      http.delete("/api/crm/customers/:customerId/follow-ups/:followUpId", () => {
        followUpDeleted = true
        followUps = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    const contactCard = await screen.findByRole("article", { name: "陈晨 联系人摘要" })
    await userEvent.click(within(contactCard).getByRole("button", { name: "编辑" }))
    const nameInput = screen.getByLabelText("姓名")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "陈晨（更新）")
    await userEvent.click(screen.getByRole("button", { name: "保存联系人" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("联系人已更新"))
    expect(updatedContact).toMatchObject({ name: "陈晨（更新）", is_primary: true })
    expect(await screen.findByRole("article", { name: "陈晨（更新） 联系人摘要" })).toBeInTheDocument()

    const followUpCard = screen.getByRole("article", { name: "2026-08-20 面谈 跟进记录" })
    await userEvent.click(within(followUpCard).getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("客户当前计划将回退到次新记录")
    await userEvent.click(within(dialog).getByRole("button", { name: "确认删除这条跟进" }))

    await waitFor(() => expect(followUpDeleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("跟进已删除")
    expect(await screen.findByText(/暂无跟进记录。记录第一条跟进/)).toBeInTheDocument()
  })

  it("通过 ?edit=1 直接进入客户档案编辑态", async () => {
    renderPage(`/crm/customers/${customerId}?edit=1`)

    expect(await screen.findByRole("button", { name: "保存修改" })).toBeInTheDocument()
    expect(screen.getByLabelText("客户名称")).toHaveValue("星河科技")
    expect(screen.getByLabelText("客户来源")).toHaveValue("朋友介绍")
  })

  it("保存客户档案后刷新主档案并回到只读", async () => {
    let requestBody: unknown
    server.use(http.put("/api/crm/customers/:customerId", async ({ request }) => {
      requestBody = await request.json()
      return HttpResponse.json({ ...customer, name: "星河科技有限公司" })
    }))

    renderPage(`/crm/customers/${customerId}?edit=1`)
    const nameInput = await screen.findByLabelText("客户名称")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "星河科技有限公司")
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("客户已更新"))
    expect(requestBody).toMatchObject({ name: "星河科技有限公司", status: "跟进中" })
    expect(await screen.findByRole("heading", { name: "星河科技有限公司" })).toBeInTheDocument()
    expect(screen.queryByLabelText("客户名称")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "编辑客户档案" })).toBeInTheDocument()
  })

  it("取消编辑客户档案后回到只读展示", async () => {
    renderPage(`/crm/customers/${customerId}?edit=1`)

    await userEvent.click(await screen.findByRole("button", { name: "取消编辑" }))
    expect(screen.queryByLabelText("客户名称")).not.toBeInTheDocument()
    expect(screen.getAllByText("发送报价方案").length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: "编辑客户档案" })).toBeInTheDocument()
  })

  it("客户不存在时展示可恢复的错误状态", async () => {
    server.use(http.get("/api/crm/customers/:customerId", () => HttpResponse.json({ code: "not_found", message: "客户不存在" }, { status: 404 })))

    renderPage()

    expect(await screen.findByText("客户不存在或加载失败。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回 CRM" })).toHaveAttribute("href", "/crm")
  })
})
