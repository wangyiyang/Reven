import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, HttpResponse, http } from "msw"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/server"
import { ArticleDetailPage } from "./article-detail-page"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const id = "11111111-1111-4111-8111-111111111111"
const jobId = "22222222-2222-4222-8222-222222222222"
const article = {
  id,
  title: "测试稿件",
  notion_url: "https://www.notion.so/safe-page",
  notion_status: "待发布",
  automation_status: "失败",
  target_channels: ["个人博客", "微信公众号"],
  planned_at: null,
  notion_last_edited_at: "2026-07-30T00:00:00Z",
  last_synced_at: "2026-07-30T00:01:00Z",
  cover_valid: false,
  content_sync: {
    status: "已同步",
    outputs_enabled: true,
    error: null,
    current_snapshot: {
      id: "33333333-3333-4333-8333-333333333333",
      synced_at: "2026-07-30T00:01:00Z",
      source_last_edited_at: "2026-07-30T00:00:00Z",
      content_hash: "b".repeat(64),
      character_count: 1200,
      media_count: 3,
    },
    latest_run: null,
  },
  blog_status: "失败",
  wechat_status: "草稿已生成",
  notion_metadata: {},
  cover_metadata: {},
  last_error: "已脱敏错误",
  content_hash: "a".repeat(64),
  validation_errors: [{ message: "缺少封面", field: "封面图片" }],
  validation_warnings: [],
  blog: { status: "失败", error: "构建失败", result: {} },
  wechat: { status: "草稿已生成", error: null, result: { media_id: "media-1" } },
  jobs: [{ id: jobId, overall_status: "失败", target_channels: ["个人博客", "微信公众号"], scheduled_at: "2026-07-30T00:00:00Z", content_hash: "a".repeat(64), blog_status: "失败", wechat_status: "草稿已生成" }],
  jobs_total: 57,
  jobs_has_more: true,
}

