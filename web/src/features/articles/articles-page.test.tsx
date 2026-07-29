import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { ArticlesPage } from "./articles-page"

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
  blog_status: "待处理",
  wechat_status: "草稿已生成",
}

describe("ArticlesPage", () => {
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

  it("prevents duplicate synchronization while the request is pending", async () => {
    let calls = 0
    server.use(
      http.get("/api/articles", () => HttpResponse.json({ items: [article], total: 1, page: 1, page_size: 20 })),
      http.post("/api/articles/:id/sync", async () => {
        calls += 1
        await new Promise((resolve) => setTimeout(resolve, 80))
        return HttpResponse.json({ created: 0, updated: 1, failed: 0, duration_ms: 1 })
      }),
    )
    renderPage("/articles")
    const buttons = await screen.findAllByRole("button", { name: /同步/ })

    await userEvent.dblClick(buttons[0])

    await waitFor(() => expect(calls).toBe(1))
  })
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
  return <output data-testid="location">{location.search}</output>
}
