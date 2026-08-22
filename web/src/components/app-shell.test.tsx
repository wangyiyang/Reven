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
    const headerRow = nav.parentElement?.parentElement
    expect(headerRow?.className).toContain("flex-wrap")
    expect(headerRow?.className).toContain("lg:flex-nowrap")
  })

  it("移动端导航独占一行且可横向滚动，桌面端恢复纵向栏内布局", () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    const wrapper = nav.parentElement
    expect(wrapper?.className).toContain("w-full")
    expect(wrapper?.className).toContain("lg:w-auto")
    expect(nav.className).toContain("overflow-x-auto")
    expect(nav.className).toContain("lg:overflow-visible")
  })

  it("导航项在移动端始终显示文字标签，且不折行", () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    for (const label of ["稿件", "财务", "项目", "SOP/话术", "RSS 候选", "RSS 配置", "集成设置", "系统状态"]) {
      const link = screen.getByRole("link", { name: label })
      const labelSpan = link.querySelector("span")
      expect(labelSpan?.className).not.toContain("hidden")
      expect(link.className).toContain("whitespace-nowrap")
    }
    expect(nav.querySelector("ul")?.className).toContain("flex")
  })

  it("移动端退出与主题按钮为 44px 纯图标按钮，桌面端恢复文字按钮", () => {
    renderShell()
    const logoutButton = screen.getByRole("button", { name: "退出登录" })
    const themeButton = screen.getByRole("button", { name: /切换到/ })
    for (const button of [logoutButton, themeButton]) {
      expect(button.className).toContain("h-11")
      expect(button.className).toContain("w-11")
      expect(button.className).toContain("lg:w-fit")
      const label = button.querySelector("span")
      expect(label?.className).toContain("hidden")
      expect(label?.className).toContain("lg:inline")
    }
  })
})
