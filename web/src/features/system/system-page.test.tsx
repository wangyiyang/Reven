import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
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
  it("shows service, database, sync and scheduler status", async () => {
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () =>
        HttpResponse.json({
          database: { available: true },
          notion_sync: { available: true, last_heartbeat_at: "2026-08-20T01:00:00Z" },
          scheduler: { available: false, last_heartbeat_at: null },
        }),
      ),
    )

    renderPage()

    expect(await screen.findByRole("heading", { name: "系统状态" })).toBeInTheDocument()
    expect(await screen.findByText("reven")).toBeInTheDocument()

    const databaseRow = screen.getByTestId("system-database")
    expect(databaseRow).toHaveTextContent("数据库")
    expect(databaseRow).toHaveTextContent("正常")

    const syncRow = screen.getByTestId("system-notion-sync")
    expect(syncRow).toHaveTextContent("Notion 同步")
    expect(syncRow).toHaveTextContent("正常")
    expect(syncRow).toHaveTextContent("2026")

    const schedulerRow = screen.getByTestId("system-scheduler")
    expect(schedulerRow).toHaveTextContent("调度器")
    expect(schedulerRow).toHaveTextContent("未运行")
  })

  it("reports backend failure honestly", async () => {
    server.use(
      http.get("/api/health", () => HttpResponse.json({ service: "reven", status: "ok" })),
      http.get("/api/system/status", () => HttpResponse.json({ message: "db down" }, { status: 500 })),
    )

    renderPage()

    expect(await screen.findByRole("alert")).toHaveTextContent("系统状态读取失败")
  })
})
