import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex min-h-10 items-center justify-center gap-2 border px-4 text-sm font-semibold transition-[transform,background-color,color,border-color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--blue)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45 active:translate-y-px",
  {
    variants: {
      variant: {
        default: "border-[var(--ink)] bg-[var(--ink)] text-[var(--paper)] hover:bg-[var(--red)] hover:border-[var(--red)]",
        outline: "border-[var(--line)] bg-transparent text-[var(--ink)] hover:border-[var(--ink)] hover:bg-white/50",
        danger: "border-[var(--red)] bg-transparent text-[var(--red)] hover:bg-[var(--red)] hover:text-white",
        ghost: "border-transparent bg-transparent hover:bg-black/5",
      },
      size: { default: "h-10", sm: "h-9 px-3 text-xs" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
