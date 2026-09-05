import * as Dialog from "@radix-ui/react-dialog"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"

import { confirmEntry, type FinanceEntry } from "./finance-api"
import { formatMoney, todayShanghai } from "./finance-utils"

type ConfirmSettleDialogProps = {
  entry: FinanceEntry | null
  onClose: () => void
}

export function ConfirmSettleDialog({ entry, onClose }: ConfirmSettleDialogProps) {
  if (!entry) return null
  return <ConfirmSettleDialogInner entry={entry} onClose={onClose} />
}

function ConfirmSettleDialogInner({ entry, onClose }: { entry: FinanceEntry; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [occurredOn, setOccurredOn] = useState(todayShanghai)
  const actionLabel = entry.status === "应收" ? "确认收款" : "确认付款"

  const mutation = useMutation({
    mutationFn: () => confirmEntry(entry.id, occurredOn),
    onSuccess: async () => {
      toast.success(`${actionLabel}成功`)
      await queryClient.invalidateQueries({ queryKey: ["finance"] })
      onClose()
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("该款项已确认，请刷新查看")
        await queryClient.invalidateQueries({ queryKey: ["finance"] })
        onClose()
        return
      }
      toast.error(error instanceof Error ? error.message : `${actionLabel}失败，请重试`)
    },
  })

  function submit() {
    if (!occurredOn) {
      toast.error("请选择实际收付日期")
      return
    }
    mutation.mutate()
  }

  return (
    <Dialog.Root onOpenChange={(open) => !open && onClose()} open>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg">
          <Dialog.Title className="text-lg font-semibold text-[var(--ink)]">{actionLabel}</Dialog.Title>
          <Dialog.Description className="mt-3 text-sm leading-6 text-[var(--muted)]">
            {entry.name} · {formatMoney(entry.amount_cents)}。确认后按实际收付日期计入流水与汇总。
          </Dialog.Description>
          <div className="mt-4 space-y-2">
            <Label htmlFor="confirm-settle-date">实际收付日期</Label>
            <Input
              id="confirm-settle-date"
              onChange={(event) => setOccurredOn(event.target.value)}
              type="date"
              value={occurredOn}
            />
          </div>
          <div className="mt-7 flex justify-end gap-3">
            <Button onClick={onClose} type="button" variant="outline">取消</Button>
            <Button disabled={mutation.isPending} onClick={submit} type="button">{actionLabel}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
