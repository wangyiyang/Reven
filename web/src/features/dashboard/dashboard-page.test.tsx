import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it } from "vitest"

import { server } from "@/test/server"

import type { DashboardSummary } from "./dashboard-api"
import { MISSING_INTEGRATIONS_DISMISSED_KEY } from "./dashboard-api"
import { DashboardPage } from "./dashboard-page"

function summaryFixture(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    finance: {
      receivable_cents: 120000,
      receivable_count: 3,
      overdue_receivable_cents: 50000,
      overdue_receivable_count: 1,
    },
    rss: {
      candidate_count: 12,
      saved_count: 34,
      latest_run: { status: "completed", failure_count: 0, finished_at: "2026-10-05T06:00:00Z" },
    },
    crm: {
      overdue_count: 2,
      today_count: 1,
      due_items: [
        {
          customer_id: "11111111-1111-1111-1111-111111111111",
          name: "张三",
          next_action: "电话回访",
          next_follow_up_on: "2026-10-02",
          overdue_days: 3,
        },
        {
          customer_id: "22222222-2222-2222-2222-222222222222",
          name: "李四",
          next_action: "发报价",
          next_follow_up_on: "2026-10-05",
          overdue_days: 0,
        },
      ],
    },
    projects: {
      active_count: 4,
      items: [
        { id: "33333333-3333-3333-3333-333333333333", name: "官网改版", due_on: "2026-10-01", overdue: true },
        { id: "44444444-4444-4444-4444-444444444444", name: "内部工具", due_on: "2026-10-20", overdue: false },
      ],
    },
    integrations: { missing_providers: [], cos_configured: true },
    ...overrides,
  }
}

