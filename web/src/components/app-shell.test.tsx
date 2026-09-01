import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "./app-shell"

const RSS_NAV_OPEN_KEY = "reven:nav:rss-open"

function renderShell(initialEntries = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <AppShell>
        <div>内容</div>
      </AppShell>
    </MemoryRouter>,
  )
}

describe("AppShell 移动端布局", () => {
  beforeEach(() => {
    localStorage.clear()
  })
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

  it("tab 条可右滑时显示渐隐与箭头提示，滑到底后隐藏", async () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    // jsdom 无真实布局，模拟 390px 视口下内容溢出
    Object.defineProperty(nav, "scrollWidth", { configurable: true, value: 796 })
    Object.defineProperty(nav, "clientWidth", { configurable: true, value: 350 })
    let scrollLeft = 0
    Object.defineProperty(nav, "scrollLeft", { configurable: true, get: () => scrollLeft })
    const scrollBy = vi.fn(({ left }: { left: number }) => { scrollLeft += left })
    Object.defineProperty(nav, "scrollBy", { configurable: true, value: scrollBy })

    fireEvent(nav, new Event("scroll"))
    const hint = await screen.findByRole("button", { name: "还有更多模块，向右滑动查看" })
    expect(hint.className).toContain("lg:hidden")

    await userEvent.click(hint)
    expect(scrollBy).toHaveBeenCalledWith(expect.objectContaining({ left: 220 }))

    // 滑到底后提示消失
    scrollLeft = 500
    fireEvent(nav, new Event("scroll"))
    await waitFor(() => expect(screen.queryByRole("button", { name: "还有更多模块，向右滑动查看" })).not.toBeInTheDocument())
  })

  it("tab 条无溢出时不显示滑动提示", () => {
    renderShell()
    // jsdom 默认 scrollWidth=clientWidth=0，无溢出
    expect(screen.queryByRole("button", { name: "还有更多模块，向右滑动查看" })).not.toBeInTheDocument()
  })

  it("导航项在移动端始终显示文字标签，且不折行", () => {
    renderShell()
    const nav = screen.getByRole("navigation", { name: "内容工作台主导航" })
    for (const label of ["稿件", "CRM", "人才库", "财务", "项目", "SOP/话术", "RSS 候选", "RSS 源", "RSS 关键词", "集成设置", "系统状态"]) {
      const link = screen.getByRole("link", { name: label })
      const labelSpan = link.querySelector("span")
      expect(labelSpan?.className).not.toContain("hidden")
      expect(link.className).toContain("whitespace-nowrap")
    }
    expect(nav.querySelector("ul")?.className).toContain("flex")
  })

  it("RSS 分组在非 RSS 页面默认收起，点击展开并持久化偏好", async () => {
    renderShell()
    const toggle = screen.getByRole("button", { name: "RSS" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    // 移动端 tab 条不支持层级：折叠按钮仅桌面端可见，子项始终平铺
    expect(toggle.className).toContain("hidden")
    expect(toggle.className).toContain("lg:flex")
    const sublist = () => toggle.parentElement?.querySelector("ul")
    expect(sublist()?.className).toContain("lg:hidden")

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(sublist()?.className).not.toContain("lg:hidden")
    expect(localStorage.getItem(RSS_NAV_OPEN_KEY)).toBe("true")
  })

  it("无存储偏好时，RSS 路由下分组自动展开", () => {
    renderShell(["/rss/sources"])
    expect(screen.getByRole("button", { name: "RSS" })).toHaveAttribute("aria-expanded", "true")
  })

  it("存储的收起偏好优先于路由：RSS 页面内也保持收起", () => {
    localStorage.setItem(RSS_NAV_OPEN_KEY, "false")
    renderShell(["/rss/sources"])
    expect(screen.getByRole("button", { name: "RSS" })).toHaveAttribute("aria-expanded", "false")
  })

  it("存储的展开偏好在非 RSS 页面同样生效", () => {
    localStorage.setItem(RSS_NAV_OPEN_KEY, "true")
    renderShell()
    expect(screen.getByRole("button", { name: "RSS" })).toHaveAttribute("aria-expanded", "true")
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
