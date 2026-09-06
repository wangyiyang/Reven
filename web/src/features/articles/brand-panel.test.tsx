import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { BrandPanel } from "./brand-panel"
import type { ArticleDetail, JobDetail } from "./types"
import { server } from "@/test/server"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const article = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  selected_cover_asset_id: null,
} as unknown as ArticleDetail

const boundJob = {
  brand_binding_key: "abc123",
  brand: {
    binding_key: "abc123",
    version_fingerprint: { brand_version: 1, wechat_template_version: 1, blog_template_version: null },
  },
} as unknown as JobDetail

const legacyJob = {
  brand_binding_key: "legacy",
  brand: null,
} as unknown as JobDetail

function renderPanel(job: JobDetail | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BrandPanel article={article} job={job} />
    </QueryClientProvider>,
  )
}

function mockProfile(version: number) {
  server.use(
    http.get("/api/brand/profile", () =>
      HttpResponse.json({
        published: {
          id: "11111111-1111-1111-1111-111111111111",
          version,
          status: "已发布",
          payload: {},
          source: "手工创建",
          published_at: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        },
        draft: null,
      }),
    ),
    http.get("/api/brand/templates/wechat", () => HttpResponse.json({ published: null, draft: null })),
    http.get("/api/brand/templates/blog", () => HttpResponse.json({ published: null, draft: null })),
  )
}

describe("BrandPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("冻结版本落后于当前版本时提示并提供重新生成", async () => {
    mockProfile(2)
    let regenerated = false
    server.use(
      http.post(`/api/articles/${article.id}/jobs`, () => {
        regenerated = true
        return HttpResponse.json({ ok: true, job_id: article.id })
      }),
    )
    renderPanel(boundJob)

    expect(await screen.findByText(/品牌配置已更新到 v2/)).toBeInTheDocument()
    expect(screen.getByText("品牌 v1")).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "按当前品牌重新生成任务" }))
    await waitFor(() => expect(regenerated).toBe(true))
    await waitFor(() => expect(toast.success).toHaveBeenCalled())
  })

  it("冻结版本与当前一致时不提示", async () => {
    mockProfile(1)
    renderPanel(boundJob)
    expect(await screen.findByText("品牌 v1")).toBeInTheDocument()
    expect(screen.queryByText(/品牌配置已更新/)).not.toBeInTheDocument()
  })

  it("legacy 任务展示未绑定说明", async () => {
    mockProfile(1)
    renderPanel(legacyJob)
    expect(await screen.findByText("legacy（未绑定品牌）")).toBeInTheDocument()
    expect(screen.getByText(/该任务按 legacy 默认行为发布/)).toBeInTheDocument()
  })

  it("封面选择对话框列出素材并提交选择", async () => {
    mockProfile(1)
    let posted: unknown = null
    server.use(
      http.get("/api/brand/assets", () =>
        HttpResponse.json([
          {
            id: "22222222-2222-2222-2222-222222222222",
            purpose: "封面",
            label: "默认封面",
            enabled: true,
            public_url: "https://cdn.example.com/cover.png",
            sha256: "a".repeat(64),
            mime_type: "image/png",
            byte_size: 2048,
            width: 900,
            height: 383,
            source: "手工上传",
            created_at: "2026-09-01T00:00:00Z",
          },
        ]),
      ),
      http.post(`/api/articles/${article.id}/cover`, async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ ok: true })
      }),
    )
    renderPanel(boundJob)

    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "选择品牌封面" }))
    await user.click(await screen.findByRole("button", { name: /默认封面/ }))
    await waitFor(() => expect(posted).toEqual({ asset_id: "22222222-2222-2222-2222-222222222222" }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("封面选择已更新"))
  })
})
