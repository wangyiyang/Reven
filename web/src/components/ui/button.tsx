import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-md border px-4 text-sm font-semibold transition-[transform,background-color,color,border-color,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] disabled:pointer-events-none disabled:opacity-45 active:translate-y-px!",
  {
    variants: {
      variant: {
        default: "border-[var(--signal)] bg-[var(--signal)] text-[var(--on-signal)] hover:-translate-y-px",
        outline: "border-[var(--line)] bg-transparent text-[var(--ink)] hover:border-[var(--ink)] hover:bg-[var(--faint)]",
        danger: "border-[var(--danger)] bg-transparent text-[var(--danger)] hover:bg-[var(--danger)] hover:text-[var(--on-danger)]",
        ghost: "border-transparent bg-transparent hover:bg-[var(--faint)]",
      },
      size: { default: "h-10", sm: "h-9 px-3 text-xs" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
  ),
)

Button.displayName = "Button"
