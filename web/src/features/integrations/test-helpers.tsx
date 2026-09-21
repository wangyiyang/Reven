import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"

import { IntegrationsPage } from "./integrations-page"
import type { Integration } from "./types"

export const configuredRuntime = {
  provider: "embedding",
  public_config: { base_url: "https://api.siliconflow.cn", model: "BAAI/bge-m3" },
  secret_configured: true,
  secret_hint: "已配置 · ****9f2a",
  connection_status: "连接正常",
  last_tested_at: "2026-07-30T00:01:00Z",
  last_error: null,
  last_latency_ms: null,
}

export const configuredBaidu = {
  provider: "translate_baidu",
  public_config: { priority: 2, enabled: true },
  secret_configured: true,
  secret_hint: "已配置 · ****key1",
  connection_status: "连接正常",
  last_tested_at: "2026-08-20T00:01:00Z",
  last_error: null,
  last_latency_ms: 235,
}

export const configuredEmbedding = {
  provider: "embedding",
  public_config: { base_url: "https://api.siliconflow.cn", model: "BAAI/bge-m3" },
  secret_configured: true,
  secret_hint: "已配置 · ****key2",
  connection_status: "未测试",
  last_tested_at: null,
  last_error: null,
  last_latency_ms: null,
}

export const configuredFeishuBot: Integration = {
  provider: "feishu_bot",
  public_config: { whitelist_open_ids: ["ou_boss", "ou_ops"], enabled: true },
  secret_configured: true,
  secret_hint: "已配置 · ****alue",
  connection_status: "连接正常",
  last_tested_at: "2026-09-19T00:01:00Z",
  last_error: null,
  last_latency_ms: null,
}

export const latestRun = {
  run_date: "2026-08-25",
  status: "completed",
  started_at: "2026-08-25T00:00:00Z",
  finished_at: "2026-08-25T00:05:00Z",
  candidate_count: 12,
  failure_count: 0,
  errors: [],
  notification_error: null,
}

export async function findCard(title: string) {
  const heading = await screen.findByRole("heading", { name: title })
  const article = heading.closest("article")
  if (!article) throw new Error(`找不到 ${title} 卡片`)
  return within(article as HTMLElement)
}

export function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <IntegrationsPage />
    </QueryClientProvider>,
  )
}
