import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AppShell } from "./app-shell"

function renderShell() {
  return render(
    <MemoryRouter>
      <AppShell>
        <div>内容</div>
      </AppShell>
    </MemoryRouter>,
  )
}

describe("AppShell 移动端布局", () => {
  it("移动端头部允许换行，避免整页横向溢出", () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    const headerRow = nav.parentElement
    expect(headerRow?.className).toContain("flex-wrap")
    expect(headerRow?.className).toContain("lg:flex-nowrap")
  })

  it("移动端导航独占一行且可横向滚动，桌面端恢复纵向栏内布局", () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    expect(nav.className).toContain("w-full")
    expect(nav.className).toContain("overflow-x-auto")
    expect(nav.className).toContain("lg:w-auto")
    expect(nav.className).toContain("lg:overflow-visible")
  })
})
