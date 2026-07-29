import type { LabelHTMLAttributes } from "react"

import { cn } from "@/lib/utils"

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-xs font-bold tracking-[0.12em] text-[var(--muted)] uppercase", className)} {...props} />
}
