import type { HTMLAttributes } from "react"

import { cn } from "@/lib/utils"

export function Separator({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn("h-px w-full bg-[var(--line)]", className)} role="separator" {...props} />
}
