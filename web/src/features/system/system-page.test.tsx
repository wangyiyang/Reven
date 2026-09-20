import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import userEvent from "@testing-library/user-event"
import { render, screen } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { SystemPage } from "./system-page"

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SystemPage />
    </QueryClientProvider>,
  )
}

describe("SystemPage", () => {
  it("shows service, database and RSS discovery status", async () => {
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () =>
        HttpResponse.json({
          database: { available: true },
          rss_discovery: { available: true, last_heartbeat_at: "2026-08-20T01:00:00Z" },
        }),
      ),
    )

    renderPage()

    expect(await screen.findByRole("heading", { name: "系统状态" })).toBeInTheDocument()
    expect(await screen.findByText("reven")).toBeInTheDocument()

    const databaseRow = screen.getByTestId("system-database")
    expect(databaseRow).toHaveTextContent("数据库")
    expect(databaseRow).toHaveTextContent("正常")

    const syncRow = screen.getByTestId("system-rss-discovery")
    expect(syncRow).toHaveTextContent("RSS 内容发现")
    expect(syncRow).toHaveTextContent("正常")
    expect(syncRow).toHaveTextContent("2026")

    expect(screen.queryByTestId("system-notion-sync")).not.toBeInTheDocument()
    expect(screen.queryByTestId("system-scheduler")).not.toBeInTheDocument()
  })

  it("reports backend failure honestly", async () => {
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () => HttpResponse.json({ message: "db down" }, { status: 500 })),
    )

    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("系统状态读取失败")
  })
  it("shows unavailable RSS with no heartbeat", async () => {
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () => HttpResponse.json({
        database: { available: true }, rss_discovery: { available: false, last_heartbeat_at: null },
      })),
    )
    renderPage()
    expect(await screen.findByTestId("system-rss-discovery")).toHaveTextContent("未运行")
    expect(screen.getByTestId("system-rss-discovery")).toHaveTextContent("最近心跳 —")
  })

  it("rejects malformed responses and allows retry", async () => {
    let failed = true
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () => HttpResponse.json(failed ? {} : {
        database: { available: true }, rss_discovery: { available: true, last_heartbeat_at: null },
      })),
    )
    renderPage()
    expect(await screen.findByRole("alert")).toHaveTextContent("系统状态响应格式无效")
    failed = false
    await userEvent.click(screen.getByRole("button", { name: "重新读取" }))
    expect(await screen.findByTestId("system-rss-discovery")).toHaveTextContent("正常")
  })

})
