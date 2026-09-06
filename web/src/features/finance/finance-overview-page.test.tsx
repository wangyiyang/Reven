import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"

import type { FinanceEntry } from "./finance-api"
import { FinanceOverviewPage } from "./finance-overview-page"
import { currentMonthShanghai, formatMonthLabel, todayShanghai } from "./finance-utils"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function offsetDate(days: number): string {
  const date = new Date(`${todayShanghai()}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function pendingEntry(overrides: Partial<FinanceEntry>): FinanceEntry {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    kind: "income",
    name: "待收款项",
    amount_cents: 50000,
    category: null,
    occurred_on: "2026-09-01",
    due_on: null,
    recurrence: null,
    source: null,
    status: "应收",
    notes: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

const pendingEntries = [
  pendingEntry({ id: "aaaaaaa1-1111-1111-1111-111111111111", name: "逾期尾款", due_on: offsetDate(-3), amount_cents: 50000 }),
  pendingEntry({ id: "aaaaaaa5-1111-1111-1111-111111111111", name: "逾期采购", kind: "expense", status: "应付", due_on: offsetDate(-1), amount_cents: 20000 }),
  pendingEntry({ id: "aaaaaaa2-1111-1111-1111-111111111111", name: "近期服务费", due_on: offsetDate(2), amount_cents: 30000 }),
  pendingEntry({ id: "aaaaaaa3-1111-1111-1111-111111111111", name: "远期顾问费", due_on: offsetDate(20), amount_cents: 80000 }),
  pendingEntry({ id: "aaaaaaa4-1111-1111-1111-111111111111", name: "未定款项", due_on: null, amount_cents: 10000 }),
]

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><FinanceOverviewPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("FinanceOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(
      http.get("/api/finance/summary", () => HttpResponse.json({
        income_cents: 80000,
        expense_cents: 20000,
        net_cents: 60000,
        receivable_cents: 30000,
        payable_cents: 40000,
      })),
      http.get("/api/finance/entries", () => HttpResponse.json(pendingEntries)),
    )
  })

  it("展示本月三卡金额与统计周期，现金区不混入应收应付", async () => {
    renderPage()

    const summary = await screen.findByRole("region", { name: "本月收支汇总" })
    expect(summary).toHaveTextContent(`统计周期：本月（${formatMonthLabel(currentMonthShanghai())}）`)
    await within(summary).findByText("¥800.00")
    expect(within(summary).getByText("本月实收").parentElement).toHaveTextContent("¥800.00")
    expect(within(summary).getByText("本月实付").parentElement).toHaveTextContent("¥200.00")
    expect(within(summary).getByText("收支净额").parentElement).toHaveTextContent("¥600.00")
    expect(within(summary).queryByText("应收")).not.toBeInTheDocument()
    expect(within(summary).queryByText("应付")).not.toBeInTheDocument()
    expect(screen.queryByText(/跑道|余额|利润/)).not.toBeInTheDocument()
  })

  it("summary 请求携带当月 month，待收付请求携带应收应付状态", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/finance/entries", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json(pendingEntries)
    }))
    let summaryUrl: URL | null = null
    server.use(http.get("/api/finance/summary", ({ request }) => {
      summaryUrl = new URL(request.url)
      return HttpResponse.json({ income_cents: 0, expense_cents: 0, net_cents: 0, receivable_cents: 0, payable_cents: 0 })
    }))

    renderPage()
    await screen.findByRole("region", { name: "本月收支汇总" })

    await waitFor(() => expect(summaryUrl?.searchParams.get("month")).toBe(currentMonthShanghai()))
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("status")).toBe("应收,应付"))
  })

  it("逾期与近期到期摘要按方向拆分链接，可进入待收待付页对应分组", async () => {
    renderPage()

    const digest = await screen.findByRole("region", { name: "待处理款项" })
    const overdueCard = (await within(digest).findByText("已逾期")).parentElement as HTMLElement
    expect(overdueCard).toHaveTextContent("2 笔 · ¥700.00")
    const overdueReceivable = within(overdueCard).getByRole("link", { name: /待收 1 笔 · ¥500.00/ })
    expect(overdueReceivable).toHaveAttribute("href", "/finance/pending?tab=receivable&group=overdue")
    const overduePayable = within(overdueCard).getByRole("link", { name: /待付 1 笔 · ¥200.00/ })
    expect(overduePayable).toHaveAttribute("href", "/finance/pending?tab=payable&group=overdue")

    const upcomingCard = (within(digest).getByText("近期到期（7 天内）")).parentElement as HTMLElement
    expect(upcomingCard).toHaveTextContent("1 笔 · ¥300.00")
    const upcomingReceivable = within(upcomingCard).getByRole("link", { name: /待收 1 笔 · ¥300.00/ })
    expect(upcomingReceivable).toHaveAttribute("href", "/finance/pending?tab=receivable&group=upcoming")
    expect(within(upcomingCard).queryByRole("link", { name: /待付/ })).not.toBeInTheDocument()
  })

  it("没有逾期与近期到期款项时展示空态文案", async () => {
    server.use(http.get("/api/finance/entries", () => HttpResponse.json([
      pendingEntry({ name: "远期顾问费", due_on: offsetDate(20) }),
    ])))

    renderPage()

    const digest = await screen.findByRole("region", { name: "待处理款项" })
    await within(digest).findByText("暂无待处理款项。")
    expect(within(digest).queryByRole("link")).not.toBeInTheDocument()
  })
})
