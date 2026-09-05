import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"

import { server } from "@/test/server"

import { EntryFormDrawer } from "./entry-form-drawer"
import type { FinanceEntry } from "./finance-api"
import { todayShanghai, type EntryFormVariant } from "./finance-utils"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const createdEntry: FinanceEntry = {
  id: "11111111-1111-1111-1111-111111111111",
  kind: "income",
  name: "咨询收入",
  amount_cents: 500000,
  category: "服务",
  occurred_on: "2026-09-10",
  due_on: null,
  recurrence: null,
  source: null,
  status: "已收",
  notes: null,
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:00Z",
}

function renderDrawer(props: { variant: EntryFormVariant; entry?: FinanceEntry; onClose?: () => void }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EntryFormDrawer onClose={props.onClose ?? (() => {})} open variant={props.variant} entry={props.entry} />
    </QueryClientProvider>,
  )
}

describe("EntryFormDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.post("/api/finance/entries", () => HttpResponse.json(createdEntry, { status: 201 })))
  })

  it("settled 入口渲染实际收付日期与分类，pending 入口渲染收付款对象、预计收付日期与备注", () => {
    const { unmount } = renderDrawer({ variant: "income-settled" })
    expect(screen.getByLabelText("实际收付日期")).toBeInTheDocument()
    expect(screen.getByLabelText("分类（可选）")).toBeInTheDocument()
    expect(screen.queryByLabelText("收付款对象")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("预计收付日期")).not.toBeInTheDocument()
    unmount()

    renderDrawer({ variant: "receivable" })
    expect(screen.getByLabelText("收付款对象")).toBeInTheDocument()
    expect(screen.getByLabelText("预计收付日期")).toBeInTheDocument()
    expect(screen.getByLabelText("备注（可选）")).toBeInTheDocument()
    expect(screen.queryByLabelText("实际收付日期")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("分类（可选）")).not.toBeInTheDocument()
  })

  it.each([
    { variant: "income-settled" as const, kind: "income", status: "已收", submitLabel: "记收入" },
    { variant: "expense-settled" as const, kind: "expense", status: "已付", submitLabel: "记支出" },
  ])("$submitLabel 提交固定的 kind/status 映射", async ({ variant, kind, status, submitLabel }) => {
    let requestBody: unknown
    server.use(http.post("/api/finance/entries", async ({ request }) => {
      requestBody = await request.json()
      return HttpResponse.json(createdEntry, { status: 201 })
    }))

    renderDrawer({ variant })
    await userEvent.type(screen.getByLabelText("名称"), "咨询收入")
    await userEvent.type(screen.getByLabelText("金额"), "5000")
    fireEvent.change(screen.getByLabelText("实际收付日期"), { target: { value: "2026-09-10" } })
    await userEvent.type(screen.getByLabelText("分类（可选）"), "服务")
    await userEvent.click(screen.getByRole("button", { name: submitLabel }))

    await waitFor(() => expect(requestBody).toEqual({
      kind,
      status,
      name: "咨询收入",
      amount: 5000,
      occurred_on: "2026-09-10",
      due_on: null,
      category: "服务",
      source: null,
      notes: null,
      recurrence: null,
    }))
    expect(toast.success).toHaveBeenCalledWith("财务记录已添加")
  })

  it.each([
    { variant: "receivable" as const, kind: "income", status: "应收", submitLabel: "新增待收" },
    { variant: "payable" as const, kind: "expense", status: "应付", submitLabel: "新增待付" },
  ])("$submitLabel 创建时 occurred_on 取当天、due_on 取表单日期", async ({ variant, kind, status, submitLabel }) => {
    let requestBody: unknown
    server.use(http.post("/api/finance/entries", async ({ request }) => {
      requestBody = await request.json()
      return HttpResponse.json(createdEntry, { status: 201 })
    }))

    renderDrawer({ variant })
    await userEvent.type(screen.getByLabelText("名称"), "客户尾款")
    await userEvent.type(screen.getByLabelText("金额"), "12000")
    await userEvent.type(screen.getByLabelText("收付款对象"), "星河科技")
    fireEvent.change(screen.getByLabelText("预计收付日期"), { target: { value: "2026-09-20" } })
    await userEvent.type(screen.getByLabelText("备注（可选）"), "月底结算")
    await userEvent.click(screen.getByRole("button", { name: submitLabel }))

    await waitFor(() => expect(requestBody).toEqual({
      kind,
      status,
      name: "客户尾款",
      amount: 12000,
      occurred_on: todayShanghai(),
      due_on: "2026-09-20",
      category: null,
      source: "星河科技",
      notes: "月底结算",
      recurrence: null,
    }))
  })

  it("缺少名称或预计收付日期时不发起请求并提示", async () => {
    let postCalls = 0
    server.use(http.post("/api/finance/entries", () => {
      postCalls += 1
      return HttpResponse.json(createdEntry, { status: 201 })
    }))

    renderDrawer({ variant: "payable" })
    await userEvent.click(screen.getByRole("button", { name: "新增待付" }))
    expect(toast.error).toHaveBeenCalledWith("请填写名称")

    await userEvent.type(screen.getByLabelText("名称"), "云服务账单")
    await userEvent.type(screen.getByLabelText("金额"), "300")
    await userEvent.type(screen.getByLabelText("收付款对象"), "火山引擎")
    await userEvent.click(screen.getByRole("button", { name: "新增待付" }))
    expect(toast.error).toHaveBeenCalledWith("请选择预计收付日期")
    expect(postCalls).toBe(0)
  })

  it("编辑待收记录时预填字段，PUT 保留原 occurred_on 与应收状态", async () => {
    const entry: FinanceEntry = {
      ...createdEntry,
      status: "应收",
      occurred_on: "2026-08-01",
      due_on: null,
      source: "星河科技",
      notes: "尾款",
    }
    let requestBody: unknown
    let requestMethod = ""
    server.use(http.put("/api/finance/entries/:id", async ({ request }) => {
      requestMethod = request.method
      requestBody = await request.json()
      return HttpResponse.json(entry)
    }))

    renderDrawer({ entry, variant: "receivable" })
    expect(screen.getByRole("dialog")).toHaveTextContent("编辑财务记录")
    expect(screen.getByLabelText("名称")).toHaveValue("咨询收入")
    expect(screen.getByLabelText("收付款对象")).toHaveValue("星河科技")
    expect(screen.getByLabelText("预计收付日期")).toHaveValue("")

    fireEvent.change(screen.getByLabelText("预计收付日期"), { target: { value: "2026-09-25" } })
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(requestBody).toMatchObject({
      kind: "income",
      status: "应收",
      occurred_on: "2026-08-01",
      due_on: "2026-09-25",
      source: "星河科技",
      notes: "尾款",
    }))
    expect(requestMethod).toBe("PUT")
    expect(toast.success).toHaveBeenCalledWith("财务记录已更新")
  })
})
