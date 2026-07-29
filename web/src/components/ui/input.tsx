import * as React from "react"

import { cn } from "@/lib/utils"

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full border-0 border-b border-[var(--line)] bg-transparent px-0 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--muted)] focus:border-[var(--blue)] focus:ring-0",
        className,
      )}
      {...props}
    />
  )
}
