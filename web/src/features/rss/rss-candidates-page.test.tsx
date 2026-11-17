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
  record_id: "rec_1",
  source_name: "Example",
  url: "https://example.com/agent-systems",
  title: "智能体系统",
  summary: "一份关于智能体系统的实践指南。",
  published_at: "2026-08-11T01:00:00Z",
  status: "candidate",
  matched_keywords: ["AI 智能体"],
  archived_at: "2026-08-11T02:00:00Z",
  dedupe_key: "url:key-1",
}

function pageOf(items: unknown[], total = items.length, nextCursor: string | null = null) {
  return { items, total, next_cursor: nextCursor }
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

  it("shows candidate title, summary, keywords and source link", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))))

    renderPage()

    expect(await screen.findByRole("heading", { name: "RSS 内容发现" })).toBeInTheDocument()
    expect(await screen.findByRole("heading", { name: "智能体系统" })).toBeInTheDocument()
    expect(screen.getByText("一份关于智能体系统的实践指南。")).toBeInTheDocument()
    expect(screen.getByText("AI 智能体")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "查看原文" })).toHaveAttribute(
      "href",
      "https://example.com/agent-systems",
    )
  })

  it("clamps long summaries behind an expand toggle", async () => {
    const longSummary = "这是一段很长的摘要。".repeat(60)
    server.use(
      http.get("/api/rss/candidates", () =>
        HttpResponse.json(pageOf([{ ...candidate, summary: longSummary }])),
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
      http.post("/api/rss/candidates/:recordId/ignore", () => {
        items = []
        return HttpResponse.json({ ...candidate, status: "ignored" })
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "忽略 智能体系统" }))

    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledWith("已忽略候选")
  })

  it("saves an approved candidate and makes it available in saved materials", async () => {
    let saved = false
    const savedItem = { ...candidate, status: "saved" }
    const requestedStatuses: string[] = []
    server.use(
      http.get("/api/rss/candidates", ({ request }) => {
        const status = new URL(request.url).searchParams.get("status") ?? ""
        requestedStatuses.push(status)
        const items = status === "saved" ? (saved ? [savedItem] : []) : (saved ? [] : [candidate])
        return HttpResponse.json(pageOf(items))
      }),
      http.post("/api/rss/candidates/:recordId/confirm", () => {
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
      http.post(`/api/rss/candidates/:recordId/${action}`, () => {
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

  it("toasts and refreshes the list on a 409 conflict", async () => {
    let listCalls = 0
    let conflicted = false
    server.use(
      http.get("/api/rss/candidates", () => {
        listCalls += 1
        return HttpResponse.json(pageOf(conflicted ? [] : [candidate]))
      }),
      http.post("/api/rss/candidates/:recordId/confirm", () => {
        conflicted = true
        return HttpResponse.json(
          { code: "RSS_CANDIDATE_NOT_SAVABLE", message: "RSS 候选状态已变更，当前状态不允许保存（请刷新列表）" },
          { status: 409 },
        )
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "采纳并保存 智能体系统" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("该条已在飞书侧变更，已刷新"))
    expect(toast.success).not.toHaveBeenCalled()
    // 冲突后列表被 invalidate：重新拉取并显示刷新后的空队列
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(listCalls).toBeGreaterThanOrEqual(2)
  })

  it("does not report success when confirmation returns an unsaved record", async () => {
    server.use(
      http.get("/api/rss/candidates", () => HttpResponse.json(pageOf([candidate]))),
      http.post("/api/rss/candidates/:recordId/confirm", () => HttpResponse.json(candidate)),
    )
    renderPage()
    await userEvent.click(await screen.findByRole("button", { name: "采纳并保存 智能体系统" }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("RSS 候选响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "采纳并保存 智能体系统" })).toBeEnabled()
  })

  it("loads the next server page via the cursor-based load-more control", async () => {
    const first = Array.from({ length: 30 }, (_, i) => ({
      ...candidate,
      record_id: `rec_${i + 1}`,
      title: `候选 ${i + 1}`,
    }))
    const second = Array.from({ length: 5 }, (_, i) => ({
      ...candidate,
      record_id: `rec_${i + 31}`,
      title: `候选 ${i + 31}`,
    }))
    const requestedCursors: (string | null)[] = []
    server.use(
      http.get("/api/rss/candidates", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor")
        requestedCursors.push(cursor)
        return HttpResponse.json(cursor === null ? pageOf(first, 35, "tok-2") : pageOf(second, 35, null))
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
    expect(requestedCursors).toEqual([null, "tok-2"])
    expect(screen.queryByRole("button", { name: /加载更多/ })).not.toBeInTheDocument()
  })

  it("flags malformed page payloads as a local error", async () => {
    server.use(http.get("/api/rss/candidates", () => HttpResponse.json([candidate])))
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("RSS 内容读取失败")
  })
})
