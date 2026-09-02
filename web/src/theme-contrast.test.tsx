import { readFileSync } from "node:fs"
import path from "node:path"

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { Button } from "@/components/ui/button"
import { LoginPage } from "@/features/auth/login-page"

const themeCss = readFileSync(path.resolve(process.cwd(), "src/index.css"), "utf8")

describe("Notion 蓝灰主题对比度契约", () => {
  it("为浅色和深色主题提供经验证的语义色 token", () => {
    expect(themeCss).toMatch(/:root\s*{[^}]*--signal:\s*#0B65A3;/s)
    expect(themeCss).toMatch(/:root\s*{[^}]*--muted:\s*#6B6A67;/s)
    expect(themeCss).toMatch(/:root\s*{[^}]*--danger:\s*#B42318;/s)
    expect(themeCss).toMatch(/:root\s*{[^}]*--on-signal:\s*#FFFFFF;/s)
    expect(themeCss).toMatch(/:root\s*{[^}]*--on-danger:\s*#FFFFFF;/s)

    expect(themeCss).toMatch(/html\[data-theme="dark"\]\s*{[^}]*--signal:\s*#6EB6E8;/s)
    expect(themeCss).toMatch(/html\[data-theme="dark"\]\s*{[^}]*--muted:\s*#A7A7A4;/s)
    expect(themeCss).toMatch(/html\[data-theme="dark"\]\s*{[^}]*--danger:\s*#FF7B72;/s)
    expect(themeCss).toMatch(/html\[data-theme="dark"\]\s*{[^}]*--on-signal:\s*#191919;/s)
    expect(themeCss).toMatch(/html\[data-theme="dark"\]\s*{[^}]*--on-danger:\s*#191919;/s)
  })

  it("共享按钮使用与主题对应的 signal 和 danger 前景", () => {
    render(
      <>
        <Button>保存</Button>
        <Button variant="danger">删除</Button>
      </>,
    )

    const defaultButton = screen.getByRole("button", { name: "保存" })
    expect(defaultButton).toHaveClass("text-[var(--on-signal)]", "hover:-translate-y-px", "active:translate-y-px!")
    expect(defaultButton.className).not.toMatch(/hover:opacity-/)
    expect(screen.getByRole("button", { name: "删除" })).toHaveClass("hover:text-[var(--on-danger)]")
  })

  it("登录按钮使用 signal 的语义前景", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    const loginButton = screen.getByRole("button", { name: "登录" })
    expect(loginButton).toHaveClass("text-[var(--on-signal)]", "hover:-translate-y-px", "active:translate-y-px!")
    expect(loginButton.className).not.toMatch(/hover:opacity-/)
  })
})
