import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

export function StatusBadge({ enabled }: { enabled: boolean }) {
  return <Badge className={enabled ? "text-[var(--signal)]" : "text-[var(--muted)]"}>{enabled ? "已启用" : "已停用"}</Badge>
}

export function ErrorPanel({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert">
      <p>RSS 配置读取失败：{message}</p>
      <Button className="mt-4" onClick={retry} size="sm" variant="outline">重新读取</Button>
    </div>
  )
}
