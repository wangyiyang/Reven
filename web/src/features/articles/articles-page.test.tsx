import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router-dom"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { ArticlesPage } from "./articles-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const article = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "测试稿件",
  notion_url: "https://www.notion.so/safe-page",
  notion_status: "待发布",
  automation_status: "等待中",
  target_channels: ["个人博客", "微信公众号"],
  planned_at: null,
  notion_last_edited_at: "2026-07-30T00:00:00Z",
  last_synced_at: "2026-07-30T00:01:00Z",
  cover_valid: true,
  content_sync: {
    status: "未同步",
    outputs_enabled: false,
    error: null,
    current_snapshot: null,
    latest_run: null,
  },
  blog_status: "待处理",
  wechat_status: "草稿已生成",
}

describe("ArticlesPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("persists status channel query and page filters in the URL", async () => {
    const requests: string[] = []
    server.use(http.get("/api/articles", ({ request }) => {
      requests.push(new URL(request.url).search)
      return HttpResponse.json({ items: [article], total: 21, page: 2, page_size: 20 })
    }))
    renderPage("/articles?status=待发布&channel=微信公众号&query=测试&page=2")

    expect(await screen.findAllByText("测试稿件")).not.toHaveLength(0)
    expect(screen.getByRole("combobox", { name: "状态" })).toHaveTextContent("待发布")
    expect(screen.getByRole("combobox", { name: "渠道" })).toHaveTextContent("微信公众号")
    expect(screen.getByLabelText("搜索标题")).toHaveValue("测试")
    expect(requests[0]).toContain("page=2")
    expect(screen.getByTestId("location")).toHaveTextContent("status=待发布")
  })

  it.each(["abc", "0", "-5"])("normalizes invalid page %s to the first page", async (page) => {
    const requests: URLSearchParams[] = []
    server.use(http.get("/api/articles", ({ request }) => {
      requests.push(new URL(request.url).searchParams)
      return HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })
    }))
    renderPage(`/articles?status=待发布&channel=微信公众号&query=测试&page=${page}`)

    expect(await screen.findAllByText("测试稿件")).not.toHaveLength(0)
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("page=1"))

    const normalizedParams = new URLSearchParams(screen.getByTestId("location").textContent ?? "")
    expect(normalizedParams.get("status")).toBe("待发布")
    expect(normalizedParams.get("channel")).toBe("微信公众号")
    expect(normalizedParams.get("query")).toBe("测试")
    expect(screen.getByTestId("navigation-type")).toHaveTextContent("REPLACE")
    expect(requests).toHaveLength(1)
    expect(requests[0].get("page")).toBe("1")
  })

  it("replaces an out-of-range page with the last page without showing the empty state", async () => {
    const requestedPages: string[] = []
    let showedEmptyState = false
    const emptyStateObserver = new MutationObserver((records) => {
      showedEmptyState ||= records.some((record) => [...record.addedNodes].some((node) => node.textContent?.includes("没有匹配稿件")))
    })
    emptyStateObserver.observe(document.body, { childList: true, subtree: true })
    server.use(http.get("/api/articles", ({ request }) => {
      const page = new URL(request.url).searchParams.get("page") ?? ""
      requestedPages.push(page)
      return HttpResponse.json({
        items: page === "3" ? [article] : [],
        total: 41,
        page: Number(page),
        page_size: 20,
      })
    }))

    renderPage("/articles?status=待发布&channel=微信公众号&query=测试&page=99")

    expect(await screen.findAllByText("测试稿件")).not.toHaveLength(0)
    emptyStateObserver.disconnect()
    expect(requestedPages).toEqual(["99", "3"])
    expect(showedEmptyState).toBe(false)
    expect(screen.queryByText("没有匹配稿件")).not.toBeInTheDocument()
    const normalizedParams = new URLSearchParams(screen.getByTestId("location").textContent ?? "")
    expect(normalizedParams.get("page")).toBe("3")
    expect(normalizedParams.get("status")).toBe("待发布")
    expect(normalizedParams.get("channel")).toBe("微信公众号")
    expect(normalizedParams.get("query")).toBe("测试")
    expect(screen.getByTestId("navigation-type")).toHaveTextContent("REPLACE")
  })

  it("keeps the empty state for a genuinely empty result", async () => {
    server.use(http.get("/api/articles", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })))
    renderPage("/articles?status=待发布&page=1")

    expect(await screen.findByText("没有匹配稿件")).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("status=待发布&page=1")
  })

  it("updates filters and sends them to the API", async () => {
    const requests: string[] = []
    server.use(http.get("/api/articles", ({ request }) => {
      requests.push(new URL(request.url).search)
      return HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })
    }))
    renderPage("/articles")

    await screen.findAllByText("测试稿件")
    await userEvent.click(screen.getByRole("combobox", { name: "状态" }))
    await userEvent.click(screen.getByRole("option", { name: "待发布" }))

    await waitFor(() => expect(requests.at(-1)).toContain("status=%E5%BE%85%E5%8F%91%E5%B8%83"))
  })

  it("loads status options from the facets endpoint instead of hardcoded values", async () => {
    server.use(
      http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })),
      http.get("/api/articles/status-facets", () => HttpResponse.json({ statuses: ["已发布", "撰写中"] })),
    )
    renderPage("/articles")

    await screen.findAllByText("测试稿件")
    await userEvent.click(screen.getByRole("combobox", { name: "状态" }))

    expect(await screen.findByRole("option", { name: "已发布" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "撰写中" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "全部状态" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "已完成" })).not.toBeInTheDocument()
  })

  it("shows the URL status value when the facets endpoint fails", async () => {
    server.use(
      http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })),
      http.get("/api/articles/status-facets", () => HttpResponse.json({ message: "boom" }, { status: 500 })),
    )
    renderPage("/articles?status=已发布&page=1")

    expect(await screen.findAllByText("测试稿件")).not.toHaveLength(0)
    expect(screen.getByRole("combobox", { name: "状态" })).toHaveTextContent("已发布")
    await userEvent.click(screen.getByRole("combobox", { name: "状态" }))
    expect(await screen.findByRole("option", { name: "已发布" })).toBeInTheDocument()
  })

  it("prevents duplicate synchronization while the request is pending", async () => {
    let calls = 0
    server.use(
      http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })),
      http.post("/api/articles/:id/sync", async () => {
        calls += 1
        await new Promise((resolve) => setTimeout(resolve, 80))
        return HttpResponse.json(syncRun())
      }),
      http.get("/api/articles/:id/sync-runs/:runId", () => HttpResponse.json(syncRun())),
    )
    renderPage("/articles")
    const buttons = await screen.findAllByRole("button", { name: /同步/ })

    await userEvent.dblClick(buttons[0])

    await waitFor(() => expect(calls).toBe(1))
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1))
  })

  it("moves channel statuses into the mobile summary", async () => {
    server.use(http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })))
    renderPage("/articles")

    const summary = await screen.findByRole("article", { name: "测试稿件移动摘要" })

    expect(within(summary).getByText("博客")).toBeInTheDocument()
    expect(within(summary).getByText("微信")).toBeInTheDocument()
    expect(within(summary).getByText("草稿已生成")).toBeInTheDocument()
  })

  it("tolerates target channels outside the publish pipeline (e.g. 掘金)", async () => {
    const juejinArticle = { ...article, title: "带掘金渠道的稿件", target_channels: ["微信公众号", "个人博客", "掘金"] }
    server.use(http.get("/api/articles", () => HttpResponse.json({ items: [juejinArticle], total: 1, page: 1, page_size: 20 })))
    renderPage("/articles")

    expect(await screen.findAllByText("带掘金渠道的稿件")).not.toHaveLength(0)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it.each([
    ["null items", { items: null, total: 1, page: 1, page_size: 20 }],
    ["string total", { items: [article], total: "1", page: 1, page_size: 20 }],
  ])("shows a recoverable error for malformed %s responses", async (_, body) => {
    server.use(http.get("/api/articles", () => HttpResponse.json(body)))
    renderPage("/articles")

    expect(await screen.findByRole("alert")).toHaveTextContent("稿件列表响应格式无效")
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument()
  })

  it("reports a malformed successful sync response without a success toast", async () => {
    server.use(
      http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })),
      http.post("/api/articles/:id/sync", () => HttpResponse.json({ ok: true })),
    )
    renderPage("/articles")

    await userEvent.click((await screen.findAllByRole("button", { name: /同步/ }))[0])

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("同步操作响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it.each(["not-a-date", "2026-07-30T08:01:00"])(
    "shows a recoverable error for malformed or timezone-naive list date %s",
    async (lastSyncedAt) => {
      server.use(http.get("/api/articles", () => HttpResponse.json({
        items: [{ ...article, last_synced_at: lastSyncedAt }],
        total: 1,
        page: 1,
        page_size: 20,
      })))
      renderPage("/articles")

      expect(await screen.findByRole("alert")).toHaveTextContent("稿件响应格式无效")
    },
  )
})

function renderPage(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes><Route element={<><ArticlesPage /><Location /></>} path="/articles" /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function Location() {
  const location = useLocation()
  const navigationType = useNavigationType()
  return <><output data-testid="location">{location.search}</output><output data-testid="navigation-type">{navigationType}</output></>
}

function syncRun() {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    article_id: article.id,
    status: "等待中",
    stage: "等待同步",
    progress_current: 0,
    progress_total: 0,
    current_media: null,
    error_stage: null,
    error_code: null,
    error_message: null,
    error_media: null,
    retryable: false,
    attempt_count: 0,
    created_at: "2026-07-30T00:01:00Z",
    updated_at: "2026-07-30T00:01:00Z",
    created: true,
  }
}
