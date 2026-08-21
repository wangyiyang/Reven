import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
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
  push_error: null,
  notion_url: null,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <RssCandidatesPage />
    </QueryClientProvider>,
  )
}

describe("RssCandidatesPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows candidate evidence and source material", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json([candidate])))

    renderPage()

    expect(await screen.findByRole("heading", { name: "RSS 候选工作台" })).toBeInTheDocument()
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
        HttpResponse.json([{ ...candidate, summary_zh: longSummary }]),
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
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json([candidate])))
    renderPage()

    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "展开全文" })).not.toBeInTheDocument()
  })

  it("ignores a candidate and removes it from the queue", async () => {
    let candidates = [candidate]
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(candidates)),
      http.post("/api/rss/candidates/:id/ignore", () => {
        candidates = []
        return HttpResponse.json({ ...candidate, status: "ignored" })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "忽略 智能体系统" }))

    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledWith("已忽略候选")
  })

  it("confirms a candidate and reports the Notion destination", async () => {
    let candidates = [candidate]
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(candidates)),
      http.post("/api/rss/candidates/:id/confirm", () => {
        candidates = []
        return HttpResponse.json({
          item_id: candidate.id,
          notion_page_id: "22222222-2222-2222-2222-222222222222",
          notion_url: "https://www.notion.so/material",
        })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "推送到 Notion 智能体系统" }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(
      "已推送到 Notion Inbox",
      { action: { label: "打开页面", onClick: expect.any(Function) } },
    ))
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
  })

  it("renders at most one batch of candidates with a load-more control", async () => {
    const many = Array.from({ length: 35 }, (_, i) => ({
      ...candidate,
      id: `00000000-0000-0000-0000-${String(i + 1).padStart(12, "0")}`,
      title: `候选 ${i + 1}`,
    }))
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(many)))

    renderPage()

    expect(await screen.findByText("候选 30")).toBeInTheDocument()
    expect(screen.queryByText("候选 31")).not.toBeInTheDocument()

    const more = screen.getByRole("button", { name: /加载更多/ })
    expect(more).toHaveTextContent("5")

    await userEvent.click(more)
    expect(await screen.findByText("候选 35")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /加载更多/ })).not.toBeInTheDocument()
  })
})
