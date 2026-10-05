import { AlertTriangle, X } from "lucide-react"
import * as Dialog from "@radix-ui/react-dialog"
import type { ReactNode, RefObject } from "react"

import { Button } from "./button"

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  busy?: boolean
  /** danger（默认）：删除等破坏性确认，带警示图标与危险色按钮；primary：结算等普通确认 */
  tone?: "danger" | "primary"
  /** 额外内容（如结算日期输入），渲染在描述与按钮之间 */
  children?: ReactNode
  onConfirm: () => void
  onClose: () => void
  returnFocusRef?: RefObject<HTMLButtonElement | null>
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  const tone = props.tone ?? "danger"
  return (
    <Dialog.Root onOpenChange={(open) => !open && props.onClose()} open={props.open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg"
          onCloseAutoFocus={(event) => {
            if (!props.returnFocusRef?.current) return
            event.preventDefault()
            props.returnFocusRef.current.focus()
          }}
        >
          <div className="flex items-start justify-between gap-6">
            {tone === "danger" ? <AlertTriangle aria-hidden className="mt-1 text-[var(--danger)]" /> : null}
            <div className="flex-1">
              <Dialog.Title className="text-lg font-semibold">{props.title}</Dialog.Title>
              <Dialog.Description className="mt-3 text-sm leading-6 text-[var(--muted)]">{props.description}</Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="关闭确认对话框" size="sm" variant="ghost"><X size={16} /></Button>
            </Dialog.Close>
          </div>
          {props.children ? <div className="mt-4">{props.children}</div> : null}
          <div className="mt-7 flex justify-end gap-3">
            <Dialog.Close asChild><Button variant="outline">取消</Button></Dialog.Close>
            <Button disabled={props.busy} onClick={props.onConfirm} variant={tone === "danger" ? "danger" : "default"}>{props.confirmLabel}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
