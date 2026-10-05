import * as Dialog from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "./button"

interface DrawerProps {
  open: boolean
  title: string
  /** 屏幕阅读器补充描述（sr-only），缺省复用 title；存在是为满足 Radix 的 Description 要求 */
  description?: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
}

export function Drawer(props: DrawerProps) {
  return (
    <Dialog.Root onOpenChange={(open) => !open && props.onClose()} open={props.open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/20 data-[state=closed]:animate-[drawer-fade-out_200ms_ease-in] data-[state=open]:animate-[drawer-fade-in_240ms_ease-out]" />
        <Dialog.Content className="fixed top-0 right-0 z-50 flex h-full w-full flex-col rounded-l-2xl border-l border-[var(--line)] bg-[var(--bg)] shadow-2xl data-[state=closed]:animate-[drawer-slide-out_240ms_ease-in] data-[state=open]:animate-[drawer-slide-in_320ms_cubic-bezier(0.22,1,0.36,1)] sm:max-w-md">
          <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] px-6 py-4">
            <Dialog.Title className="text-lg font-semibold text-[var(--ink)]">{props.title}</Dialog.Title>
            <Dialog.Close asChild>
              <Button aria-label="关闭抽屉" size="sm" variant="ghost"><X size={16} /></Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">{props.description ?? props.title}</Dialog.Description>
          <div className="flex-1 overflow-y-auto px-6 py-5">{props.children}</div>
          {props.footer ? <div className="border-t border-[var(--line)] px-6 py-4">{props.footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
