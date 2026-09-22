import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"

import type { FinanceEntry } from "./finance-api"
import { FinanceLedgerPage } from "./finance-ledger-page"
import { currentMonthShanghai } from "./finance-utils"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const settledIncome: FinanceEntry = {
  id: "11111111-1111-1111-1111-111111111111",
  kind: "income",
  name: "OLL 项目预付款",
  amount_cents: 15000000,
  category: "服务",
  occurred_on: "2026-09-06",
  due_on: null,
  recurrence: null,
  source: null,
  status: "已收",
  notes: null,
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
}

const settledExpense: FinanceEntry = {
  ...settledIncome,
  id: "22222222-2222-2222-2222-222222222222",
  kind: "expense",
  name: "DeepSeek 充值",
  amount_cents: 10000,
  category: "AI / 大模型",
  occurred_on: "2026-09-21",
  status: "已付",
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><FinanceLedgerPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("FinanceLedgerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/finance/entries", () => HttpResponse.json([settledIncome, settledExpense])))
  })

  it("默认请求只查当月已收/已付记录，列表渲染返回的流水", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/finance/entries", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json([settledIncome, settledExpense])
    }))

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    expect(screen.getAllByText("DeepSeek 充值")[0]).toBeInTheDocument()

    const latest = requests.at(-1)
    expect(latest?.searchParams.get("status")).toBe("已收,已付")
    expect(latest?.searchParams.get("month")).toBe(currentMonthShanghai())
    expect(latest?.searchParams.get("kind")).toBeNull()
  })

  it("筛选变更驱动请求参数：类型、分类、搜索、月份", async () => {
    const requests: URL[] = []
    server.use(http.get("/api/finance/entries", ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json([])
    }))

    renderPage()
    await screen.findByText("该月份暂无收支流水。")

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型筛选" }), "income")
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("kind")).toBe("income"))

    await userEvent.type(screen.getByLabelText("分类"), "服务")
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("category")).toBe("服务"))

    await userEvent.type(screen.getByLabelText("搜索"), "DeepSeek")
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("query")).toBe("DeepSeek"))

    fireEvent.change(screen.getByLabelText("月份"), { target: { value: "2026-08" } })
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("month")).toBe("2026-08"))
  })

  it("通过抽屉编辑记录并刷新列表", async () => {
    let entries = [settledIncome]
    let requestBody: unknown
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.put("/api/finance/entries/:id", async ({ request }) => {
        requestBody = await request.json()
        entries = [{ ...settledIncome, name: "OLL 项目尾款" }]
        return HttpResponse.json(entries[0])
      }),
    )

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "编辑 OLL 项目预付款" }))[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("编辑财务记录")
    const nameInput = screen.getByLabelText("名称")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "OLL 项目尾款")
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }))

    expect((await screen.findAllByText("OLL 项目尾款"))[0]).toBeInTheDocument()
    expect(requestBody).toMatchObject({ kind: "income", status: "已收", name: "OLL 项目尾款", amount: 150000 })
  })

  it("删除前弹确认框，确认后记录从列表移除", async () => {
    let entries = [settledIncome]
    server.use(
      http.get("/api/finance/entries", () => HttpResponse.json(entries)),
      http.delete("/api/finance/entries/:id", () => {
        entries = []
        return new HttpResponse(null, { status: 204 })
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 项目预付款"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "删除 OLL 项目预付款" })[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("删除财务记录")
    await userEvent.click(within(dialog).getByRole("button", { name: /确认删除/ }))

    await screen.findByText("该月份暂无收支流水。")
    expect(screen.queryByText("OLL 项目预付款")).not.toBeInTheDocument()
  })
})
