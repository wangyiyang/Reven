import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"
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
    expect(await screen.findByText("OLL 项目预付款")).toBeInTheDocument()
    expect(screen.getByText("DeepSeek 充值")).toBeInTheDocument()
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

    expect(await screen.findByText("OLL 项目预付款")).toBeInTheDocument()
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
})
