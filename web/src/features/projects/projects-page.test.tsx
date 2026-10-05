import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

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
  github_repo: "wangyiyang/OLL",
  notes: null as string | null,
  created_at: "2026-08-19T00:00:00Z",
  updated_at: "2026-08-19T00:00:00Z",
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectsPage />
    </QueryClientProvider>,
  )
}

describe("ProjectsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    server.use(
      http.get("/api/projects", () => HttpResponse.json([project])),
    )
  })

  it("shows projects", async () => {
    renderPage()

    expect(await screen.findByRole("heading", { name: "项目库" })).toBeInTheDocument()
    expect((await screen.findAllByText("OLL 交付"))[0]).toBeInTheDocument()
    expect(screen.getByText("wangyiyang/OLL")).toBeInTheDocument()
    expect(screen.queryByLabelText("Notion URL")).not.toBeInTheDocument()
  })

  it("shows empty state when no projects", async () => {
    server.use(http.get("/api/projects", () => HttpResponse.json([])))

    renderPage()

    expect((await screen.findAllByText("暂无项目，先添加一个。"))[0]).toBeInTheDocument()
  })

  it("opens the create drawer via 新建项目 and closes it without saving", async () => {
    renderPage()

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "新建项目" }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("新建项目")
    expect(within(dialog).getByLabelText("名称")).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole("button", { name: "关闭抽屉" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
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
    await userEvent.click(screen.getByRole("button", { name: "新建项目" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(within(dialog).getByLabelText("名称"), "Reven 工作台")
    await userEvent.type(within(dialog).getByLabelText("目标"), "一人公司操作系统")
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "状态" }), "进行中")
    await userEvent.type(within(dialog).getByLabelText("部门"), "工程交付")
    fireEvent.change(within(dialog).getByLabelText("截止日"), { target: { value: "2026-12-31" } })
    await userEvent.type(within(dialog).getByLabelText("GitHub 仓库"), "wangyiyang/Reven")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加项目" }))

    expect((await screen.findAllByText("Reven 工作台"))[0]).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(toast.success).toHaveBeenCalledWith("项目已添加")
    expect(requestBody).toEqual({
      name: "Reven 工作台",
      goal: "一人公司操作系统",
      status: "进行中",
      department: "工程交付",
      due_on: "2026-12-31",
      github_repo: "wangyiyang/Reven",
      notes: null,
    })
  })

  it("rejects invalid GitHub links before posting", async () => {
    let posted = false
    server.use(http.post("/api/projects", () => {
      posted = true
      return HttpResponse.json(project, { status: 201 })
    }))

    renderPage()
    await userEvent.click(screen.getByRole("button", { name: "新建项目" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(within(dialog).getByLabelText("名称"), "坏链接项目")
    await userEvent.type(within(dialog).getByLabelText("GitHub 仓库"), "bad url")
    await userEvent.click(within(dialog).getByRole("button", { name: "添加项目" }))

    expect(toast.error).toHaveBeenCalledWith("GitHub 仓库格式不正确")
    expect(posted).toBe(false)
  })

  it("asks for confirmation via dialog before deleting a project", async () => {
    let deleted = false
    server.use(http.delete("/api/projects/:id", () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }))

    renderPage()
    expect((await screen.findAllByText("OLL 交付"))[0]).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "删除 OLL 交付" })[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("删除项目")
    expect(deleted).toBe(false)

    await userEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    expect(deleted).toBe(false)
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getAllByText("OLL 交付")[0]).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole("button", { name: "删除 OLL 交付" })[0])
    const dialog2 = await screen.findByRole("dialog")
    await userEvent.click(within(dialog2).getByRole("button", { name: /确认删除/ }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(toast.success).toHaveBeenCalledWith("项目已删除")
  })

  it("filters projects by status", async () => {
    server.use(
      http.get("/api/projects", ({ request }) => {
        const status = new URL(request.url).searchParams.get("status")
        return HttpResponse.json(status === "已完成" ? [] : [project])
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 交付"))[0]).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "状态筛选" }), "已完成")

    expect((await screen.findAllByText("暂无项目，先添加一个。"))[0]).toBeInTheDocument()
  })

  it("searches projects by keyword", async () => {
    server.use(
      http.get("/api/projects", ({ request }) => {
        const query = new URL(request.url).searchParams.get("query")
        return HttpResponse.json(query === "不存在" ? [] : [project])
      }),
    )

    renderPage()
    expect((await screen.findAllByText("OLL 交付"))[0]).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText("搜索项目"))
    await userEvent.type(screen.getByLabelText("搜索项目"), "不存在")

    expect((await screen.findAllByText("暂无项目，先添加一个。"))[0]).toBeInTheDocument()
  })

  it("edits a project and refreshes the list", async () => {
    let projects = [project]
    let requestBody: unknown
    server.use(
      http.get("/api/projects", () => HttpResponse.json(projects)),
      http.put("/api/projects/:id", async ({ request }) => {
        requestBody = await request.json()
        projects = [{ ...project, name: "OLL 二期交付" }]
        return HttpResponse.json(projects[0])
      }),
    )

    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "编辑 OLL 交付" }))[0])

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("编辑项目")
    const nameInput = within(dialog).getByLabelText("名称")
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, "OLL 二期交付")
    await userEvent.click(within(dialog).getByRole("button", { name: "保存修改" }))

    expect((await screen.findAllByText("OLL 二期交付"))[0]).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(requestBody).toMatchObject({ name: "OLL 二期交付", github_repo: "wangyiyang/OLL", status: "进行中" })
    expect(toast.success).toHaveBeenCalledWith("项目已更新")
  })

  it("canceling edit closes the drawer and keeps the list unchanged", async () => {
    renderPage()
    await userEvent.click((await screen.findAllByRole("button", { name: "编辑 OLL 交付" }))[0])

    const dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByRole("button", { name: "取消编辑" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect((await screen.findAllByText("OLL 交付"))[0]).toBeInTheDocument()
  })

  it("renders the GitHub repo as an external link", async () => {
    renderPage()

    const link = await screen.findByRole("link", { name: "wangyiyang/OLL" })
    expect(link).toHaveAttribute("href", "https://github.com/wangyiyang/OLL")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"))
  })
})
