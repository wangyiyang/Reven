import * as React from "react"

import { cn } from "@/lib/utils"

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn("min-h-24 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] p-3 text-sm outline-none focus:border-[var(--signal)]", className)}
      {...props}
    />
  )
}
