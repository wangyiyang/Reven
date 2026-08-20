import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { PlaybooksPage } from "./playbooks-page"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const playbook = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "客户首次沟通 SOP",
  kind: "sop",
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
      <PlaybooksPage />
    </QueryClientProvider>,
  )
}

describe("PlaybooksPage", () => {
  beforeAll(() => server.listen())
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())

  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/playbooks", () => HttpResponse.json([playbook])))
  })

  it("shows playbooks", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "SOP / 话术库" })).toBeInTheDocument()
    expect(await screen.findByText("客户首次沟通 SOP")).toBeInTheDocument()
    expect(screen.getByText("CRM、销售")).toBeInTheDocument()
  })

  it("shows empty state when no playbooks", async () => {
    server.use(http.get("/api/playbooks", () => HttpResponse.json([])))

    renderPage()

    expect(await screen.findByText("暂无 Playbook，先沉淀一条 SOP。")).toBeInTheDocument()
  })

  it("creates a playbook and refreshes the list", async () => {
    let requestBody: Record<string, unknown> | null = null
    server.use(
      http.post("/api/playbooks", async ({ request }) => {
        requestBody = (await request.clone().json()) as Record<string, unknown>
        return HttpResponse.json({ ...playbook, id: "22222222-2222-2222-2222-222222222222", ...(requestBody ?? {}) }, { status: 201 })
      }),
      http.get("/api/playbooks", () =>
        HttpResponse.json([playbook, { ...playbook, id: "22222222-2222-2222-2222-222222222222", title: "公众号发布 Checklist" }]),
      ),
    )

    renderPage()
    await userEvent.type(await screen.findByLabelText("标题"), "公众号发布 Checklist")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "类型" }), "checklist")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "状态" }), "正式")
    await userEvent.type(screen.getByLabelText("标签"), "内容, 发布")
    await userEvent.type(screen.getByLabelText("内容"), "- 题图\n- 摘要")
    await userEvent.click(screen.getByRole("button", { name: "添加 Playbook" }))

    expect(await screen.findByText("公众号发布 Checklist")).toBeInTheDocument()
    expect(requestBody).toEqual({
      title: "公众号发布 Checklist",
      kind: "checklist",
      status: "正式",
      body: "- 题图\n- 摘要",
      tags: ["内容", "发布"],
    })
  })
})
