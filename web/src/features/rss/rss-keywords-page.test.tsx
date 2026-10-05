import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { RssKeywordsPage } from "./rss-keywords-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const keywords = [
  {
    id: "22222222-2222-2222-2222-222222222222",
    term: "AI agents",
    kind: "positive",
    enabled: true,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    term: "sponsored post",
    kind: "negative",
    enabled: false,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
  },
]

function buildKeywords(count: number, kind: "positive" | "negative" = "positive") {
  return Array.from({ length: count }, (_, index) => ({
    id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
    term: `keyword-${String(index + 1).padStart(2, "0")}`,
    kind,
    enabled: true,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
  }))
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <RssKeywordsPage />
    </QueryClientProvider>,
  )
}

describe("RssKeywordsPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("separates positive and negative keywords", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(keywords)),
    )

    renderPage()

    expect(await screen.findByRole("heading", { level: 1, name: "RSS 关键词" })).toBeInTheDocument()
    expect(await screen.findByRole("region", { name: "正向关键词" })).toHaveTextContent("AI agents")
    expect(screen.getByRole("region", { name: "反向关键词" })).toHaveTextContent("sponsored post")
  })

  it("opens the create drawer and closes it via cancel or close button", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
    )
    renderPage()

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole("button", { name: "新建关键词" }))
    expect(screen.getByRole("dialog", { name: "新建关键词" })).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "新建关键词" }))
    await userEvent.click(screen.getByRole("button", { name: "关闭抽屉" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("adds a keyword to the selected negative list", async () => {
    let currentKeywords: typeof keywords = []
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(currentKeywords)),
      http.post("/api/rss/keywords", async ({ request }) => {
        requestBody = await request.json()
        const created = {
          ...keywords[1],
          id: "55555555-5555-5555-5555-555555555555",
          term: "press release",
          enabled: true,
        }
        currentKeywords = [created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "新建关键词" }))
    const dialog = screen.getByRole("dialog", { name: "新建关键词" })
    await userEvent.type(within(dialog).getByLabelText("关键词"), "press release")
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "关键词类型" }), "negative")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加关键词" }))

    expect(await screen.findByRole("region", { name: "反向关键词" })).toHaveTextContent("press release")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(requestBody).toEqual({ term: "press release", kind: "negative", enabled: true })
  })

  it("edits and reclassifies a keyword through the drawer", async () => {
    let currentKeywords = keywords
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(currentKeywords)),
      http.put("/api/rss/keywords/:id", async ({ params, request }) => {
        requestBody = await request.json()
        currentKeywords = currentKeywords.map((keyword) => (
          keyword.id === params.id ? { ...keyword, ...(requestBody as object) } : keyword
        ))
        return HttpResponse.json(currentKeywords.find((keyword) => keyword.id === params.id))
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "编辑 AI agents" }))
    const dialog = screen.getByRole("dialog", { name: "编辑关键词" })
    expect(within(dialog).getByLabelText("关键词")).toHaveValue("AI agents")
    await userEvent.clear(within(dialog).getByLabelText("关键词"))
    await userEvent.type(within(dialog).getByLabelText("关键词"), "AI systems")
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "关键词类型" }), "negative")
    await userEvent.click(within(dialog).getByRole("button", { name: "保存关键词" }))

    expect(await screen.findByRole("region", { name: "反向关键词" })).toHaveTextContent("AI systems")
    expect(screen.getByRole("region", { name: "正向关键词" })).not.toHaveTextContent("AI agents")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(requestBody).toEqual({ term: "AI systems", kind: "negative", enabled: true })
  })

  it("disables a keyword without changing its term or type", async () => {
    let currentKeywords = [keywords[0]]
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(currentKeywords)),
      http.put("/api/rss/keywords/:id", async ({ request }) => {
        requestBody = await request.json()
        currentKeywords = [{ ...keywords[0], ...(requestBody as object) }]
        return HttpResponse.json(currentKeywords[0])
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "停用 AI agents" }))

    expect(await screen.findByRole("region", { name: "正向关键词" })).toHaveTextContent("已停用")
    expect(requestBody).toEqual({ term: "AI agents", kind: "positive", enabled: false })
  })

  it("requires confirmation before deleting a keyword", async () => {
    let currentKeywords = [keywords[0]]
    const deleteRequest = vi.fn()
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(currentKeywords)),
      http.delete("/api/rss/keywords/:id", () => {
        deleteRequest()
        currentKeywords = []
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除 AI agents" }))
    expect(deleteRequest).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "确认删除 AI agents" }))

    expect(await screen.findByRole("region", { name: "正向关键词" })).toHaveTextContent("尚未配置正向关键词")
    expect(deleteRequest).toHaveBeenCalledOnce()
  })

  it("filters keywords per panel via the search input", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(keywords)),
    )
    renderPage()

    const positive = await screen.findByRole("region", { name: "正向关键词" })
    await userEvent.type(screen.getByRole("textbox", { name: "搜索正向关键词" }), "zzz")

    expect(positive).toHaveTextContent("没有匹配「zzz」的正向关键词")
    expect(positive).not.toHaveTextContent("AI agents")
    expect(screen.getByRole("region", { name: "反向关键词" })).toHaveTextContent("sponsored post")
  })

  it("collapses long lists behind an expand toggle", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(buildKeywords(31))),
    )
    renderPage()

    const positive = await screen.findByRole("region", { name: "正向关键词" })
    expect(positive).toHaveTextContent("keyword-30")
    expect(positive).not.toHaveTextContent("keyword-31")

    await userEvent.click(screen.getByRole("button", { name: "展开全部 31 条" }))
    expect(positive).toHaveTextContent("keyword-31")

    await userEvent.click(screen.getByRole("button", { name: "收起" }))
    expect(positive).not.toHaveTextContent("keyword-31")
  })

  it("search bypasses collapse and restores it when cleared", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(buildKeywords(31))),
    )
    renderPage()

    const positive = await screen.findByRole("region", { name: "正向关键词" })
    const search = screen.getByRole("textbox", { name: "搜索正向关键词" })
    await userEvent.type(search, "keyword-31")

    expect(positive).toHaveTextContent("keyword-31")
    expect(positive).toHaveTextContent("1 / 31 个关键词")
    expect(screen.queryByRole("button", { name: /展开全部/ })).not.toBeInTheDocument()

    await userEvent.clear(search)
    expect(positive).not.toHaveTextContent("keyword-31")
    expect(screen.getByRole("button", { name: "展开全部 31 条" })).toBeInTheDocument()
  })

  it("keeps actions available on filtered results", async () => {
    let currentKeywords = [keywords[0]]
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json(currentKeywords)),
      http.put("/api/rss/keywords/:id", async ({ request }) => {
        requestBody = await request.json()
        currentKeywords = [{ ...keywords[0], ...(requestBody as object) }]
        return HttpResponse.json(currentKeywords[0])
      }),
    )
    renderPage()

    await userEvent.type(await screen.findByRole("textbox", { name: "搜索正向关键词" }), "AI")
    await userEvent.click(screen.getByRole("button", { name: "停用 AI agents" }))

    expect(await screen.findByRole("region", { name: "正向关键词" })).toHaveTextContent("已停用")
    expect(requestBody).toEqual({ term: "AI agents", kind: "positive", enabled: false })
  })
})
