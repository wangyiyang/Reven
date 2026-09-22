import { Badge } from "@/components/ui/badge"

export function StatusBadge({ enabled }: { enabled: boolean }) {
  return <Badge className={enabled ? "text-[var(--signal)]" : "text-[var(--muted)]"}>{enabled ? "已启用" : "已停用"}</Badge>
}
