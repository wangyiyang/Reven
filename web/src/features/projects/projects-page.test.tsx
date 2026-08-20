import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { ProjectsPage } from "./projects-page"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const project = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "OLL 交付",
  goal: "9 月底完成验收",
  status: "进行中",
  department: "工程交付",
  due_on: "2026-09-30",
  notion_url: null as string | null,
  github_repo: "wangyiyang/OLL",
  notes: null as string | null,
  created_at: "2026-08-19T00:00:00Z",
  updated_at: "2026-08-19T00:00:00Z",
}

const server = setupServer()

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectsPage />
    </QueryClientProvider>,
  )
}

describe("ProjectsPage", () => {
  beforeAll(() => server.listen())
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())

  beforeEach(() => {
    vi.clearAllMocks()
    server.use(
      http.get("/api/projects", () => HttpResponse.json([project])),
    )
  })

  it("shows projects", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "项目库" })).toBeInTheDocument()
    expect(await screen.findByText("OLL 交付")).toBeInTheDocument()
    expect(screen.getByText("wangyiyang/OLL")).toBeInTheDocument()
  })

  it("shows empty state when no projects", async () => {
    server.use(http.get("/api/projects", () => HttpResponse.json([])))

    renderPage()

    expect(await screen.findByText("暂无项目，先添加一个。")).toBeInTheDocument()
  })

  it("creates a project and refreshes the list", async () => {
    let requestBody: Record<string, unknown> | null = null
    server.use(
      http.post("/api/projects", async ({ request }) => {
        requestBody = (await request.clone().json()) as Record<string, unknown>
        return HttpResponse.json({ ...project, id: "33333333-3333-3333-3333-333333333333", ...(requestBody ?? {}) }, { status: 201 })
      }),
      http.get("/api/projects", () =>
        HttpResponse.json([project, { ...project, id: "33333333-3333-3333-3333-333333333333", name: "Reven 工作台" }]),
      ),
    )

    renderPage()
    await userEvent.type(await screen.findByLabelText("名称"), "Reven 工作台")
    await userEvent.type(screen.getByLabelText("目标"), "一人公司操作系统")
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "状态" }), "进行中")
    await userEvent.type(screen.getByLabelText("部门"), "工程交付")
    fireEvent.change(screen.getByLabelText("截止日"), { target: { value: "2026-12-31" } })
    await userEvent.type(screen.getByLabelText("GitHub 仓库"), "wangyiyang/Reven")
    await userEvent.click(screen.getByRole("button", { name: "添加项目" }))

    expect(await screen.findByText("Reven 工作台")).toBeInTheDocument()
    expect(requestBody).toEqual({
      name: "Reven 工作台",
      goal: "一人公司操作系统",
      status: "进行中",
      department: "工程交付",
      due_on: "2026-12-31",
      notion_url: null,
      github_repo: "wangyiyang/Reven",
      notes: null,
    })
  })
})