describe("ArticleDetailPage", () => {
  beforeEach(() => vi.clearAllMocks())

  it("shows five detail concerns, bounded history, and only failed-channel retry", async () => {
    useDetailHandlers()
    renderPage()

    expect(await screen.findByRole("heading", { name: "测试稿件" })).toBeInTheDocument()
    expect(screen.getByText("未通过：发布将被阻止")).toBeInTheDocument()
    expect(screen.getAllByText("缺少封面").length).toBeGreaterThanOrEqual(1)
    expect(await screen.findByText("微信草稿 media_id")).toBeInTheDocument()
    expect(screen.getByText(/共 57 条。更早记录未在本页加载。/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重试个人博客" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "重试微信公众号" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "取消等待任务" })).not.toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "下一步怎么处理" })).toBeInTheDocument()
    expect(screen.getByText("检查 GitHub 集成、PR 与构建日志，修复后仅重试博客渠道。")).toBeInTheDocument()
  })

  it("shows sync failure with cover advice in recovery guidance", async () => {
    useDetailHandlers({
      articlePatch: {
        last_error: null,
        validation_errors: [],
        blog: null,
        content_sync: { ...article.content_sync, error: "同步需要可下载的封面" },
      },
    })
    renderPage()

    expect((await screen.findAllByText("同步需要可下载的封面")).length).toBeGreaterThan(0)
    expect(screen.getByText("在 Notion 补充封面图片并重新同步，然后重试失败渠道。")).toBeInTheDocument()
  })

  it("shows publish-blocking validation in recovery guidance even without sync/job errors (#72)", async () => {
    useDetailHandlers({
      articlePatch: {
        last_error: null,
        content_sync: { ...article.content_sync, error: null },
        blog: null,
        wechat: null,
        jobs: [],
        validation_errors: [{ code: "cover_missing", message: "请配置并确认封面可下载", field: "cover" }],
      },
    })
    renderPage()

    await screen.findByRole("heading", { name: "测试稿件" })
    // 校验阻塞项必须出现在「下一步怎么处理」，不能显示「当前没有需要处理的错误」
    expect(screen.queryByText("当前没有需要处理的错误。")).not.toBeInTheDocument()
    expect(screen.getAllByText("发布前校验").length).toBeGreaterThanOrEqual(2) // 校验区标题 + 指引项来源
    expect(screen.getAllByText("请配置并确认封面可下载").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("在 Notion 补充封面图片并重新同步，然后重试失败渠道。")).toBeInTheDocument()
  })

  it("renders returned HTML only in a fully sandboxed iframe", async () => {
    useDetailHandlers()
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "生成微信预览" }))

    const frame = await screen.findByTitle("测试稿件的微信预览")
    expect(frame).toHaveAttribute("sandbox", "")
    expect(frame).toHaveAttribute("srcdoc", "<script>window.evil=true</script><h1>稿件</h1>")
    expect(document.querySelector("main script")).toBeNull()
  })

  it("copies portable Markdown from the validated current snapshot", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true })
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } })
    useDetailHandlers()
    server.use(
      http.post("/api/articles/:id/portable-markdown", () =>
        HttpResponse.json({ markdown: "# 测试稿件\n\n![图](https://assets.example/image.png)\n" }),
      ),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "复制 Markdown" }))

    await vi.waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("# 测试稿件\n\n![图](https://assets.example/image.png)\n"),
    )
    expect(toast.success).toHaveBeenCalledWith("已复制")
  })

  it("shows the same Markdown for manual copy when clipboard permission is unavailable", async () => {
    const markdown = "# 测试稿件\n\n正文与 [YouTube](https://youtube.com/watch?v=1)\n"
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true })
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new DOMException("denied")) },
    })
    useDetailHandlers()
    server.use(
      http.post("/api/articles/:id/portable-markdown", () => HttpResponse.json({ markdown })),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "复制 Markdown" }))

    expect(await screen.findByRole("dialog", { name: "手动复制 Markdown" })).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "可移植 Markdown 内容" })).toHaveValue(markdown)
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("请检查浏览器权限"))
  })

  it("refreshes and disables copying when the snapshot becomes stale during validation", async () => {
    let stale = false
    useDetailHandlers()
    server.use(
      http.get("/api/articles/:id", () => HttpResponse.json({
        ...article,
        content_sync: stale
          ? { ...article.content_sync, status: "已过期", outputs_enabled: false }
          : article.content_sync,
      })),
      http.post("/api/articles/:id/portable-markdown", () => {
        stale = true
        return HttpResponse.json(
          { code: "SNAPSHOT_STALE", message: "Notion 内容已变化，请重新同步" },
          { status: 409 },
        )
      }),
    )
    renderPage()

    const copyButton = await screen.findByRole("button", { name: "复制 Markdown" })
    expect(copyButton).toBeEnabled()
    await userEvent.click(copyButton)

    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith("Notion 内容已变化，请重新同步"))
    await vi.waitFor(() => expect(copyButton).toBeDisabled())
  })

  it("keeps preview and publication retry disabled until the latest snapshot is valid", async () => {
    useDetailHandlers({
      articlePatch: {
        content_sync: {
          status: "同步失败",
          outputs_enabled: false,
          error: "附件下载失败",
          current_snapshot: article.content_sync.current_snapshot,
          latest_run: null,
        },
      },
    })
    renderPage()

    expect(await screen.findByRole("button", { name: "复制 Markdown" })).toBeDisabled()
    expect(await screen.findByRole("button", { name: "生成微信预览" })).toBeDisabled()
    expect(await screen.findByRole("button", { name: "重试个人博客" })).toBeDisabled()
    expect(screen.getAllByText("附件下载失败")).toHaveLength(3)
    expect(screen.getByRole("button", { name: "同步内容" })).toBeEnabled()
  })

  it("requires an explicit resume after snapshot preparation blocked the publication", async () => {
    let requestedChannels: unknown = null
    useDetailHandlers({
      jobPatch: {
        overall_status: "阻塞",
        blog_status: "待处理",
        wechat_status: "待处理",
        blog: { status: "待处理", error: null, result: {} },
        wechat: { status: "待处理", error: null, result: {} },
      },
    })
    server.use(http.post("/api/articles/:id/jobs/:jobId/retry", async ({ request }) => {
      requestedChannels = (await request.json() as { channels: unknown }).channels
      return HttpResponse.json({ ok: true, job_id: jobId })
    }))
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "恢复发布" }))

    await vi.waitFor(() => expect(requestedChannels).toEqual(["个人博客", "微信公众号"]))
  })

  it("reports clipboard permission failure without degrading to plain text", async () => {
    useDetailHandlers()
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: false })
    renderPage()
    await userEvent.click(await screen.findByRole("button", { name: "生成微信预览" }))
    await userEvent.click(await screen.findByRole("button", { name: "复制富文本" }))

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("需要 HTTPS"))
  })

  it("does not show task actions before the latest job detail is confirmed", async () => {
    useDetailHandlers({ jobDelay: 100 })
    renderPage()

    expect(await screen.findByLabelText("正在读取最近任务")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "重试个人博客" })).not.toBeInTheDocument()
  })

  it("shows a local retry when the latest job response is malformed", async () => {
    useDetailHandlers({ malformedJob: true })
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("任务详情响应格式无效")
    expect(screen.getByRole("button", { name: "重试任务详情" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "重试个人博客" })).not.toBeInTheDocument()
  })

  it("redacts sensitive errors and offers a stable fallback action", async () => {
    useDetailHandlers({
      articlePatch: {
        last_error: "token=raw-secret https://signed.example/private",
        validation_errors: [],
      },
      jobPatch: { blog: { status: "失败", error: "password=raw-password", result: {} } },
    })
    renderPage()

    expect(await screen.findByText("token=*** [已脱敏地址]")).toBeInTheDocument()
    expect(await screen.findAllByText("password=***")).toHaveLength(2)
    expect(screen.queryByText(/raw-secret|raw-password|signed\.example/)).not.toBeInTheDocument()
    expect(screen.getByText("检查集成配置或打开 Notion 修复内容，确认后重试对应失败渠道。")).toBeInTheDocument()
  })

  it("prevents duplicate retry requests and success toasts", async () => {
    let calls = 0
    useDetailHandlers()
    server.use(http.post("/api/articles/:id/jobs/:jobId/retry", async () => {
      calls += 1
      await delay(80)
      return HttpResponse.json({ ok: true, job_id: jobId })
    }))
    renderPage()

    await userEvent.dblClick(await screen.findByRole("button", { name: "重试个人博客" }))

    await vi.waitFor(() => expect(calls).toBe(1))
    await vi.waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1))
  })

  it("shows a recoverable page error for malformed article details", async () => {
    server.use(http.get("/api/articles/:id", () => HttpResponse.json({ id })))
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("稿件响应格式无效")
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument()
  })

  it("reports malformed preview and action responses without false success", async () => {
    useDetailHandlers()
    server.use(
      http.post("/api/articles/:id/preview/wechat", () => HttpResponse.json({ html: null })),
      http.post("/api/articles/:id/jobs/:jobId/retry", () => HttpResponse.json({ ok: true })),
    )
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "生成微信预览" }))
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith("微信预览响应格式无效"))
    await userEvent.click(await screen.findByRole("button", { name: "重试个人博客" }))
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith("任务操作响应格式无效"))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it("prevents duplicate preview requests", async () => {
    let calls = 0
    useDetailHandlers()
    server.use(http.post("/api/articles/:id/preview/wechat", async () => {
      calls += 1
      await delay(80)
      return HttpResponse.json({ html: "<h1>预览</h1>" })
    }))
    renderPage()

    await userEvent.dblClick(await screen.findByRole("button", { name: "生成微信预览" }))

    await vi.waitFor(() => expect(calls).toBe(1))
    expect(await screen.findByTitle("测试稿件的微信预览")).toBeInTheDocument()
  })

  it("rejects a timezone-naive article date without rendering Intl output", async () => {
    useDetailHandlers({ articlePatch: { planned_at: "2026-07-30T08:01:00" } })
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("稿件响应格式无效")
  })

  it("shows a local error for an invalid job date", async () => {
    useDetailHandlers({ jobPatch: { created_at: "invalid-date" } })
    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("任务详情响应格式无效")
    expect(screen.queryByRole("button", { name: "重试个人博客" })).not.toBeInTheDocument()
  })
})

function useDetailHandlers(options: {
  jobDelay?: number
  malformedJob?: boolean
  articlePatch?: Record<string, unknown>
  jobPatch?: Record<string, unknown>
} = {}) {
  server.use(
    http.get("/api/articles/:id", () => HttpResponse.json({ ...article, ...options.articlePatch })),
    http.get("/api/articles/:id/jobs/:jobId", async () => {
      if (options.jobDelay) await delay(options.jobDelay)
      if (options.malformedJob) return HttpResponse.json({ id: jobId })
      return HttpResponse.json({
      ...article.jobs[0],
      article_id: id,
      snapshot_metadata: {},
      blog: article.blog,
      wechat: article.wechat,
      wechat_html: "<h1>旧快照</h1>",
      attempt_count: 1,
      created_at: "2026-07-30T00:00:00Z",
      updated_at: "2026-07-30T00:01:00Z",
      ...options.jobPatch,
    })
    }),
    http.post("/api/articles/:id/preview/wechat", () => HttpResponse.json({ html: "<script>window.evil=true</script><h1>稿件</h1>" })),
  )
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/articles/${id}`]}>
        <Routes><Route element={<ArticleDetailPage />} path="/articles/:articleId" /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