function mockSummary(summary: DashboardSummary) {
  server.use(http.get("/api/dashboard/summary", () => HttpResponse.json(summary)))
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("DashboardPage", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it("渲染四张卡片与聚合数字", async () => {
    mockSummary(summaryFixture())
    renderPage()

    expect(await screen.findByRole("heading", { name: "工作台" })).toBeInTheDocument()
    // 整卡链接在加载态即渲染，先等真实数据到达再断言
    await screen.findByText("¥1,200.00")

    const financeCard = screen.getByRole("link", { name: "前往财务待收款" })
    expect(financeCard).toHaveTextContent("财务待收款")
    expect(financeCard).toHaveTextContent("¥1,200.00")
    expect(financeCard).toHaveTextContent("3 笔待收")
    expect(financeCard).toHaveTextContent("逾期 ¥500.00 · 1 笔")

    const rssCard = screen.getByRole("link", { name: "前往 RSS 待审核" })
    expect(rssCard).toHaveTextContent("12")
    expect(rssCard).toHaveTextContent("已保存素材 34")
    expect(rssCard).toHaveTextContent("最近抓取：成功")

    const crmLink = screen.getByRole("link", { name: "前往 CRM" })
    const crmCard = crmLink.closest("div")?.parentElement as HTMLElement
    expect(crmCard).toHaveTextContent("逾期 2 / 今日 1")
    expect(within(crmCard).getByRole("link", { name: "查看客户 张三" })).toHaveTextContent("2026-10-02")

    const projectCard = screen.getByRole("link", { name: "前往项目列表" })
    expect(projectCard).toHaveTextContent("进行中项目")
    expect(projectCard).toHaveTextContent("4")
    expect(projectCard).toHaveTextContent("官网改版")
    expect(projectCard).toHaveTextContent("2026-10-01")
  })

  it("逾期项以 destructive 红色突出", async () => {
    mockSummary(summaryFixture())
    renderPage()

    await screen.findByText("逾期 ¥500.00 · 1 笔")
    const financeCard = screen.getByRole("link", { name: "前往财务待收款" })
    expect(financeCard.querySelector(".text-\\[var\\(--danger\\)\\]")).toHaveTextContent("逾期 ¥500.00 · 1 笔")

    const crmOverdue = screen.getByText("逾期 2")
    expect(crmOverdue.className).toContain("text-[var(--danger)]")

    const overdueCustomer = screen.getByRole("link", { name: "查看客户 张三" })
    expect(overdueCustomer.querySelector(".text-\\[var\\(--danger\\)\\]")).toHaveTextContent("逾期 3 天 · 2026-10-02")
    const todayCustomer = screen.getByRole("link", { name: "查看客户 李四" })
    expect(todayCustomer.querySelector(".text-\\[var\\(--danger\\)\\]")).toBeNull()

    const projectCard = screen.getByRole("link", { name: "前往项目列表" })
    const overdueProject = within(projectCard).getByText("2026-10-01")
    expect(overdueProject.className).toContain("text-[var(--danger)]")
    const futureProject = within(projectCard).getByText("2026-10-20")
    expect(futureProject.className).not.toContain("text-[var(--danger)]")
  })

  it("最近抓取失败时状态点与文案显眼提示", async () => {
    mockSummary(
      summaryFixture({
        rss: {
          candidate_count: 5,
          saved_count: 1,
          latest_run: { status: "partial", failure_count: 3, finished_at: "2026-10-05T06:00:00Z" },
        },
      }),
    )
    renderPage()

    const rssCard = screen.getByRole("link", { name: "前往 RSS 待审核" })
    const failureLine = await within(rssCard).findByText(/最近抓取：3 条失败/)
    expect(failureLine.className).toContain("text-[var(--danger)]")
  })

  it("横幅列出全部缺失项（含 COS），关闭后不再显示；出现新缺失项时重新弹出", async () => {
    mockSummary(
      summaryFixture({
        integrations: { missing_providers: ["translate_baidu"], cos_configured: false },
      }),
    )
    const first = renderPage()

    const banner = await screen.findByRole("region", { name: "集成配置缺失提醒" })
    expect(banner).toHaveTextContent("2 项集成未配置")
    expect(banner).toHaveTextContent("百度翻译")
    expect(banner).toHaveTextContent("腾讯云 COS（环境变量）")
    expect(within(banner).getByRole("link", { name: "前往集成设置" })).toHaveAttribute("href", "/integrations")

    await userEvent.click(within(banner).getByRole("button", { name: "关闭集成缺失提醒" }))
    expect(screen.queryByRole("region", { name: "集成配置缺失提醒" })).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(MISSING_INTEGRATIONS_DISMISSED_KEY) ?? "[]")).toEqual([
      "translate_baidu",
      "cos",
    ])

    // 相同缺失集合：重新挂载后仍保持关闭（等数据到达再断言，避免加载态误通过）
    first.unmount()
    const second = renderPage()
    await screen.findByText("¥1,200.00")
    expect(screen.queryByRole("region", { name: "集成配置缺失提醒" })).not.toBeInTheDocument()

    // 出现新缺失项（embedding）：横幅重新弹出
    mockSummary(
      summaryFixture({
        integrations: { missing_providers: ["translate_baidu", "embedding"], cos_configured: true },
      }),
    )
    second.unmount()
    renderPage()
    const reopened = await screen.findByRole("region", { name: "集成配置缺失提醒" })
    expect(reopened).toHaveTextContent("Embedding")
    expect(reopened).not.toHaveTextContent("腾讯云 COS")
  })

  it("无缺失项时不显示横幅", async () => {
    mockSummary(summaryFixture())
    renderPage()

    // 等数据到达再断言，避免加载态误通过
    await screen.findByText("¥1,200.00")
    expect(screen.queryByRole("region", { name: "集成配置缺失提醒" })).not.toBeInTheDocument()
  })

  it("卡片与清单项链接到对应模块页面", async () => {
    mockSummary(summaryFixture())
    renderPage()

    expect(await screen.findByRole("link", { name: "前往财务待收款" })).toHaveAttribute("href", "/finance/pending")
    expect(screen.getByRole("link", { name: "前往 RSS 待审核" })).toHaveAttribute("href", "/rss/candidates")
    expect(screen.getByRole("link", { name: "前往 CRM" })).toHaveAttribute("href", "/crm")
    expect(screen.getByRole("link", { name: "前往项目列表" })).toHaveAttribute("href", "/projects")
    // 清单项依赖数据加载，用 findByRole 等待
    expect(await screen.findByRole("link", { name: "查看客户 张三" })).toHaveAttribute(
      "href",
      "/crm/customers/11111111-1111-1111-1111-111111111111",
    )
  })

  it("零值正常显示 0，不隐藏卡片；无运行记录时提示暂无抓取记录", async () => {
    mockSummary({
      finance: { receivable_cents: 0, receivable_count: 0, overdue_receivable_cents: 0, overdue_receivable_count: 0 },
      rss: { candidate_count: 0, saved_count: 0, latest_run: null },
      crm: { overdue_count: 0, today_count: 0, due_items: [] },
      projects: { active_count: 0, items: [] },
      integrations: { missing_providers: [], cos_configured: true },
    })
    renderPage()

    // 整卡链接在加载态即渲染，先等真实数据到达再断言
    await screen.findByText("0 笔待收")
    const financeCard = screen.getByRole("link", { name: "前往财务待收款" })
    expect(financeCard).toHaveTextContent("¥0.00")
    expect(financeCard).toHaveTextContent("0 笔待收")
    expect(financeCard).toHaveTextContent("逾期 ¥0.00 · 0 笔")
    expect(financeCard.querySelector(".text-\\[var\\(--danger\\)\\]")).toBeNull()

    const rssCard = screen.getByRole("link", { name: "前往 RSS 待审核" })
    expect(rssCard).toHaveTextContent("暂无抓取记录")

    expect(screen.getByText("暂无待跟进客户。")).toBeInTheDocument()
    expect(screen.getByText("暂无进行中项目。")).toBeInTheDocument()
    expect(screen.getByText("逾期 0")).toBeInTheDocument()
  })
})
