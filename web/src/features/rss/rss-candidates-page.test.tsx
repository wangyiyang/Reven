import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"

import { server } from "@/test/server"
import { RssCandidatesPage } from "./rss-candidates-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const candidate = {
  id: "11111111-1111-1111-1111-111111111111",
  source_name: "Example",
  url: "https://example.com/agent-systems",
  title: "Agent systems",
  summary: "A practical guide to agent systems.",
  title_zh: "智能体系统",
  summary_zh: "一份关于智能体系统的实践指南。",
  published_at: "2026-08-11T01:00:00Z",
  status: "candidate",
  positive_literal_matches: ["agent"],
  negative_literal_matches: [],
  bm25_score: 0.6,
  positive_embedding_score: 0.9,
  negative_embedding_score: 0.1,
  embedding_model: "BAAI/bge-m3",
  embedding_status: "completed",
  model_status: "skipped",
  model_score: null,
  reason: "正向信号达到阈值",
  rules_version: "rss-v1",
  screening_error: null,
  saved_at: null,
}

function pageOf(items: unknown[], total = items.length, page = 1, pageSize = 30) {
  return { items, total, page, page_size: pageSize }
}

function renderPage(path = "/rss/candidates") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><RssCandidatesPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("RssCandidatesPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows candidate evidence and source material", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))))

    renderPage()

    expect(await screen.findByRole("heading", { name: "RSS 内容发现" })).toBeInTheDocument()
    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.getByText("正向信号达到阈值")).toBeInTheDocument()
    expect(screen.getByText("agent")).toBeInTheDocument()
    expect(screen.getByText("0.900")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "查看原文" })).toHaveAttribute(
      "href",
      "https://example.com/agent-systems",
    )
  })

  it("clamps long summaries behind an expand toggle", async () => {
    const longSummary = "这是一段很长的摘要。".repeat(60)
    server.use(
      http.get("/api/rss/candidates", () =>
        HttpResponse.json(pageOf([{ ...candidate, summary_zh: longSummary }])),
      ),
    )
    renderPage()

    const paragraph = await screen.findByText(longSummary)
    expect(paragraph.className).toContain("line-clamp")

    await userEvent.click(screen.getByRole("button", { name: "展开全文" }))

    expect(paragraph.className).not.toContain("line-clamp")
    expect(screen.getByRole("button", { name: "收起" })).toBeInTheDocument()
  })

  it("shows short summaries in full without a toggle", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))))
    renderPage()

    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "展开全文" })).not.toBeInTheDocument()
  })

  it("ignores a candidate and removes it from the queue", async () => {
    let items: unknown[] = [candidate]
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(pageOf(items, items.length))),
      http.post("/api/rss/candidates/:id/ignore", () => {
        items = []
        return HttpResponse.json({ ...candidate, status: "ignored" })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "忽略 智能体系统" }))

    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledWith("已忽略候选")
  })

  it("saves an approved candidate locally and makes it available in saved materials", async () => {
    let saved = false
    const savedItem = { ...candidate, status: "saved", saved_at: "2026-09-21T01:00:00Z" }
    const requestedStatuses: string[] = []
    server.use(
      http.get("/api/rss/candidates", ({ request }) => {
        const status = new URL(request.url).searchParams.get("status") ?? ""
        requestedStatuses.push(status)
        const items = status === "saved" ? (saved ? [savedItem] : []) : (saved ? [] : [candidate])
        return HttpResponse.json(pageOf(items))
      }),
      http.post("/api/rss/candidates/:id/confirm", () => {
        saved = true
        return HttpResponse.json(savedItem)
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "采纳并保存 智能体系统" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已保存到素材库"))
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("tab", { name: "已保存素材" }))
    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.getByText(/已保存 ·/)).toHaveTextContent("2026")
    expect(screen.getByRole("link", { name: "查看原文" })).toHaveAttribute("href", candidate.url)
    expect(screen.queryByRole("button", { name: /采纳并保存|忽略/ })).not.toBeInTheDocument()
    expect(requestedStatuses).toContain("saved")
    await userEvent.click(screen.getByRole("tab", { name: "待审核" }))
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
  })

  it("opens saved materials directly from the URL", async () => {
    let status: string | null = null
    server.use(http.get("/api/rss/candidates", ({ request }) => {
      status = new URL(request.url).searchParams.get("status")
      return HttpResponse.json(pageOf([]))
    }))
    renderPage("/rss/candidates?status=saved")
    expect(await screen.findByText("暂无已保存素材")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "已保存素材" })).toHaveAttribute("aria-selected", "true")
    expect(status).toBe("saved")
  })

  it.each(["saved", "ignored"])("hides review actions for %s items", async (status) => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([{ ...candidate, status }]))))
    renderPage()
    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /采纳并保存|忽略/ })).not.toBeInTheDocument()
  })

  it.each(["confirm", "ignore"])("allows retry after a failed %s action", async (action) => {
    let calls = 0
    let resolved = false
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(pageOf(resolved ? [] : [candidate]))),
      http.post(`/api/rss/candidates/:id/${action}`, () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ code: "failed", message: "操作失败，请重试" }, { status: 503 })
        resolved = true
        return HttpResponse.json({ ...candidate, status: action === "confirm" ? "saved" : "ignored" })
      }),
    )
    renderPage()
    const button = await screen.findByRole("button", { name: `${action === "confirm" ? "采纳并保存" : "忽略"} 智能体系统` })
    await userEvent.click(button)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("操作失败，请重试"))
    expect(button).toBeEnabled()
    expect(toast.success).not.toHaveBeenCalled()
    await userEvent.click(button)
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it("does not report success when confirmation returns an unsaved record", async () => {
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))),
      http.post("/api/rss/candidates/:id/confirm", () => HttpResponse.json(candidate)),
    )
    renderPage()
    await userEvent.click(await screen.findByRole("button", { name: "采纳并保存 智能体系统" }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("RSS 候选响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "采纳并保存 智能体系统" })).toBeEnabled()
  })

  it("loads the next server page via the load-more control", async () => {
    const first = Array.from({ length: 30 }, (_, i) => ({
      ...candidate,
      id: `00000000-0000-0000-0000-${String(i + 1).padStart(12, "0")}`,
      title: `候选 ${i + 1}`,
      title_zh: `候选 ${i + 1}`,
    }))
    const second = Array.from({ length: 5 }, (_, i) => ({
      ...candidate,
      id: `00000000-0000-0000-0000-${String(i + 31).padStart(12, "0")}`,
      title: `候选 ${i + 31}`,
      title_zh: `候选 ${i + 31}`,
    }))
    const requestedPages: string[] = []
    server.use(
      http.get("/api/rss/candidates", ({ request }) => {
        const page = new URL(request.url).searchParams.get("page") ?? "1"
        requestedPages.push(page)
        return HttpResponse.json(page === "1" ? pageOf(first, 35, 1) : pageOf(second, 35, 2))
      }),
    )

    renderPage()

    expect(await screen.findByText("候选 30")).toBeInTheDocument()
    expect(screen.queryByText("候选 31")).not.toBeInTheDocument()
    expect(screen.getByText("待审")).toHaveTextContent("35")

    const more = screen.getByRole("button", { name: /加载更多/ })
    expect(more).toHaveTextContent("5")

    await userEvent.click(more)
    expect(await screen.findByText("候选 35")).toBeInTheDocument()
    expect(requestedPages).toEqual(["1", "2"])
    expect(screen.queryByRole("button", { name: /加载更多/ })).not.toBeInTheDocument()
  })

  it("flags malformed page payloads as a local error", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json([candidate])))
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("RSS 内容读取失败")
  })

  it("surfaces a degraded embedding badge with the screening error code", async () => {
    server.use(
      http.get("/api/rss/candidates", () =>
        HttpResponse.json(pageOf([{ ...candidate, embedding_status: "degraded", screening_error: "embedding_http_429" }]))),
    )
    renderPage()

    expect(await screen.findByText("语义降级")).toBeInTheDocument()
    expect(screen.getByText("embedding_http_429")).toBeInTheDocument()
  })

  it("does not flag a completed embedding status", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))))
    renderPage()

    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.queryByText("语义降级")).not.toBeInTheDocument()
  })
})
