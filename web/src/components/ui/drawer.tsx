import * as Dialog from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "./button"

interface DrawerProps {
  open: boolean
  title: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
}

export function Drawer(props: DrawerProps) {
  return (
    <Dialog.Root onOpenChange={(open) => !open && props.onClose()} open={props.open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content className="fixed top-0 right-0 z-50 flex h-full w-full flex-col border-l border-[var(--line)] bg-[var(--bg)] shadow-lg sm:max-w-md">
          <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] px-6 py-4">
            <Dialog.Title className="text-lg font-semibold text-[var(--ink)]">{props.title}</Dialog.Title>
            <Dialog.Close asChild>
              <Button aria-label="关闭抽屉" size="sm" variant="ghost"><X size={16} /></Button>
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">{props.children}</div>
          {props.footer ? <div className="border-t border-[var(--line)] px-6 py-4">{props.footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
