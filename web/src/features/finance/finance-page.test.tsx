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
          income_cents: 80000,
          expense_cents: 20000,
          net_cents: 60000,
          receivable_cents: 30000,
          payable_cents: 40000,
        }),
      ),
    )

    renderPage()

    expect(await screen.findByRole("heading", { name: "财务收支" })).toBeInTheDocument()
    expect(screen.getByText("一人公司现金流台账：现金收付与应收应付。")).toBeInTheDocument()
    expect(screen.queryByText(/跑道/)).not.toBeInTheDocument()
    const summary = screen.getByRole("region", { name: "财务汇总" })
    await within(summary).findByText("¥800.00")
    expect(within(summary).getByText("已收收入").parentElement).toHaveTextContent("¥800.00")
    expect(within(summary).getByText("已付花销").parentElement).toHaveTextContent("¥200.00")
    expect(within(summary).getByText("现金净额").parentElement).toHaveTextContent("¥600.00")
    expect(within(summary).getByText("应收").parentElement).toHaveTextContent("¥300.00")
    expect(within(summary).getByText("应付").parentElement).toHaveTextContent("¥400.00")
    expect((await screen.findAllByText("¥150,000.00")).length).toBeGreaterThan(0)
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

  it("keeps the row and summary visible until the server confirms deletion", async () => {
    let entries = [income]
    let deleteCalls = 0
    let entriesGetCalls = 0
    let summaryGetCalls = 0
    let resolveDelete: () => void = () => {}
    server.use(
      http.get("/api/finance/entries", () => {
        entriesGetCalls += 1
        return HttpResponse.json(entries)
      }),
      http.get("/api/finance/summary", () => {
        summaryGetCalls += 1
        const incomeCents = entries.length > 0 ? 15000000 : 0
        return HttpResponse.json({ ...summaryZeros, income_cents: incomeCents, net_cents: incomeCents })
      }),
      http.delete("/api/finance/entries/:id", async () => {
        deleteCalls += 1
        await new Promise<void>((resolve) => { resolveDelete = resolve })
        entries = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    const summary = await screen.findByRole("region", { name: "财务汇总" })
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    const confirmButton = within(dialog).getByRole("button", { name: /确认删除/ })
    await userEvent.click(confirmButton)

    await waitFor(() => expect(deleteCalls).toBe(1))
    expect(screen.getAllByText("OLL 项目预付款")[0]).toBeInTheDocument()
    expect(summary).toHaveTextContent("¥150,000.00")
    expect(confirmButton).toBeDisabled()

    resolveDelete()
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await waitFor(() => expect(screen.queryByText("OLL 项目预付款")).not.toBeInTheDocument())
    expect(deleteCalls).toBe(1)
    expect(entriesGetCalls).toBe(2)
    expect(summaryGetCalls).toBe(2)
    expect(summary).not.toHaveTextContent("¥150,000.00")
  })

  it("keeps the row and summary when the delete fails", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([income])),
      http.get("/api/finance/summary", () =>
        HttpResponse.json({ ...summaryZeros, income_cents: 15000000, net_cents: 15000000 }),
      ),
      http.delete("/api/finance/entries/:id", () => HttpResponse.json({ message: "boom" }, { status: 500 })),
    )

    renderPage()
    const summary = await screen.findByRole("region", { name: "财务汇总" })
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "删除" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    expect(summary).toHaveTextContent("¥150,000.00")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })

  it("deletes four entries sequentially exactly once and stays consistent with the server", async () => {
    const initialEntries = [
      income,
      expense,
      { ...income, id: "33333333-3333-3333-3333-333333333333", name: "云服务器" },
      { ...expense, id: "44444444-4444-4444-4444-444444444444", name: "设计订阅" },
    ]
    let entries = [...initialEntries]
    const deleteCalls = new Map<string, number>()
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.get("/api/finance/summary", () => HttpResponse.json(summaryZeros)),
      http.delete("/api/finance/entries/:id", ({ params }) => {
        const id = String(params.id)
        deleteCalls.set(id, (deleteCalls.get(id) ?? 0) + 1)
        entries = entries.filter((entry) => entry.id !== id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()

    for (const entry of initialEntries) {
      await userEvent.click(screen.getByRole("button", { name: `删除 ${entry.name}` }))
      const dialog = await screen.findByRole("dialog")
      await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
      await waitFor(() => expect(screen.queryByText(entry.name)).not.toBeInTheDocument())
    }

    expect(entries).toEqual([])
    expect(Object.fromEntries(deleteCalls)).toEqual(
      Object.fromEntries(initialEntries.map((entry) => [entry.id, 1])),
    )
    expect((await screen.findAllByText("还没有财务记录。")).length).toBeGreaterThan(0)
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
