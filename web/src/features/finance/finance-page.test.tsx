import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"

import { server } from "@/test/server"
import { FinancePage } from "./finance-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const income = {
  id: "11111111-1111-1111-1111-111111111111",
  kind: "income",
  name: "OLL 项目预付款",
  amount_cents: 15000000,
  category: "服务",
  occurred_on: "2026-02-06",
  due_on: null,
  recurrence: null,
  source: "产品",
  status: "已收",
  notes: null,
  created_at: "2026-08-19T00:00:00Z",
  updated_at: "2026-08-19T00:00:00Z",
}

const expense = {
  ...income,
  id: "22222222-2222-2222-2222-222222222222",
  kind: "expense",
  name: "DeepSeek 充值",
  amount_cents: 10000,
  category: "AI / 大模型",
  occurred_on: "2026-07-21",
  source: null as string | null,
  status: "已付",
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FinancePage />
    </QueryClientProvider>,
  )
}

describe("FinancePage", () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  const summaryZeros = {
    income_cents: 0,
    expense_cents: 0,
    net_cents: 0,
    receivable_cents: 0,
    payable_cents: 0,
  }

  it("shows finance summary and entries", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income, expense])),
      http.get("/api/finance/summary", () =>
        HttpResponse.json({
          income_cents: 15000000,
          expense_cents: 10000,
          net_cents: 14990000,
          receivable_cents: 0,
          payable_cents: 0,
        }),
      ),
    )

    renderPage()

    expect(await screen.findByRole("heading", { name: "财务收支" })).toBeInTheDocument()
    expect((await screen.findAllByText("¥150,000.00")).length).toBeGreaterThan(0)
    expect(screen.getByRole("region", { name: "财务汇总" })).toHaveTextContent("¥100.00")
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    expect(screen.getAllByText("DeepSeek 充值")[0]).toBeInTheDocument()
  })

  it("creates an income entry and refreshes the list", async () => {
    let entries = [expense]
    let requestBody: unknown
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.get("/api/finance/summary", () =>
        HttpResponse.json({
          income_cents: 0,
          expense_cents: 10000,
          net_cents: -10000,
          receivable_cents: 0,
          payable_cents: 0,
        }),
      ),
      http.post("/api/finance/entries", async ({ request }) => {
        requestBody = await request.json()
        const created = { ...income, id: "33333333-3333-3333-3333-333333333333" }
        entries = [created, ...entries]
        return HttpResponse.json(created, { status: 201 })
      }),
    )

    renderPage()

    await userEvent.type(await screen.findByLabelText("名称"), "OLL 项目预付款")
    await userEvent.type(screen.getByLabelText("金额"), "150000")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型" }), "income")
    fireEvent.change(screen.getByLabelText("日期"), { target: { value: "2026-02-06" } })
    await userEvent.click(screen.getByRole("button", { name: "添加记录" }))

    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    expect(requestBody).toEqual({
      kind: "income",
      name: "OLL 项目预付款",
      amount: 150000,
      category: null,
      occurred_on: "2026-02-06",
      due_on: null,
      recurrence: null,
      source: null,
      status: "已记录",
      notes: null,
    })
    expect(toast.success).toHaveBeenCalledWith("财务记录已添加")
  })

  it("filters entries by kind", async () => {
    server.use(
      http.get("/api/finance/entries", ({ request }) => {
        const kind = new URL(request.url).searchParams.get("kind")
        return HttpResponse.json(kind === "income" ? [income] : [income, expense])
      }),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
    )

    renderPage()
    expect((await screen.findAllByText("DeepSeek 充值"))[0]).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型筛选" }), "income")

    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    expect(screen.queryByText("DeepSeek 充值")).not.toBeInTheDocument()
  })

  it("searches entries by keyword", async () => {
    server.use(
      http.get("/api/finance/entries", ({ request }) => {
        const query = new URL(request.url).searchParams.get("query")
        return HttpResponse.json(query === "DeepSeek" ? [expense] : [income, expense])
      }),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText("搜索记录"), "DeepSeek")

    expect((await screen.findAllByText("DeepSeek 充值"))[0]).toBeInTheDocument()
    expect(screen.queryByText("OLL 项目预付款")).not.toBeInTheDocument()
  })

  it("edits an entry and refreshes the list", async () => {
    let entries = [income]
    let requestBody: unknown
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
      http.put("/api/finance/entries/:id", async ({ request }) => {
        requestBody = await request.json()
        entries = [{ ...income, name: "OLL 项目尾款" }]
        return HttpResponse.json(entries[0])
      }),
    )

    renderPage()
    await userEvent.click(await screen.findByRole("button", { name: "编辑" }))

    const nameInput = await screen.findByLabelText("名称")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "OLL 项目尾款")
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    expect((await screen.findAllByText("OLL 项目尾款"))[0]).toBeInTheDocument()
    expect(requestBody).toMatchObject({ kind: "income", name: "OLL 项目尾款", amount: 150000, status: "已收" })
    expect(toast.success).toHaveBeenCalledWith("财务记录已更新")
  })

  it("asks for confirmation via dialog before deleting an entry", async () => {
    let deleted = false
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income])),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
      http.delete("/api/finance/entries/:id", () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "删除" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("删除财务记录")
    expect(deleted).toBe(false)

    await userEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    expect(deleted).toBe(false)
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getAllByText("OLL 项目预付款")[0]).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "删除" }))
    const dialog2 = await screen.findByRole("dialog")
    await userEvent.click(within(dialog2).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("财务记录已删除")
  })

  it("removes the row optimistically before the server responds", async () => {
    let resolveDelete: () => void = () => {}
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income])),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
      http.delete("/api/finance/entries/:id", async () => {
        await new Promise<void>((resolve) => { resolveDelete = resolve })
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    // 服务端响应被挂起时，行已经从列表消失（乐观更新）
    await waitFor(() => expect(screen.queryByText("OLL 项目预付款")).not.toBeInTheDocument())
    resolveDelete()
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("财务记录已删除"))
  })

  it("restores the row when the delete fails", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income])),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
      http.delete("/api/finance/entries/:id", () => HttpResponse.json({ message: "boom" }, { status: 500 })),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    // 失败后回滚：行恢复
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
  })

  it("renders mobile cards with labeled edit and delete actions", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income])),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
    )

    renderPage()

    const card = await screen.findByRole("article", { name: "OLL 项目预付款 移动摘要" })
    expect(card).toHaveTextContent("¥150,000.00")
    expect(card).toHaveTextContent("收入")
    expect(card).toHaveTextContent("2026-02-06")

    await userEvent.click(screen.getByRole("button", { name: "编辑 OLL 项目预付款" }))
    expect(screen.getByLabelText("名称")).toHaveValue("OLL 项目预付款")

    await userEvent.click(screen.getByRole("button", { name: "删除 OLL 项目预付款" }))
    expect(await screen.findByRole("dialog")).toHaveTextContent("删除财务记录")
  })

  it("stacks summary cards two-per-row on mobile", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([])),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
    )

    renderPage()

    const summary = await screen.findByRole("region", { name: "财务汇总" })
    expect(summary.className).toContain("grid-cols-2")
  })
})
