import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"

import { server } from "@/test/server"

import type { FinanceEntry } from "./finance-api"
import { FinancePendingPage } from "./finance-pending-page"
import { todayShanghai } from "./finance-utils"

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
    source: "星河科技",
    status: "应收",
    notes: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

const receivableEntries = [
  pendingEntry({ id: "aaaaaaa1-1111-1111-1111-111111111111", name: "逾期尾款", due_on: offsetDate(-3) }),
  pendingEntry({ id: "aaaaaaa2-1111-1111-1111-111111111111", name: "近期服务费", due_on: offsetDate(2) }),
  pendingEntry({ id: "aaaaaaa3-1111-1111-1111-111111111111", name: "远期顾问费", due_on: offsetDate(20) }),
  pendingEntry({ id: "aaaaaaa4-1111-1111-1111-111111111111", name: "未定款项", due_on: null }),
]

const payableEntry = pendingEntry({
  id: "bbbbbbb1-1111-1111-1111-111111111111",
  kind: "expense",
  name: "云服务账单",
  status: "应付",
  source: "火山引擎",
  due_on: offsetDate(5),
})

function renderPage(initialEntry = "/finance/pending") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}><FinancePendingPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("FinancePendingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/finance/entries", ({ request }) => {
      const status = new URL(request.url).searchParams.get("status")
      return HttpResponse.json(status === "应付" ? [payableEntry] : receivableEntries)
    }))
  })

  it("默认请求应收记录并按逾期/近期/以后/未定四组展示", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/finance/entries", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json(receivableEntries)
    }))

    renderPage()

    const overdue = await screen.findByRole("region", { name: "已逾期" })
    expect(within(overdue).getByRole("heading")).toHaveTextContent("已逾期（1）")
    expect(within(overdue).getAllByText("逾期尾款")[0]).toBeInTheDocument()
    expect(within(overdue).getAllByText(/逾期 3 天/)[0]).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "近期到期" })).getAllByText("近期服务费")[0]).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "以后到期" })).getAllByText("远期顾问费")[0]).toBeInTheDocument()
    const unscheduled = screen.getByRole("region", { name: "日期未定" })
    expect(within(unscheduled).getAllByText("未定款项")[0]).toBeInTheDocument()
    expect(within(unscheduled).getAllByText(/日期未定，可编辑补录/)[0]).toBeInTheDocument()
    expect(requests.at(-1)?.searchParams.get("status")).toBe("应收")
  })

  it("切换待付后请求应付记录", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/finance/entries", ({ request }) => {
      requests.push(new URL(request.url))
      const status = new URL(request.url).searchParams.get("status")
      return HttpResponse.json(status === "应付" ? [payableEntry] : receivableEntries)
    }))

    renderPage()
    await screen.findByRole("region", { name: "已逾期" })

    await userEvent.click(screen.getByRole("button", { name: "待付" }))

    expect((await screen.findAllByText("云服务账单"))[0]).toBeInTheDocument()
    expect(screen.queryByText("逾期尾款")).not.toBeInTheDocument()
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("status")).toBe("应付"))
  })

  it("?group=overdue 只展示逾期分组，清除筛选后恢复全部分组", async () => {
    renderPage("/finance/pending?group=overdue")

    await screen.findByRole("region", { name: "已逾期" })
    expect(screen.queryByRole("region", { name: "近期到期" })).not.toBeInTheDocument()
    expect(screen.getByText("仅看：已逾期")).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "清除筛选" }))

    expect(await screen.findByRole("region", { name: "近期到期" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "日期未定" })).toBeInTheDocument()
    expect(screen.queryByText("仅看：已逾期")).not.toBeInTheDocument()
  })

  it("确认收款后调用 confirm 接口且记录从列表消失", async () => {
    let entries = [receivableEntries[0]]
    let confirmBody: unknown
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.post("/api/finance/entries/:id/confirm", async ({ request }) => {
        confirmBody = await request.json()
        entries = []
        return HttpResponse.json({ ...receivableEntries[0], status: "已收", occurred_on: todayShanghai() })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("逾期尾款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "确认收款 逾期尾款" })[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("逾期尾款 · ¥500.00")
    expect(screen.getByLabelText("实际收付日期")).toHaveValue(todayShanghai())
    await userEvent.click(within(dialog).getByRole("button", { name: "确认收款" }))

    await waitFor(() => expect(confirmBody).toEqual({ occurred_on: todayShanghai() }))
    expect(toast.success).toHaveBeenCalledWith("确认收款成功")
    await waitFor(() => expect(screen.queryByText("逾期尾款")).not.toBeInTheDocument())
  })

  it("重复确认返回 409 时提示且款项保留在列表", async () => {
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([receivableEntries[0]])),
      http.post("/api/finance/entries/:id/confirm", () =>
        HttpResponse.json({ code: "FINANCE_ENTRY_ALREADY_SETTLED", message: "该款项已确认，请勿重复操作" }, { status: 409 })),
    )

    renderPage()
    expect((await screen.findAllByText("逾期尾款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "确认收款 逾期尾款" })[0])
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: "确认收款" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("该款项已确认，请刷新查看"))
    expect((await screen.findAllByText("逾期尾款"))[0]).toBeInTheDocument()
  })

  it("日期未定的款项可通过编辑抽屉补录预计收付日期", async () => {
    const unscheduled = receivableEntries[3]
    let requestBody: unknown
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json([unscheduled])),
      http.put("/api/finance/entries/:id", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json({ ...unscheduled, due_on: "2026-09-25" })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("未定款项"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "编辑 未定款项" })[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("编辑财务记录")
    expect(screen.getByLabelText("预计收付日期")).toHaveValue("")
    fireEvent.change(screen.getByLabelText("预计收付日期"), { target: { value: "2026-09-25" } })
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(requestBody).toMatchObject({ status: "应收", due_on: "2026-09-25" }))
    expect(toast.success).toHaveBeenCalledWith("财务记录已更新")
  })
})
