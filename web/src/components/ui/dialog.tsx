import { AlertTriangle, X } from "lucide-react"
import * as Dialog from "@radix-ui/react-dialog"
import type { RefObject } from "react"

import { Button } from "./button"

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
  returnFocusRef?: RefObject<HTMLButtonElement | null>
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  return (
    <Dialog.Root onOpenChange={(open) => !open && props.onClose()} open={props.open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 border border-[var(--ink)] bg-[var(--paper)] p-6 shadow-[10px_10px_0_var(--ink)]"
          onCloseAutoFocus={(event) => {
            if (!props.returnFocusRef?.current) return
            event.preventDefault()
            props.returnFocusRef.current.focus()
          }}
        >
          <div className="flex items-start justify-between gap-6">
            <AlertTriangle aria-hidden className="mt-1 text-[var(--red)]" />
            <div className="flex-1">
              <Dialog.Title className="font-display text-2xl">{props.title}</Dialog.Title>
              <Dialog.Description className="mt-3 text-sm leading-6 text-[var(--muted)]">{props.description}</Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="关闭确认对话框" size="sm" variant="ghost"><X size={16} /></Button>
            </Dialog.Close>
          </div>
          <div className="mt-7 flex justify-end gap-3">
            <Dialog.Close asChild><Button variant="outline">取消</Button></Dialog.Close>
            <Button disabled={props.busy} onClick={props.onConfirm} variant="danger">{props.confirmLabel}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
