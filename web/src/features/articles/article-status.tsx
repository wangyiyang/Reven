import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle, MinusCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type Tone = "waiting" | "working" | "failed" | "done" | "neutral"

const tones: Record<Tone, string> = {
  waiting: "border-[var(--muted)] text-[var(--muted)]",
  working: "border-[var(--muted)] text-[var(--muted)]",
  failed: "border-[var(--danger)] text-[var(--danger)]",
  done: "border-[var(--signal)] text-[var(--signal)]",
  neutral: "border-[var(--line)] text-[var(--muted)]",
}

function toneFor(status: string | null): Tone {
  if (!status || /未开始/.test(status)) return "neutral"
  if (/等待|计划|待处理|待发布/.test(status)) return "waiting"
  if (/同步中|处理|上传|构建|发布中|合并中|准备/.test(status)) return "working"
  if (/过期|阻塞|失败|异常|取消/.test(status)) return "failed"
  if (/已同步|完成|成功|上线|草稿已生成|已交付|已发布/.test(status)) return "done"
  return "neutral"
}

const icons = {
  waiting: Clock3,
  working: LoaderCircle,
  failed: AlertTriangle,
  done: CheckCircle2,
  neutral: MinusCircle,
}

export function ArticleStatus({ status, compact = false }: { status: string | null; compact?: boolean }) {
  const tone = toneFor(status)
  const Icon = icons[tone]
  const label = status ?? "暂无任务"
  return (
    <Badge className={cn("gap-1.5 normal-case", tones[tone], compact && "px-1.5 py-0.5 text-[10px]")}>
      <Icon aria-hidden className={tone === "working" ? "animate-spin" : ""} size={12} />
      {label}
    </Badge>
  )
}
