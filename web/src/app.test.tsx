import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { MemoryRouter, useLocation } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { App } from "./app"
import { server } from "@/test/server"

function CurrentLocation() {
  const location = useLocation()
  return <output aria-label="当前地址">{location.pathname}{location.search}</output>
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  server.use(http.get("/api/rss/candidates", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 30 })))
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><App /><CurrentLocation /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("App routes", () => {
  it.each(["/", "/articles", "/articles/retired-id"])("routes %s to content discovery", async (path) => {
    renderApp(path)
    expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
    expect(screen.getByLabelText("当前地址")).toHaveTextContent("/rss/candidates")
    expect(screen.queryByRole("link", { name: "稿件" })).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Reven 首页" })).toHaveAttribute("href", "/rss/candidates")
    for (const name of ["CRM", "人才库", "财务", "项目", "SOP（标准作业流程）", "品牌管理"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument()
    }
  })

  it.each(["/login", "/login?next=https%3A%2F%2Fevil.example", "/login?next=%2F%2Fevil.example"])(
    "uses the content discovery landing page after %s", async (path) => {
      server.use(http.post("/api/auth/login", () => HttpResponse.json({ ok: true })))
      renderApp(path)
      await userEvent.type(screen.getByLabelText("管理员密码"), "test-password")
      await userEvent.click(screen.getByRole("button", { name: "登录" }))
      expect(await screen.findByText("候选队列已清空")).toBeInTheDocument()
      expect(screen.getByLabelText("当前地址")).toHaveTextContent("/rss/candidates")
    },
  )

  it("preserves a saved-materials destination across login", async () => {
    server.use(http.post("/api/auth/login", () => HttpResponse.json({ ok: true })))
    renderApp("/login?next=%2Frss%2Fcandidates%3Fstatus%3Dsaved")
    await userEvent.type(screen.getByLabelText("管理员密码"), "test-password")
    await userEvent.click(screen.getByRole("button", { name: "登录" }))
    expect(await screen.findByText("暂无已保存素材")).toBeInTheDocument()
    expect(screen.getByLabelText("当前地址")).toHaveTextContent("/rss/candidates?status=saved")
  })
})
