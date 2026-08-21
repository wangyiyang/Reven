import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"

import { server } from "@/test/server"
import { RssSettingsPage } from "./rss-settings-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const source = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "OpenAI Blog",
  feed_url: "https://openai.com/blog/rss.xml",
  enabled: true,
  created_at: "2026-08-11T00:00:00Z",
  updated_at: "2026-08-11T00:00:00Z",
}

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

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <RssSettingsPage />
    </QueryClientProvider>,
  )
}

describe("RssSettingsPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows configured sources and separates positive and negative keywords", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([source])),
      http.get("/api/rss/keywords", () => HttpResponse.json(keywords)),
    )

    renderPage()

    expect(await screen.findByRole("heading", { name: "RSS 内容发现配置" })).toBeInTheDocument()
    expect(await screen.findByText("OpenAI Blog")).toBeInTheDocument()
    expect(await screen.findByRole("link", { name: "https://openai.com/blog/rss.xml" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "正向关键词" })).toHaveTextContent("AI agents")
    expect(screen.getByRole("region", { name: "反向关键词" })).toHaveTextContent("sponsored post")
  })

  it("filters sources by keyword in name or feed URL", async () => {
    const other = {
      ...source,
      id: "33333333-3333-3333-3333-333333333333",
      name: "SegmentFault",
      feed_url: "https://segmentfault.com/feeds",
    }
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([source, other])),
      http.get("/api/rss/keywords", () => HttpResponse.json(keywords)),
    )

    renderPage()

    expect(await screen.findByText("OpenAI Blog")).toBeInTheDocument()
    expect(screen.getByText("SegmentFault")).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText("搜索 RSS 源"), "openai")

    expect(screen.getByText("OpenAI Blog")).toBeInTheDocument()
    expect(screen.queryByText("SegmentFault")).not.toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText("搜索 RSS 源"))
    await userEvent.type(screen.getByLabelText("搜索 RSS 源"), "不存在的源")

    expect(screen.getByText("没有匹配的 RSS 源")).toBeInTheDocument()
    expect(screen.queryByText("OpenAI Blog")).not.toBeInTheDocument()
  })

  it("adds an RSS source and refreshes the list", async () => {
    let sources = [source]
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json(sources)),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
      http.post("/api/rss/sources", async ({ request }) => {
        requestBody = await request.json()
        const created = {
          ...source,
          id: "44444444-4444-4444-4444-444444444444",
          name: "Anthropic News",
          feed_url: "https://www.anthropic.com/rss.xml",
        }
        sources = [...sources, created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    renderPage()

    await userEvent.type(await screen.findByLabelText("RSS 源名称"), "Anthropic News")
    await userEvent.type(screen.getByLabelText("Feed URL"), "https://www.anthropic.com/rss.xml")
    await userEvent.click(screen.getByRole("button", { name: "添加 RSS 源" }))

    expect(await screen.findByText("Anthropic News")).toBeInTheDocument()
    expect(requestBody).toEqual({
      name: "Anthropic News",
      feed_url: "https://www.anthropic.com/rss.xml",
      enabled: true,
    })
    expect(toast.success).toHaveBeenCalledWith("RSS 源已添加")
  })

  it("edits an RSS source through the shared form", async () => {
    let sources = [source]
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json(sources)),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
      http.put("/api/rss/sources/:id", async ({ request }) => {
        requestBody = await request.json()
        sources = [{ ...source, ...(requestBody as object) }]
        return HttpResponse.json(sources[0])
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "编辑 OpenAI Blog" }))
    await userEvent.clear(screen.getByLabelText("RSS 源名称"))
    await userEvent.type(screen.getByLabelText("RSS 源名称"), "OpenAI News")
    await userEvent.click(screen.getByRole("button", { name: "保存 RSS 源" }))

    expect(await screen.findByText("OpenAI News")).toBeInTheDocument()
    expect(requestBody).toEqual({
      name: "OpenAI News",
      feed_url: "https://openai.com/blog/rss.xml",
      enabled: true,
    })
  })

  it("disables an RSS source without changing its other fields", async () => {
    let sources = [source]
    let requestBody: unknown
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json(sources)),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
      http.put("/api/rss/sources/:id", async ({ request }) => {
        requestBody = await request.json()
        sources = [{ ...source, ...(requestBody as object) }]
        return HttpResponse.json(sources[0])
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "停用 OpenAI Blog" }))

    expect(await screen.findByText("已停用")).toBeInTheDocument()
    expect(requestBody).toEqual({
      name: source.name,
      feed_url: source.feed_url,
      enabled: false,
    })
  })

  it("requires confirmation before deleting an RSS source", async () => {
    let sources = [source]
    const deleteRequest = vi.fn()
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json(sources)),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
      http.delete("/api/rss/sources/:id", () => {
        deleteRequest()
        sources = []
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "删除 OpenAI Blog" }))
    expect(deleteRequest).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "确认删除 OpenAI Blog" }))

    expect(await screen.findByText("尚未配置 RSS 源。")).toBeInTheDocument()
    expect(deleteRequest).toHaveBeenCalledOnce()
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

    await userEvent.type(await screen.findByLabelText("关键词"), "press release")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "关键词类型" }), "negative")
    await userEvent.click(screen.getByRole("button", { name: "添加关键词" }))

    expect(await screen.findByRole("region", { name: "反向关键词" })).toHaveTextContent("press release")
    expect(requestBody).toEqual({ term: "press release", kind: "negative", enabled: true })
  })

  it("edits and reclassifies a keyword through the shared form", async () => {
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
    await userEvent.clear(screen.getByLabelText("关键词"))
    await userEvent.type(screen.getByLabelText("关键词"), "AI systems")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "关键词类型" }), "negative")
    await userEvent.click(screen.getByRole("button", { name: "保存关键词" }))

    expect(await screen.findByRole("region", { name: "反向关键词" })).toHaveTextContent("AI systems")
    expect(screen.getByRole("region", { name: "正向关键词" })).not.toHaveTextContent("AI agents")
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

  it("keeps source input and shows the server error when creation fails", async () => {
    server.use(
      http.get("/api/rss/sources", () => HttpResponse.json([])),
      http.get("/api/rss/keywords", () => HttpResponse.json([])),
      http.post("/api/rss/sources", () => HttpResponse.json(
        { code: "RSS_SOURCE_URL_CONFLICT", message: "RSS 源地址已存在" },
        { status: 409 },
      )),
    )
    renderPage()

    await userEvent.type(await screen.findByLabelText("RSS 源名称"), "重复源")
    await userEvent.type(screen.getByLabelText("Feed URL"), "https://example.com/feed.xml")
    await userEvent.click(screen.getByRole("button", { name: "添加 RSS 源" }))

    expect(await screen.findByDisplayValue("重复源")).toBeInTheDocument()
    expect(toast.error).toHaveBeenCalledWith("RSS 源地址已存在")
    expect(toast.success).not.toHaveBeenCalled()
  })
})
