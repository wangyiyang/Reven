import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { SopsPage } from "./sops-page"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const sop = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "客户首次沟通 SOP",
  kind: "procedure",
  status: "试行",
  body: "1. 确认背景",
  tags: ["CRM", "销售"],
  created_at: "2026-08-19T00:00:00Z",
  updated_at: "2026-08-19T00:00:00Z",
}

const server = setupServer()

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SopsPage />
    </QueryClientProvider>,
  )
}

describe("SopsPage", () => {
  beforeAll(() => server.listen())
  afterEach(() => {
    server.resetHandlers()
    vi.unstubAllGlobals()
    Object.defineProperty(window.navigator, "clipboard", { value: undefined, configurable: true })
  })
  afterAll(() => server.close())

  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/sops", () => HttpResponse.json([sop])))
  })

  it("shows sops", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "SOP（标准作业流程）" })).toBeInTheDocument()
    expect((await screen.findAllByText("客户首次沟通 SOP"))[0]).toBeInTheDocument()
    expect(screen.getAllByText("CRM、销售")[0]).toBeInTheDocument()
  })

  it("shows empty state when no sops", async () => {
    server.use(http.get("/api/sops", () => HttpResponse.json([])))

    renderPage()

    expect((await screen.findAllByText("暂无 SOP，先沉淀一条。"))[0]).toBeInTheDocument()
  })

  it("creates a sop and refreshes the list", async () => {
    let requestBody: Record<string, unknown> | null = null
    server.use(
      http.post("/api/sops", async ({ request }) => {
        requestBody = (await request.clone().json()) as Record<string, unknown>
        return HttpResponse.json({ ...sop, id: "22222222-2222-2222-2222-222222222222", ...(requestBody ?? {}) }, { status: 201 })
      }),
      http.get("/api/sops", () =>
        HttpResponse.json([sop, { ...sop, id: "22222222-2222-2222-2222-222222222222", title: "公众号发布 Checklist" }]),
      ),
    )

    renderPage()
    await userEvent.click(screen.getByRole("button", { name: "新建 SOP" }))
    const dialog = await screen.findByRole("dialog")

    await userEvent.type(within(dialog).getByLabelText("标题"), "公众号发布 Checklist")
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "类型" }), "checklist")
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "状态" }), "正式")
    await userEvent.type(within(dialog).getByLabelText("标签"), "内容, 发布")
    await userEvent.type(within(dialog).getByLabelText("内容"), "- 题图\n- 摘要")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加 SOP" }))

    expect((await screen.findAllByText("公众号发布 Checklist"))[0]).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(requestBody).toEqual({
      title: "公众号发布 Checklist",
      kind: "checklist",
      status: "正式",
      body: "- 题图\n- 摘要",
      tags: ["内容", "发布"],
    })
  })

  it("requires sop content before posting", async () => {
    let posted = false
    server.use(http.post("/api/sops", () => {
      posted = true
      return HttpResponse.json(sop, { status: 201 })
    }))

    renderPage()
    await userEvent.click(screen.getByRole("button", { name: "新建 SOP" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(within(dialog).getByLabelText("标题"), "空内容 SOP")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加 SOP" }))

    expect(toast.error).toHaveBeenCalledWith("请填写标题和内容")
    expect(posted).toBe(false)
  })

  it("asks for confirmation via dialog before deleting a sop", async () => {
    let deleted = false
    server.use(http.delete("/api/sops/:id", () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }))

    renderPage()
    expect((await screen.findAllByText("客户首次沟通 SOP"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "删除 客户首次沟通 SOP" })[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("删除 SOP")
    expect(deleted).toBe(false)

    await userEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    expect(deleted).toBe(false)
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getAllByText("客户首次沟通 SOP")[0]).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole("button", { name: "删除 客户首次沟通 SOP" })[0])
    const dialog2 = await screen.findByRole("dialog")
    await userEvent.click(within(dialog2).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("SOP 已删除")
  })

  it("renders mobile cards with view, edit and delete actions", async () => {
    renderPage()

    const card = await screen.findByRole("article", { name: "客户首次沟通 SOP 移动摘要" })
    expect(card).toHaveTextContent("试行")
    expect(card).toHaveTextContent("CRM、销售")

    await userEvent.click(screen.getAllByRole("button", { name: "查看 客户首次沟通 SOP" })[0])
    expect(await screen.findByRole("dialog")).toHaveTextContent("1. 确认背景")
    await userEvent.click(screen.getByRole("button", { name: "关闭" }))

    await userEvent.click(screen.getAllByRole("button", { name: "编辑 客户首次沟通 SOP" })[0])
    const drawer = await screen.findByRole("dialog")
    expect(within(drawer).getByLabelText("标题")).toHaveValue("客户首次沟通 SOP")

    await userEvent.click(within(drawer).getByRole("button", { name: "取消编辑" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())

    await userEvent.click(screen.getAllByRole("button", { name: "删除 客户首次沟通 SOP" })[0])
    expect(await screen.findByRole("dialog")).toHaveTextContent("删除 SOP")
  })

  it("filters sops by kind and status", async () => {
    server.use(
      http.get("/api/sops", ({ request }) => {
        const url = new URL(request.url)
        const kind = url.searchParams.get("kind")
        const status = url.searchParams.get("status")
        return HttpResponse.json(kind === "checklist" || status === "正式" ? [] : [sop])
      }),
    )

    renderPage()
    expect((await screen.findAllByText("客户首次沟通 SOP"))[0]).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型筛选" }), "checklist")
    expect((await screen.findAllByText("暂无 SOP，先沉淀一条。"))[0]).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型筛选" }), "")
    expect((await screen.findAllByText("客户首次沟通 SOP"))[0]).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "状态筛选" }), "正式")
    expect((await screen.findAllByText("暂无 SOP，先沉淀一条。"))[0]).toBeInTheDocument()
  })

  it("searches sops by keyword", async () => {
    server.use(
      http.get("/api/sops", ({ request }) => {
        const query = new URL(request.url).searchParams.get("query")
        return HttpResponse.json(query === "不存在" ? [] : [sop])
      }),
    )

    renderPage()
    expect((await screen.findAllByText("客户首次沟通 SOP"))[0]).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("搜索 SOP"), "不存在")

    expect((await screen.findAllByText("暂无 SOP，先沉淀一条。"))[0]).toBeInTheDocument()
  })

  it("edits a sop and refreshes the list", async () => {
    let sops = [sop]
    let requestBody: unknown
    server.use(
      http.get("/api/sops", () => HttpResponse.json(sops)),
      http.put("/api/sops/:id", async ({ request }) => {
        requestBody = await request.json()
        sops = [{ ...sop, title: "客户首次沟通 SOP v2" }]
        return HttpResponse.json(sops[0])
      }),
    )

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "编辑 客户首次沟通 SOP" }))[0])

    const dialog = await screen.findByRole("dialog")
    const titleInput = within(dialog).getByLabelText("标题")
    await userEvent.clear(titleInput)
    await userEvent.type(titleInput, "客户首次沟通 SOP v2")
    await userEvent.click(within(dialog).getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect((await screen.findAllByText("客户首次沟通 SOP v2"))[0]).toBeInTheDocument()
    expect(requestBody).toMatchObject({ title: "客户首次沟通 SOP v2", kind: "procedure", status: "试行", body: "1. 确认背景", tags: ["CRM", "销售"] })
    expect(toast.success).toHaveBeenCalledWith("SOP 已更新")
  })

  it("opens full content view and copies the body", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true })
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true })

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "查看 客户首次沟通 SOP" }))[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByText("1. 确认背景")).toBeInTheDocument()
    expect(within(dialog).getByText("CRM、销售")).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole("button", { name: "复制内容" }))
    expect(writeText).toHaveBeenCalledWith("1. 确认背景")
    expect(toast.success).toHaveBeenCalledWith("内容已复制")
  })
})
