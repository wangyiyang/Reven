import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { toast } from "sonner"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { BrandPage } from "./brand-page"
import { server } from "@/test/server"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const publishedBrand = {
  id: "11111111-1111-1111-1111-111111111111",
  version: 3,
  status: "已发布",
  payload: {
    brand_name: "翊行代码",
    intro: "",
    default_author: "王一羊",
    handle: "",
    website: "",
    tagline: "把内容工程化",
    colors: { primary: "#0F4C81", text: "#0A0A0A", background: "#FAFAFA" },
    fonts: { body: "sans-serif", mono: "" },
    style_notes: "",
  },
  source: "手工创建",
  published_at: "2026-09-01T00:00:00Z",
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
}

const qrAsset = {
  id: "22222222-2222-2222-2222-222222222222",
  purpose: "二维码",
  label: "公众号二维码",
  enabled: true,
  public_url: "https://cdn.example.com/qr.png",
  sha256: "a".repeat(64),
  mime_type: "image/png",
  byte_size: 1024,
  width: 430,
  height: 430,
  source: "手工上传",
  created_at: "2026-09-01T00:00:00Z",
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BrandPage />
    </QueryClientProvider>,
  )
}

function mockBaseline() {
  server.use(
    http.get("/api/brand/profile", () => HttpResponse.json({ published: publishedBrand, draft: null })),
    http.get("/api/brand/assets", () => HttpResponse.json([qrAsset])),
    http.get("/api/brand/templates/wechat", () =>
      HttpResponse.json({
        published: null,
        draft: {
          id: "33333333-3333-3333-3333-333333333333",
          channel: "微信公众号",
          version: 1,
          status: "草稿",
          payload: {
            theme: { primary_color: "#00E676", font_family: "", font_size: 16 },
            footer_modules: [{ key: "follow", type: "text", content: "欢迎关注", asset_id: null, enabled: true }],
          },
          published_at: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        },
      }),
    ),
    http.get("/api/brand/templates/blog", () => HttpResponse.json({ published: null, draft: null })),
    http.get("/api/brand/import/runs", () => HttpResponse.json([])),
  )
}

describe("BrandPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("展示已发布品牌档案并支持保存草稿", async () => {
    mockBaseline()
    let saved: unknown = null
    server.use(
      http.put("/api/brand/profile/draft", async ({ request }) => {
        saved = await request.json()
        return HttpResponse.json(publishedBrand)
      }),
    )
    renderPage()

    expect(await screen.findByDisplayValue("翊行代码")).toBeInTheDocument()
    expect(screen.getByDisplayValue("王一羊")).toBeInTheDocument()
    expect(screen.getByText(/当前已发布 v3/)).toBeInTheDocument()

    const user = userEvent.setup()
    const authorInput = screen.getByLabelText("默认署名")
    await user.clear(authorInput)
    await user.type(authorInput, "翊行")
    // 页面含档案与模板两个“保存草稿”，第一个是品牌档案的
    await user.click(screen.getAllByRole("button", { name: "保存草稿" })[0])

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("品牌草稿已保存"))
    expect((saved as { default_author?: string })?.default_author).toBe("翊行")
  })

  it("无已发布档案时提示 legacy 回落", async () => {
    server.use(http.get("/api/brand/profile", () => HttpResponse.json({ published: null, draft: null })))
    renderPage()
    expect(await screen.findByText(/legacy 回落/)).toBeInTheDocument()
  })

  it("素材库展示并可停用素材", async () => {
    mockBaseline()
    let patched: unknown = null
    server.use(
      http.patch("/api/brand/assets/:id", async ({ request }) => {
        patched = await request.json()
        return HttpResponse.json({ ...qrAsset, enabled: false })
      }),
    )
    renderPage()

    expect(await screen.findByText("公众号二维码")).toBeInTheDocument()
    expect(screen.getByText("430×430 · 1KB · 手工上传")).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "停用" }))
    await waitFor(() => expect(patched).toEqual({ enabled: false }))
  })

  it("微信模板草稿载入文末模块并可保存", async () => {
    mockBaseline()
    const saved: { current: { footer_modules?: unknown[] } | null } = { current: null }
    server.use(
      http.put("/api/brand/templates/wechat/draft", async ({ request }) => {
        saved.current = (await request.json()) as { footer_modules?: unknown[] }
        return HttpResponse.json({})
      }),
    )
    renderPage()

    expect(await screen.findByDisplayValue("欢迎关注")).toBeInTheDocument()
    expect(screen.getByText(/存在未发布草稿/)).toBeInTheDocument()

    const user = userEvent.setup()
    const buttons = screen.getAllByRole("button", { name: "保存草稿" })
    await user.click(buttons[1]) // 第一个是品牌档案的
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("微信模板草稿已保存"))
    expect(saved.current?.footer_modules).toHaveLength(1)
  })

  it("切换到博客模板标签页", async () => {
    mockBaseline()
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole("tab", { name: "个人博客" }))
    expect(await screen.findByLabelText("博客署名")).toBeInTheDocument()
    expect(screen.getByText(/尚未发布，该渠道使用默认样式与行为/)).toBeInTheDocument()
  })
})
