import { useQuery, useQueryClient } from "@tanstack/react-query"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { fetchSystemHealth, fetchSystemStatus, type Heartbeat } from "./system-api"

export function SystemPage() {
  const queryClient = useQueryClient()
  const healthQuery = useQuery({
    queryKey: ["system", "health"],
    queryFn: fetchSystemHealth,
  })
  const statusQuery = useQuery({
    queryKey: ["system", "status"],
    queryFn: fetchSystemStatus,
  })

  const loading = healthQuery.isLoading || statusQuery.isLoading
  const error = healthQuery.error ?? statusQuery.error

  return (
    <main className="page-enter mx-auto w-full max-w-4xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">系统状态</h1>
          <p className="mt-2 text-sm text-[var(--muted)]">后端服务与各后台任务的运行健康度。</p>
        </div>
        <Button
          disabled={loading}
          onClick={() => void queryClient.invalidateQueries({ queryKey: ["system"] })}
          size="sm"
          type="button"
          variant="outline"
        >刷新</Button>
      </header>

      {loading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取系统状态…</p>}
      {error && (
        <div className="border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert">
          <p>系统状态读取失败：{error.message}</p>
          <Button
            className="mt-4"
            onClick={() => void queryClient.invalidateQueries({ queryKey: ["system"] })}
            size="sm"
            variant="outline"
          >重新读取</Button>
        </div>
      )}

      {healthQuery.data && statusQuery.data && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Card data-testid="system-service">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <h2 className="text-base font-semibold">后端服务</h2>
              <StatusBadge ok={healthQuery.data.status === "ok"} />
            </CardHeader>
            <CardContent className="text-sm text-[var(--muted)]">
              服务标识 <span className="font-mono text-[var(--ink)]">{healthQuery.data.service}</span>
            </CardContent>
          </Card>

          <Card data-testid="system-database">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <h2 className="text-base font-semibold">数据库</h2>
              <StatusBadge ok={statusQuery.data.database.available} />
            </CardHeader>
            <CardContent className="text-sm text-[var(--muted)]">连接探测（SELECT 1）</CardContent>
          </Card>

          <HeartbeatCard label="RSS 内容发现" state={statusQuery.data.rss_discovery} testId="system-rss-discovery" />
        </div>
      )}
    </main>
  )
}

function StatusBadge({ ok }: { ok: boolean }) {
  return ok
    ? <Badge className="text-[var(--signal)]">正常</Badge>
    : <Badge className="text-[var(--danger)]">未运行</Badge>
}

function HeartbeatCard({ label, state, testId }: { label: string; state: Heartbeat; testId: string }) {
  return (
    <Card data-testid={testId}>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{label}</h2>
        <StatusBadge ok={state.available} />
      </CardHeader>
      <CardContent className="text-sm text-[var(--muted)]">
        最近心跳 {state.last_heartbeat_at ? formatHeartbeat(state.last_heartbeat_at) : "—"}
      </CardContent>
    </Card>
  )
}

function formatHeartbeat(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date)
}
